"""
Provisión mensual de Vacaciones.

Mismo criterio contable que la gratificación (ver provision_gratificacion.py): se reconoce el
gasto MES A MES, con corte en julio 2026, y el pasivo "Vacaciones por pagar" lo cancelan el
pago de vacaciones gozadas (asiento de planilla) y la liquidación por cese (vacaciones truncas).

Diferencia clave: la gratificación se paga en bloque cada semestre; las vacaciones se van
CONSUMIENDO al gozarse, así que el libro guarda el SALDO del pasivo, no solo deltas:

    objetivo(M)  = días devengados no gozados al cierre de M × (sueldo / 30)
    cancelado(M) = min(pago de "Descanso Vacacional" en la planilla de M, saldo(M−1))
    provisión(M) = objetivo(M) − (saldo(M−1) − cancelado(M))        saldo(M) = objetivo(M)

El primer mes (julio 2026) no tiene saldo previo, así que provisiona de golpe el devengo de
enero a julio 2026: es la regularización "ajuste en julio". El saldo de ejercicios ANTERIORES
(al 31/12/2025) NO se provisiona: la empresa ya lo tiene provisionado en su contabilidad y
volver a reconocerlo duplicaría el gasto (ver `_dias_saldo`). Los meses anteriores al corte no se tocan.

Días devengados: el Kardex (`calcular_saldo_vacacional`), recortado a lo registrado hasta el cierre
del mes (un registro de vacaciones posterior no debe alterar la provisión de un mes ya cerrado).
Valorización: sueldo base / 30, igual que la liquidación por cese ("vacaciones truncas"), para que
ambas coincidan. No incluye EsSalud patronal (queda como gasto del mes en que se paga).
"""
import calendar
import datetime
import io
import json
import types

import pandas as pd

from infrastructure.database.models import (
    Trabajador, ConfiguracionContable, ProvisionVacaciones,
)
from core.use_cases.calculo_kardex import calcular_saldo_vacacional
from core.use_cases.generador_asiento_contable import (
    AsientoContableError, _fila, COLUMNAS_SISCONT, MESES_ES,
)
from core.use_cases.provision_gratificacion import INICIO_PROVISION, _planilla_cerrada, rmv_al
from core.use_cases import valorizacion_vacaciones as vv

# Cuentas (ConfiguracionContable): las mismas que ya usan el asiento de planilla y la liquidación
CUENTA_GASTO = 'cuenta_descanso_vacacional'
CUENTA_PASIVO = 'cuenta_vacaciones_por_pagar'

# Nombre con que el motor de planilla guarda lo pagado por vacaciones gozadas (auditoria.ingresos)
CLAVE_PAGO_VACACIONES = "Descanso Vacacional"

VERSION_PROVISION_VAC = "2026-11-25-r2"


# ── Helpers de periodo ───────────────────────────────────────────────────────────

def _anio_mes(periodo_key: str) -> tuple:
    return int(periodo_key[3:]), int(periodo_key[:2])


def periodo_anterior(periodo_key: str) -> str:
    anio, mes = _anio_mes(periodo_key)
    return f"{mes - 1:02d}-{anio}" if mes > 1 else f"12-{anio - 1}"


def motivo_no_provisionable(periodo_key: str):
    """None si el periodo se puede provisionar; si no, el motivo (listo para mostrar)."""
    if _anio_mes(periodo_key) < INICIO_PROVISION:
        return "La provisión de vacaciones arranca en julio 2026 (corte acordado); este periodo es anterior."
    return None


def es_provisionable(periodo_key: str) -> bool:
    return motivo_no_provisionable(periodo_key) is None


# ── Libro de provisiones (lectura) ───────────────────────────────────────────────

def _filas_libro(db, empresa_id: int):
    return db.query(ProvisionVacaciones).filter_by(empresa_id=empresa_id).all()


def periodo_registrado(db, empresa_id: int, periodo_key: str) -> bool:
    return db.query(ProvisionVacaciones).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first() is not None


def libro_en_uso(db, empresa_id: int) -> bool:
    return db.query(ProvisionVacaciones).filter_by(empresa_id=empresa_id).first() is not None


def saldos_previos(db, empresa_id: int, periodo_key: str) -> dict:
    """{trabajador_id: saldo} — el último saldo contable registrado ANTES de este periodo."""
    limite = _anio_mes(periodo_key)
    ultimo = {}
    for f in _filas_libro(db, empresa_id):
        ym = _anio_mes(f.periodo_key)
        if ym < limite and (f.trabajador_id not in ultimo or ym > ultimo[f.trabajador_id][0]):
            ultimo[f.trabajador_id] = (ym, float(f.saldo or 0.0))
    return {tid: round(s, 2) for tid, (_, s) in ultimo.items()}


