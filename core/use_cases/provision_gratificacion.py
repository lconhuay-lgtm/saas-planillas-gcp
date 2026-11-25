"""
Provisión mensual de Gratificación (+ Bonificación Extraordinaria).

Contexto contable (acordado con el usuario):
  - Se reconoce el gasto MES A MES (devengado), no al pagar en julio/diciembre.
  - Corte: la provisión arranca en julio 2026. Lo anterior (enero–junio 2026) nunca se
    provisionó; su pago de julio se reconoce completo en julio (ajuste en julio), que es
    el resultado natural de la regla general de abajo con el libro vacío.
  - Los asientos de planilla de julio/diciembre y el de la liquidación por cese
    DESCUENTAN lo ya provisionado (libro `provisiones_gratificacion`): lo provisionado se
    cancela contra el pasivo, y solo la diferencia va a gasto (o se recupera si sobró).

Método — acumulado objetivo, no "1/6 del mes":
    objetivo(M) = base_computable(M) × factor_régimen × meses_completos(inicio_semestre..M) / 6
    provisión(M) = objetivo(M) − (lo ya provisionado en meses anteriores del semestre)
Así cada mes se auto-corrige (aumentos de sueldo, ingresos, ceses) y, si se omite un mes, el
siguiente lo recupera solo. La gratificación exige MES CALENDARIO COMPLETO (Ley 27735), igual
que el cálculo real que se paga.

Este módulo NO recalcula planillas: lee el snapshot guardado (PlanillaMensual.auditoria_json),
por lo que los meses ya cerrados no se alteran.
"""
import calendar
import datetime
import io
import json

import pandas as pd

from infrastructure.database.models import (
    PlanillaMensual, Trabajador, Empresa, Concepto, ConfiguracionContable, ProvisionGratificacion,
)
from core.domain.payroll_engine import obtener_factores_regimen, determinar_regimen_trabajador
from core.use_cases.calculo_beneficios_sociales import (
    SEMESTRES_GRATI, _meses_completos, factor_grati_aplicable, tasa_bono_extraordinario,
)
from core.use_cases.generador_asiento_contable import (
    AsientoContableError, _fila, COLUMNAS_SISCONT, MESES_ES,
)
from core.use_cases.valorizacion_beneficios import valorizar_gratificacion_al
from core.use_cases.calculo_liquidacion_cese import rmv_vigente
from core.domain.exceptions import ReglaNegocioError


def rmv_al(db, empresa_id: int, fecha: datetime.date, trabajador) -> float:
    """RMV vigente a la fecha, solo si el trabajador tiene asignación familiar (10 % de la RMV);
    si no, no hace falta y no se exige tener Parámetros Legales cargados."""
    if not getattr(trabajador, 'asig_fam', False):
        return 0.0
    try:
        return rmv_vigente(db, empresa_id, fecha)
    except ReglaNegocioError as e:
        raise AsientoContableError(str(e))

# Primer mes que se provisiona (corte acordado: julio 2026). Mes anterior = sin provisión.
INICIO_PROVISION = (2026, 7)

# Cuentas (ConfiguracionContable): las mismas que ya usa la liquidación por cese para la
# gratificación trunca — el bono extraordinario comparte cuenta con la gratificación.
CUENTA_GASTO = 'cuenta_gratificacion_gasto'
CUENTA_PASIVO = 'cuenta_gratificacion_por_pagar'

# Nombres con que el motor de planilla guarda lo pagado en julio/diciembre (auditoria.ingresos)
CLAVE_GRATI_PAGADA = "Gratificación"
CLAVE_BONO_PAGADO = "Bono Ext. 9%"

# Conceptos que nunca son "remuneración computable regular" para la base de la provisión
_NO_COMPUTABLES = {CLAVE_GRATI_PAGADA, CLAVE_BONO_PAGADO, "Asignación Familiar"}

VERSION_PROVISION = "2026-11-25-r1"


# ── Helpers de periodo / semestre ────────────────────────────────────────────────

def _anio_mes(periodo_key: str) -> tuple:
    return int(periodo_key[3:]), int(periodo_key[:2])


def semestre_de_mes(mes: int) -> str:
    """Semestre de gratificación al que pertenece un mes (ENE-JUN / JUL-DIC)."""
    return 'ENE-JUN' if mes <= 6 else 'JUL-DIC'