def saldos_previos_por_dni(db, empresa_id: int, periodo_key: str) -> dict:
    por_id = saldos_previos(db, empresa_id, periodo_key)
    if not por_id:
        return {}
    docs = {t.id: str(t.num_doc) for t in db.query(Trabajador).filter(Trabajador.id.in_(list(por_id))).all()}
    return {docs[i]: s for i, s in por_id.items() if i in docs}


def saldo_vigente_trabajador(db, empresa_id: int, trabajador_id: int) -> float:
    """Último saldo contable registrado de un trabajador (para la liquidación por cese)."""
    ultimo = None
    for f in db.query(ProvisionVacaciones).filter_by(empresa_id=empresa_id, trabajador_id=trabajador_id).all():
        ym = _anio_mes(f.periodo_key)
        if ultimo is None or ym > ultimo[0]:
            ultimo = (ym, float(f.saldo or 0.0))
    return round(ultimo[1], 2) if ultimo else 0.0


def cancelaciones_planilla(db, empresa_id: int, periodo_key: str, auditoria_data: dict) -> dict:
    """
    {dni: monto} de lo pagado por vacaciones gozadas en la planilla del mes que se cancela
    contra el pasivo provisionado (el resto, si lo hay, es gasto). Lo usa el asiento de planilla.

    Si el libro ya está en uso, exige que el mes anterior esté registrado: el saldo previo
    determina cuánto se cancela, y registrarlo después dejaría este asiento inconsistente.
    """
    pagos = {
        str(dni): round(float(((info or {}).get('ingresos', {}) or {}).get(CLAVE_PAGO_VACACIONES, 0) or 0), 2)
        for dni, info in (auditoria_data or {}).items()
    }
    pagos = {d: p for d, p in pagos.items() if p > 0}
    if not pagos or _anio_mes(periodo_key) <= INICIO_PROVISION or not es_provisionable(periodo_key):
        return {}
    if libro_en_uso(db, empresa_id) and not periodo_registrado(db, empresa_id, periodo_anterior(periodo_key)):
        raise AsientoContableError(
            f"Falta registrar la provisión de vacaciones de {periodo_anterior(periodo_key)}: el asiento de "
            f"{periodo_key} cancela vacaciones gozadas contra ese saldo. Registre primero esa provisión "
            f"(Reportería → Asiento Contable → Provisión de Vacaciones)."
        )
    previos = saldos_previos_por_dni(db, empresa_id, periodo_key)
    return {d: round(min(p, previos.get(d, 0.0)), 2) for d, p in pagos.items() if previos.get(d, 0.0) > 0}


# ── Cálculo de la provisión del mes ──────────────────────────────────────────────

def _kardex_al(t, fecha: datetime.date) -> dict:
    """Kardex del trabajador recortado a `fecha` (un registro posterior no altera meses ya cerrados)."""
    registros = [r for r in (t.vacaciones or []) if r.fecha_inicio and r.fecha_inicio <= fecha]
    cese = t.fecha_cese if (t.fecha_cese and t.fecha_cese <= fecha) else None
    sim = types.SimpleNamespace(
        fecha_ingreso=t.fecha_ingreso, fecha_cese=cese,
        dias_vacaciones_anuales=getattr(t, 'dias_vacaciones_anuales', None) or 30,
    )
    return calcular_saldo_vacacional(sim, registros, fecha_calculo=fecha)


def _dias_saldo(t, fin_mes: datetime.date) -> float:
    """
    Días a PROVISIONAR al cierre del mes: devengo desde el corte (enero 2026), sin el saldo de
    ejercicios anteriores, que ya está provisionado en la contabilidad de la empresa.

    Los días gozados desde el corte consumen primero ese saldo viejo (el más antiguo se goza antes);
    solo si lo agotan empiezan a restar del devengo nuevo:

        viejo_restante = max(0, saldo al 31/12/2025 − consumidos desde 01/01/2026)
        a provisionar  = max(0, saldo al cierre − viejo_restante)
    """
    actual = _kardex_al(t, fin_mes)
    return max(0.0, float(actual.get('saldo', 0.0) or 0.0) - _dias_viejos_restantes(t, fin_mes, actual))


def _dias_viejos_restantes(t, fecha: datetime.date, actual: dict = None) -> float:
    """Días del saldo previo al corte (ya provisionados en la contabilidad) que siguen sin gozarse a `fecha`."""
    fin_previo = datetime.date(INICIO_PROVISION[0] - 1, 12, 31)
    actual = actual if actual is not None else _kardex_al(t, fecha)
    previo = _kardex_al(t, fin_previo)
    saldo_previo = max(0.0, float(previo.get('saldo', 0.0) or 0.0))
    consumidos_desde_corte = max(0.0, float(actual.get('consumidos', 0.0) or 0.0) - float(previo.get('consumidos', 0.0) or 0.0))
    return max(0.0, saldo_previo - consumidos_desde_corte)


def valor_saldo_previo_al_corte(db, trabajador_id: int, fecha: datetime.date,
                                dias_pagados: float, monto_pagado: float) -> float:
    """
    Valor (a la tasa diaria de la liquidación) de los días de ejercicios anteriores al corte que
    aún no se gozaron. Esa provisión vive en la contabilidad de la empresa, no en el libro del
    sistema: al liquidar, se cancela contra el pasivo y no se vuelve a llevar a gasto.
    Nunca supera lo que realmente se paga (`monto_pagado`).
    """
    if not dias_pagados or dias_pagados <= 0 or not monto_pagado or monto_pagado <= 0:
        return 0.0
    t = db.query(Trabajador).filter_by(id=trabajador_id).first()
    if not t or not t.fecha_ingreso or fecha < datetime.date(INICIO_PROVISION[0], INICIO_PROVISION[1], 1):
        return 0.0
    dias = min(_dias_viejos_restantes(t, fecha), dias_pagados)
    return round(min(dias * (monto_pagado / dias_pagados), monto_pagado), 2)


def calcular_provision_mes(db, empresa_id: int, periodo_key: str) -> list:
    """
    Provisión de vacaciones del mes por trabajador de planilla:
    [{dni, nombre, trabajador_id, dias_saldo, remuneracion_diaria, saldo_previo, cancelado,
      objetivo, delta}]. No escribe nada.
    """
    motivo = motivo_no_provisionable(periodo_key)
    if motivo:
        raise AsientoContableError(motivo)
    planilla = _planilla_cerrada(db, empresa_id, periodo_key)
    auditoria = json.loads(planilla.auditoria_json or '{}')

    anio, mes = _anio_mes(periodo_key)
    fin_mes = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1])
    previos = saldos_previos(db, empresa_id, periodo_key)

    filas = []
    for dni, info in auditoria.items():
        t = db.query(Trabajador).filter_by(empresa_id=empresa_id, num_doc=str(dni)).first()
        if not t or (t.tipo_contrato or 'PLANILLA') == 'LOCADOR' or not t.fecha_ingreso:
            continue
        sueldo = float((info or {}).get('sueldo_base_nominal') or 0) or float(t.sueldo_base or 0)
        # Misma base que la liquidación (vacaciones truncas): hoy solo sueldo; con
        # BASE_VACACIONAL_COMPUTABLE activo suma asignación familiar y variables regulares.
        rmv = rmv_al(db, empresa_id, fin_mes, t) if vv.BASE_VACACIONAL_COMPUTABLE else None
        base = vv.valorizar_remuneracion_vacacional(db, empresa_id, t, fin_mes, sueldo, rmv)['base_mensual']
        diaria = base / 30.0
        dias = _dias_saldo(t, fin_mes)
        objetivo = round(dias * diaria, 2)

        pago = float(((info or {}).get('ingresos', {}) or {}).get(CLAVE_PAGO_VACACIONES, 0) or 0)
        previo = previos.get(t.id, 0.0)
        cancelado = round(min(pago, previo), 2) if previo > 0 else 0.0
        delta = round(objetivo - (previo - cancelado), 2)

        filas.append({
            "dni": str(dni), "nombre": (info or {}).get('nombres') or t.nombres, "trabajador_id": t.id,
            "dias_saldo": round(dias, 2), "remuneracion_diaria": round(diaria, 2),
            "saldo_previo": previo, "cancelado": cancelado, "objetivo": objetivo, "delta": delta,
        })
    return filas


# ── Asiento de provisión (Excel SISCONT) + registro en el libro ──────────────────