def semestre_pagado_en(mes_pago: int):
    """Semestre que se paga en ese mes: julio paga ENE-JUN, diciembre paga JUL-DIC."""
    return {7: 'ENE-JUN', 12: 'JUL-DIC'}.get(mes_pago)


def etiqueta_semestre(semestre: str, anio: int) -> str:
    return f"{semestre}-{anio}"


def motivo_no_provisionable(periodo_key: str):
    """None si el periodo se puede provisionar; si no, el motivo (listo para mostrar)."""
    if _anio_mes(periodo_key) < INICIO_PROVISION:
        return "La provisión de gratificación arranca en julio 2026 (corte acordado); este periodo es anterior."
    if _anio_mes(periodo_key)[1] == 12:
        return ("En diciembre se paga la gratificación del semestre: el asiento de planilla ya reconoce "
                "como gasto lo que falte por provisionar, así que diciembre no se provisiona aparte.")
    return None


def es_provisionable(periodo_key: str) -> bool:
    """True si el periodo es igual o posterior al corte (julio 2026) y no es diciembre."""
    return motivo_no_provisionable(periodo_key) is None


def semestre_desde_ref(ref, fecha_cese) -> tuple:
    """(semestre, año) desde `periodo_grati_ref` de la liquidación ("JUL-DIC 2026");
    si no se puede leer, se deduce de la fecha de cese."""
    try:
        sem, anio = str(ref).strip().split()
        if sem in SEMESTRES_GRATI:
            return sem, int(anio)
    except (ValueError, AttributeError):
        pass
    return semestre_de_mes(fecha_cese.month), fecha_cese.year


# ── Libro de provisiones (lectura) ───────────────────────────────────────────────

def provisiones_acumuladas(db, empresa_id: int, semestre: str, anio: int, antes_de_mes: int = None) -> dict:
    """{trabajador_id: (grati, bono)} acumulado en el libro para ese semestre.
    `antes_de_mes`: si se indica, solo cuenta meses estrictamente anteriores."""
    filas = db.query(ProvisionGratificacion).filter_by(
        empresa_id=empresa_id, semestre=etiqueta_semestre(semestre, anio),
    ).all()
    acum = {}
    for f in filas:
        if antes_de_mes is not None and not int(f.periodo_key[:2]) < antes_de_mes:
            continue
        g, b = acum.get(f.trabajador_id, (0.0, 0.0))
        acum[f.trabajador_id] = (g + float(f.monto_grati or 0), b + float(f.monto_bono or 0))
    return {k: (round(g, 2), round(b, 2)) for k, (g, b) in acum.items()}


def provisiones_por_dni(db, empresa_id: int, semestre: str, anio: int) -> dict:
    """{num_doc: (grati, bono)} acumulado del semestre — para el asiento de planilla,
    que identifica a los trabajadores por documento."""
    por_id = provisiones_acumuladas(db, empresa_id, semestre, anio)
    if not por_id:
        return {}
    docs = {
        t.id: str(t.num_doc)
        for t in db.query(Trabajador).filter(Trabajador.id.in_(list(por_id))).all()
    }
    return {docs[i]: v for i, v in por_id.items() if i in docs}


def provision_de_trabajador(db, empresa_id: int, trabajador_id: int, semestre: str, anio: int) -> tuple:
    """(grati, bono) ya provisionado de un trabajador en el semestre — para la liquidación."""
    return provisiones_acumuladas(db, empresa_id, semestre, anio).get(trabajador_id, (0.0, 0.0))


def resumen_libro(db, empresa_id: int, anio: int) -> list:
    """[(periodo_key, n_trabajadores, total_grati, total_bono, fecha_generacion)] del año."""
    filas = db.query(ProvisionGratificacion).filter(
        ProvisionGratificacion.empresa_id == empresa_id,
        ProvisionGratificacion.periodo_key.like(f"%-{anio}"),
    ).all()
    por_periodo = {}
    for f in filas:
        n, g, b, fch = por_periodo.get(f.periodo_key, (0, 0.0, 0.0, None))
        por_periodo[f.periodo_key] = (n + 1, g + float(f.monto_grati or 0), b + float(f.monto_bono or 0),
                                      max(filter(None, [fch, f.fecha_generacion]), default=None))
    return sorted(
        [(p, n, round(g, 2), round(b, 2), fch) for p, (n, g, b, fch) in por_periodo.items()],
        key=lambda x: _anio_mes(x[0]),
    )