def generar_asiento_provision(db, empresa_id: int, periodo_key: str, generado_por: str = None) -> io.BytesIO:
    """
    Genera el voucher PV{mm}-{año} (gasto de vacaciones al débito / vacaciones por pagar al
    crédito, por trabajador) y REGISTRA el saldo en el libro. Reglas de orden: el mes anterior
    debe estar registrado (salvo julio 2026, el corte) y no puede haber meses posteriores.
    """
    anio, mes = _anio_mes(periodo_key)
    posteriores = sorted({
        f.periodo_key for f in _filas_libro(db, empresa_id) if _anio_mes(f.periodo_key) > (anio, mes)
    })
    if posteriores:
        raise AsientoContableError(
            f"Ya hay provisiones de vacaciones registradas de meses posteriores ({', '.join(posteriores)}). "
            f"No se puede regenerar {periodo_key} sin invalidarlas."
        )
    if (anio, mes) > INICIO_PROVISION and not periodo_registrado(db, empresa_id, periodo_anterior(periodo_key)):
        raise AsientoContableError(
            f"Registre primero la provisión de vacaciones de {periodo_anterior(periodo_key)}: el saldo de ese "
            f"mes es la base de {periodo_key}."
        )

    filas_calc = calcular_provision_mes(db, empresa_id, periodo_key)
    con_ledger = [f for f in filas_calc if f["objetivo"] > 0 or f["saldo_previo"] > 0 or abs(f["delta"]) > 0.004]
    con_asiento = [f for f in filas_calc if abs(f["delta"]) > 0.004]

    cfg = db.query(ConfiguracionContable).filter_by(empresa_id=empresa_id).first()
    cuenta_gasto = ((getattr(cfg, CUENTA_GASTO, None) if cfg else None) or "").strip()
    cuenta_pasivo = ((getattr(cfg, CUENTA_PASIVO, None) if cfg else None) or "").strip()
    faltantes = []
    if con_asiento and not cuenta_gasto:
        faltantes.append("Descanso Vacacional — Gasto (Configuración Contable)")
    if con_asiento and not cuenta_pasivo:
        faltantes.append("Vacaciones Por Pagar (Configuración Contable)")
    if faltantes:
        raise AsientoContableError(
            "Faltan cuentas contables por configurar antes de generar la provisión.",
            cuentas_faltantes=faltantes,
        )

    fecha_asiento = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1]).strftime('%d/%m/%Y')
    num_doc = f"PV{mes:02d}-{anio}"
    glosa = f"PROVISION VACACIONES {MESES_ES.get(mes, '')} {anio}"
    if (anio, mes) == INICIO_PROVISION:
        glosa += " - REGULARIZACION ENE-JUL"

    filas = []
    for f in con_asiento:
        monto = f["delta"]
        kw = dict(cod_prov_clie=f["dni"], ruc=f["dni"], r_social=f["nombre"])
        if monto > 0:
            filas.append(_fila(11, 1, fecha_asiento, cuenta_gasto, monto, 0.0, num_doc, glosa, **kw))
            filas.append(_fila(11, 1, fecha_asiento, cuenta_pasivo, 0.0, monto, num_doc, glosa, **kw))
        else:   # reverso: el saldo objetivo bajó más de lo consumido
            filas.append(_fila(11, 1, fecha_asiento, cuenta_pasivo, -monto, 0.0, num_doc, glosa, **kw))
            filas.append(_fila(11, 1, fecha_asiento, cuenta_gasto, 0.0, -monto, num_doc, glosa, **kw))

    if round(sum(x["Monto Debe"] for x in filas) - sum(x["Monto Haber"] for x in filas), 2) != 0:
        raise AsientoContableError(
            "El asiento de provisión de vacaciones no cuadra. No se generó el archivo — "
            "este es un error interno, no de configuración."
        )

    # ── Registrar en el libro (reemplaza el mes si ya existía) ──
    try:
        db.query(ProvisionVacaciones).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).delete()
        for f in con_ledger:
            db.add(ProvisionVacaciones(
                empresa_id=empresa_id, trabajador_id=f["trabajador_id"], periodo_key=periodo_key,
                dias_saldo=f["dias_saldo"], remuneracion_diaria=f["remuneracion_diaria"],
                cancelado=f["cancelado"], monto_provision=f["delta"], saldo=f["objetivo"],
                generado_por=generado_por,
            ))
        db.commit()
    except Exception:
        db.rollback()
        raise

    if not filas:
        raise AsientoContableError(
            f"No hay provisión de vacaciones pendiente en {periodo_key}: los saldos ya están al día "
            f"(se registraron en el libro para continuar el mes siguiente)."
        )

    from core.use_cases import numeracion_vouchers as _nv
    _nv.numerar_filas(db, empresa_id, periodo_key, _nv.CLAVE_PROV_VAC, filas)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        pd.DataFrame(filas, columns=COLUMNAS_SISCONT).to_excel(writer, index=False, sheet_name='Asiento')
    buffer.seek(0)
    return buffer


def resumen_libro(db, empresa_id: int, anio: int) -> list:
    """[(periodo_key, n_trabajadores, total_provision, saldo_total, fecha_generacion)] del año."""
    por_periodo = {}
    for f in _filas_libro(db, empresa_id):
        if not f.periodo_key.endswith(f"-{anio}"):
            continue
        n, prov, saldo, fch = por_periodo.get(f.periodo_key, (0, 0.0, 0.0, None))
        por_periodo[f.periodo_key] = (n + 1, prov + float(f.monto_provision or 0), saldo + float(f.saldo or 0),
                                      max(filter(None, [fch, f.fecha_generacion]), default=None))
    return sorted(
        [(p, n, round(a, 2), round(s, 2), fch) for p, (n, a, s, fch) in por_periodo.items()],
        key=lambda x: _anio_mes(x[0]),
    )