# ── Cálculo de la provisión del mes ──────────────────────────────────────────────

def _planilla_cerrada(db, empresa_id: int, periodo_key: str):
    p = db.query(PlanillaMensual).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first()
    if not p or p.estado != 'CERRADA':
        raise AsientoContableError(
            f"La planilla del periodo {periodo_key} no está cerrada todavía — la provisión se "
            f"calcula sobre la planilla cerrada."
        )
    return p


def calcular_provision_mes(db, empresa_id: int, periodo_key: str) -> list:
    """
    Provisión pendiente de contabilizar para el mes, por trabajador de planilla:
    [{dni, nombre, trabajador_id, base_computable, meses_computados, factor,
      objetivo_grati, objetivo_bono, ya_provisionado, delta_grati, delta_bono, delta_total}]
    No escribe nada.
    """
    motivo = motivo_no_provisionable(periodo_key)
    if motivo:
        raise AsientoContableError(motivo)
    planilla = _planilla_cerrada(db, empresa_id, periodo_key)
    auditoria = json.loads(planilla.auditoria_json or '{}')

    anio, mes = _anio_mes(periodo_key)
    sem = semestre_de_mes(mes)
    sem_ini = datetime.date(anio, SEMESTRES_GRATI[sem]['meses'][0], 1)
    fin_mes = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1])

    empresa = db.query(Empresa).filter_by(id=empresa_id).first()
    regimen_empresa = (empresa.regimen_laboral if empresa else None) or "Régimen General"
    fecha_acogimiento = getattr(empresa, 'fecha_acogimiento', None)
    factor_voluntario = getattr(empresa, 'factor_proyeccion_grati', None)

    previo = provisiones_acumuladas(db, empresa_id, sem, anio, antes_de_mes=mes)

    filas = []
    for dni, info in auditoria.items():
        t = db.query(Trabajador).filter_by(empresa_id=empresa_id, num_doc=str(dni)).first()
        if not t or (t.tipo_contrato or 'PLANILLA') == 'LOCADOR':
            continue

        # Gratificación AL CORTE con el MISMO motor que la liquidación por cese (cese simulado al
        # último día del mes): fija vigente al corte + asignación familiar con la RMV del mes +
        # variables regulares (≥ 3 meses del semestre, promediadas). Nunca más de lo que se
        # calcularía liquidando ese día. Sueldo = el de la planilla de ese mes (snapshot).
        sueldo = float((info or {}).get('sueldo_base_nominal') or 0) or float(t.sueldo_base or 0)
        res = valorizar_gratificacion_al(
            db, empresa_id, t, fin_mes, rmv_al(db, empresa_id, fin_mes, t), regimen_empresa,
            fecha_acogimiento=fecha_acogimiento, factor_override=factor_voluntario, sueldo=sueldo,
        )
        base, meses, factor = res['base_computable'], res['meses_computados'], res['factor_grati']
        objetivo_grati, objetivo_bono = res['monto_grati'], res['bono_9pct']
        prev_g, prev_b = previo.get(t.id, (0.0, 0.0))
        delta_g = round(objetivo_grati - prev_g, 2)
        delta_b = round(objetivo_bono - prev_b, 2)

        filas.append({
            "dni": str(dni), "nombre": (info or {}).get('nombres') or t.nombres, "trabajador_id": t.id,
            "base_computable": round(base, 2), "meses_computados": meses, "factor": factor,
            "objetivo_grati": objetivo_grati, "objetivo_bono": objetivo_bono,
            "ya_provisionado": round(prev_g + prev_b, 2),
            "delta_grati": delta_g, "delta_bono": delta_b, "delta_total": round(delta_g + delta_b, 2),
        })
    return filas


# ── Asiento de provisión (Excel SISCONT) + registro en el libro ──────────────────

def generar_asiento_provision(db, empresa_id: int, periodo_key: str, generado_por: str = None) -> io.BytesIO:
    """
    Genera el voucher PG{mm}-{año} del mes (gasto al débito / gratificaciones por pagar al
    crédito, por trabajador) Y REGISTRA la provisión en el libro. Regenerar un mes lo
    reemplaza, pero solo si no hay meses posteriores del mismo semestre ya registrados.
    """
    anio, mes = _anio_mes(periodo_key)
    sem = semestre_de_mes(mes)

    # Orden: no se puede regenerar un mes si ya hay uno posterior en el semestre (los
    # deltas posteriores dependen de este).
    posteriores = [
        f.periodo_key for f in db.query(ProvisionGratificacion).filter_by(
            empresa_id=empresa_id, semestre=etiqueta_semestre(sem, anio)).all()
        if int(f.periodo_key[:2]) > mes
    ]
    if posteriores:
        raise AsientoContableError(
            f"Ya hay provisiones registradas de meses posteriores ({', '.join(sorted(set(posteriores)))}). "
            f"No se puede regenerar {periodo_key} sin invalidarlas."
        )

    filas_calc = [f for f in calcular_provision_mes(db, empresa_id, periodo_key) if abs(f["delta_total"]) > 0.004]
    if not filas_calc:
        raise AsientoContableError(
            f"No hay provisión de gratificación pendiente en {periodo_key} (nada que contabilizar)."
        )

    cfg = db.query(ConfiguracionContable).filter_by(empresa_id=empresa_id).first()
    cuenta_gasto = ((getattr(cfg, CUENTA_GASTO, None) if cfg else None) or "").strip()
    cuenta_pasivo = ((getattr(cfg, CUENTA_PASIVO, None) if cfg else None) or "").strip()
    faltantes = []
    if not cuenta_gasto:
        faltantes.append("Gratificación — Gasto (Configuración Contable)")
    if not cuenta_pasivo:
        faltantes.append("Gratificación Por Pagar (Configuración Contable)")
    if faltantes:
        raise AsientoContableError(
            "Faltan cuentas contables por configurar antes de generar la provisión.",
            cuentas_faltantes=faltantes,
        )

    fecha_asiento = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1]).strftime('%d/%m/%Y')
    num_doc = f"PG{mes:02d}-{anio}"
    glosa = f"PROVISION GRATIFICACION {MESES_ES.get(mes, '')} {anio}"

    filas = []
    for f in filas_calc:
        monto = f["delta_total"]
        if monto > 0:
            filas.append(_fila(11, 1, fecha_asiento, cuenta_gasto, monto, 0.0, num_doc, glosa,
                               cod_prov_clie=f["dni"], ruc=f["dni"], r_social=f["nombre"]))
            filas.append(_fila(11, 1, fecha_asiento, cuenta_pasivo, 0.0, monto, num_doc, glosa,
                               cod_prov_clie=f["dni"], ruc=f["dni"], r_social=f["nombre"]))
        else:   # reverso (la provisión acumulada excedía el objetivo)
            filas.append(_fila(11, 1, fecha_asiento, cuenta_pasivo, -monto, 0.0, num_doc, glosa,
                               cod_prov_clie=f["dni"], ruc=f["dni"], r_social=f["nombre"]))
            filas.append(_fila(11, 1, fecha_asiento, cuenta_gasto, 0.0, -monto, num_doc, glosa,
                               cod_prov_clie=f["dni"], ruc=f["dni"], r_social=f["nombre"]))

    total_debe = round(sum(x["Monto Debe"] for x in filas), 2)
    total_haber = round(sum(x["Monto Haber"] for x in filas), 2)
    if total_debe != total_haber:
        raise AsientoContableError(
            f"El asiento de provisión no cuadra (Debe: S/ {total_debe:,.2f} vs Haber: S/ {total_haber:,.2f}). "
            f"No se generó el archivo — este es un error interno, no de configuración."
        )

    # ── Registrar en el libro (reemplaza el mes si ya existía) ──
    try:
        db.query(ProvisionGratificacion).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).delete()
        for f in filas_calc:
            db.add(ProvisionGratificacion(
                empresa_id=empresa_id, trabajador_id=f["trabajador_id"], periodo_key=periodo_key,
                semestre=etiqueta_semestre(sem, anio),
                monto_grati=f["delta_grati"], monto_bono=f["delta_bono"],
                base_computable=f["base_computable"], meses_computados=f["meses_computados"],
                generado_por=generado_por,
            ))
        db.commit()
    except Exception:
        db.rollback()
        raise

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        pd.DataFrame(filas, columns=COLUMNAS_SISCONT).to_excel(writer, index=False, sheet_name='Asiento')
    buffer.seek(0)
    return buffer
