"""
Provisión mensual de CTS.

Mismo criterio contable que gratificación y vacaciones (corte en julio 2026): el gasto se reconoce
mes a mes y el pasivo "CTS por pagar" lo cancelan el depósito semestral (mayo/noviembre) y la
liquidación por cese (CTS trunca).

    objetivo(M)  = CTS AL CORTE: lo que se pagaría si el trabajador cesara el último día de M
                   (mismo motor que la liquidación, ver valorizacion_beneficios.py)
    provisión(M) = objetivo(M) − (lo ya provisionado del periodo CTS en meses anteriores)

Por construcción la provisión nunca excede lo que se calcularía liquidando ese día, y la
remuneración variable sigue la regla legal del motor (solo entra lo percibido en ≥ 3 meses del
semestre, promediado; no se proyectan meses futuros). Julio 2026 arranca con todo lo devengado del
periodo MAY-OCT (mayo–julio): el "ajuste en julio".

Periodos: NOV-ABR se deposita en mayo; MAY-OCT en noviembre (D.S. 001-97-TR). En el mes de depósito
se cierra el periodo anterior con un AJUSTE contra el DepositoCTS real y, en el mismo voucher, empieza
la provisión del periodo nuevo.
"""
import calendar
import datetime
import io
import json
import re

import pandas as pd

from infrastructure.database.models import (
    Trabajador, Empresa, ConfiguracionContable, ProvisionCTS, DepositoCTS,
)
from core.use_cases.generador_asiento_contable import (
    AsientoContableError, _fila, COLUMNAS_SISCONT, MESES_ES, aviso_cuentas_repetidas,
)
from core.use_cases.calculo_liquidacion_cese import _periodo_cts_de_fecha
from core.use_cases.calculo_beneficios_sociales import rango_cts, meses_con_servicio
from core.use_cases.valorizacion_beneficios import valorizar_cts_al
from core.use_cases.provision_gratificacion import INICIO_PROVISION, _planilla_cerrada, rmv_al

# Cuentas (ConfiguracionContable): las mismas que ya usa la liquidación por cese para la CTS trunca
CUENTA_GASTO = 'cuenta_cts_gasto'
CUENTA_PASIVO = 'cuenta_cts_por_pagar'

VERSION_PROVISION_CTS = "2026-11-25-r3"


# ── Helpers de periodo ───────────────────────────────────────────────────────────

def _anio_mes(periodo_key: str) -> tuple:
    return int(periodo_key[3:]), int(periodo_key[:2])


def etiqueta_periodo(periodo: str, anio_dep: int) -> str:
    return f"{periodo}-{anio_dep}"


def periodo_de_mes(anio: int, mes: int) -> str:
    """Etiqueta del periodo CTS al que pertenece el mes (ej. 07-2026 -> 'MAY-OCT-2026')."""
    periodo, anio_dep = _periodo_cts_de_fecha(datetime.date(anio, mes, 1))
    return etiqueta_periodo(periodo, anio_dep)


def periodo_que_cierra(anio: int, mes: int):
    """Etiqueta del periodo que se deposita en ese mes (mayo -> NOV-ABR, noviembre -> MAY-OCT), o None."""
    return {5: f"NOV-ABR-{anio}", 11: f"MAY-OCT-{anio}"}.get(mes)


def periodo_desde_ref(ref, fecha_cese: datetime.date) -> str:
    """Etiqueta desde `periodo_cts_ref` de la liquidación ("MAY-OCT (dep. 2026)"); si no se puede
    leer, se deduce de la fecha de cese."""
    m = re.match(r"\s*(NOV-ABR|MAY-OCT)\s*\(dep\.\s*(\d{4})\)", str(ref or ""))
    if m:
        return etiqueta_periodo(m.group(1), int(m.group(2)))
    periodo, anio_dep = _periodo_cts_de_fecha(fecha_cese)
    return etiqueta_periodo(periodo, anio_dep)


def motivo_no_provisionable(periodo_key: str):
    if _anio_mes(periodo_key) < INICIO_PROVISION:
        return "La provisión de CTS arranca en julio 2026 (corte acordado); este periodo es anterior."
    return None


def es_provisionable(periodo_key: str) -> bool:
    return motivo_no_provisionable(periodo_key) is None


# ── Libro (lectura) ──────────────────────────────────────────────────────────────

def provisiones_acumuladas(db, empresa_id: int, etiqueta: str, antes_de: tuple = None) -> dict:
    """{trabajador_id: monto} acumulado (provisiones + ajustes) de un periodo CTS.
    `antes_de=(año, mes)`: solo lo contabilizado en meses estrictamente anteriores."""
    acum = {}
    for f in db.query(ProvisionCTS).filter_by(empresa_id=empresa_id, periodo_cts=etiqueta).all():
        if antes_de is not None and not _anio_mes(f.periodo_key) < antes_de:
            continue
        acum[f.trabajador_id] = acum.get(f.trabajador_id, 0.0) + float(f.monto or 0.0)
    return {k: round(v, 2) for k, v in acum.items()}


def provision_de_trabajador(db, empresa_id: int, trabajador_id: int, etiqueta: str) -> float:
    """Lo ya provisionado de un trabajador en el periodo CTS — para la liquidación por cese."""
    return provisiones_acumuladas(db, empresa_id, etiqueta).get(trabajador_id, 0.0)


def resumen_libro(db, empresa_id: int, anio: int) -> list:
    """[(periodo_key, n_trabajadores, total_provision, total_ajuste, fecha)] de los meses del año."""
    por_mes = {}
    for f in db.query(ProvisionCTS).filter_by(empresa_id=empresa_id).all():
        if not f.periodo_key.endswith(f"-{anio}"):
            continue
        trabs, prov, aj, fch = por_mes.get(f.periodo_key, (set(), 0.0, 0.0, None))
        trabs.add(f.trabajador_id)
        if f.tipo == "AJUSTE":
            aj += float(f.monto or 0)
        else:
            prov += float(f.monto or 0)
        por_mes[f.periodo_key] = (trabs, prov, aj, max(filter(None, [fch, f.fecha_generacion]), default=None))
    return sorted(
        [(p, len(t), round(a, 2), round(b, 2), fch) for p, (t, a, b, fch) in por_mes.items()],
        key=lambda x: _anio_mes(x[0]),
    )


# ── Regularización ÚNICA del periodo NOV-ABR (solo julio 2026) ───────────────────

PERIODO_REG = "NOV-ABR-2026"                 # periodo CTS que se regulariza (depósito de mayo 2026)
INICIO_REG = datetime.date(2026, 1, 1)       # solo enero–abril 2026: nov–dic 2025 ya están en la contabilidad
FIN_REG = datetime.date(2026, 4, 30)


def _regularizacion_nov_abr(db, empresa_id, t, sueldo, regimen_empresa, fecha_acogimiento, factor_voluntario):
    """
    Ajuste puntual de julio 2026: la CTS de NOV-ABR (depósito de mayo 2026) sigue SIN PAGAR y nunca se
    provisionó enero–abril 2026. Devuelve (monto, fuente): la parte de enero–abril de lo que se debe.

    Lo que se debe: el depósito de mayo 2026 ya calculado y registrado (DepositoCTS) si existe; si no,
    la CTS al 30/04/2026 con el mismo motor de la liquidación. La parte de enero–abril es proporcional
    a los meses con servicio (enero–abril ÷ noviembre–abril); noviembre–diciembre 2025 no se tocan.
    """
    ini_per, fin_per = rango_cts('NOV-ABR', 2026)
    m_total = meses_con_servicio(t.fecha_ingreso, getattr(t, 'fecha_cese', None), ini_per, fin_per)
    m_reg = meses_con_servicio(t.fecha_ingreso, getattr(t, 'fecha_cese', None), INICIO_REG, FIN_REG)
    if m_total <= 0 or m_reg <= 0:
        return 0.0, None
    dep = db.query(DepositoCTS).filter_by(
        empresa_id=empresa_id, trabajador_id=t.id, periodo_key_deposito="05-2026").first()
    if dep and float(dep.monto or 0) > 0:
        total, fuente = float(dep.monto), "depósito registrado (05-2026)"
    else:
        res = valorizar_cts_al(
            db, empresa_id, t, FIN_REG, rmv_al(db, empresa_id, FIN_REG, t), regimen_empresa,
            fecha_acogimiento=fecha_acogimiento, factor_override=factor_voluntario, sueldo=sueldo,
        )
        total, fuente = float(res['monto_cts']), "CTS al 30/04/2026 (motor)"
    return round(total * min(1.0, m_reg / m_total), 2), fuente


# ── Cálculo de la provisión del mes ──────────────────────────────────────────────

def reg_nov_abr_registrada(db, empresa_id: int) -> bool:
    """True si la regularización de NOV-ABR (ene–abr 2026) ya quedó registrada en el libro."""
    return db.query(ProvisionCTS).filter_by(empresa_id=empresa_id, periodo_cts=PERIODO_REG).first() is not None


def calcular_provision_mes(db, empresa_id: int, periodo_key: str, incluir_reg_nov_abr: bool = False) -> list:
    """
    Por trabajador de planilla: [{dni, nombre, trabajador_id, periodo_cts, base_cts, meses,
    objetivo, ya_provisionado, delta_provision, periodo_cierre, deposito, provisionado_cierre,
    delta_ajuste, reg_periodo, reg_monto, reg_fuente, delta_total}]. No escribe nada.

    `incluir_reg_nov_abr`: OPCIÓN del usuario (solo tiene efecto en julio 2026): incluir la CTS de
    enero–abril 2026 del periodo NOV-ABR, si la empresa no la provisionó.
    """
    motivo = motivo_no_provisionable(periodo_key)
    if motivo:
        raise AsientoContableError(motivo)
    planilla = _planilla_cerrada(db, empresa_id, periodo_key)
    auditoria = json.loads(planilla.auditoria_json or '{}')

    anio, mes = _anio_mes(periodo_key)
    fin_mes = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1])
    etiqueta = periodo_de_mes(anio, mes)
    cierre = periodo_que_cierra(anio, mes)

    empresa = db.query(Empresa).filter_by(id=empresa_id).first()
    regimen_empresa = (empresa.regimen_laboral if empresa else None) or "Régimen General"
    fecha_acogimiento = getattr(empresa, 'fecha_acogimiento', None)
    factor_voluntario = getattr(empresa, 'factor_proyeccion_grati', None)

    previo = provisiones_acumuladas(db, empresa_id, etiqueta, antes_de=(anio, mes))
    # El ajuste solo aplica a periodos que realmente se provisionaron (los anteriores al corte, no)
    cierre_en_uso = bool(cierre) and db.query(ProvisionCTS).filter_by(empresa_id=empresa_id, periodo_cts=cierre).first()
    provisionado_cierre = provisiones_acumuladas(db, empresa_id, cierre) if cierre_en_uso else {}
    depositos = {}
    if cierre_en_uso:
        for d in db.query(DepositoCTS).filter_by(empresa_id=empresa_id, periodo_key_deposito=periodo_key).all():
            depositos[d.trabajador_id] = float(d.monto or 0.0)

    filas = []
    for dni, info in auditoria.items():
        t = db.query(Trabajador).filter_by(empresa_id=empresa_id, num_doc=str(dni)).first()
        if not t or (t.tipo_contrato or 'PLANILLA') == 'LOCADOR' or not t.fecha_ingreso:
            continue
        sueldo = float((info or {}).get('sueldo_base_nominal') or 0) or float(t.sueldo_base or 0)
        res = valorizar_cts_al(
            db, empresa_id, t, fin_mes, rmv_al(db, empresa_id, fin_mes, t), regimen_empresa,
            fecha_acogimiento=fecha_acogimiento, factor_override=factor_voluntario, sueldo=sueldo,
        )
        objetivo = res['monto_cts']
        previo_t = previo.get(t.id, 0.0)

        delta_aj, dep, prov_c = 0.0, None, 0.0
        if cierre_en_uso and t.id in depositos:
            dep, prov_c = depositos[t.id], provisionado_cierre.get(t.id, 0.0)
            delta_aj = round(dep - prov_c, 2)

        # Ajuste puntual: SOLO en julio 2026 (nunca se repite)
        reg, reg_fuente = (0.0, None)
        if incluir_reg_nov_abr and (anio, mes) == INICIO_PROVISION:
            reg, reg_fuente = _regularizacion_nov_abr(
                db, empresa_id, t, sueldo, regimen_empresa, fecha_acogimiento, factor_voluntario)

        filas.append({
            "dni": str(dni), "nombre": (info or {}).get('nombres') or t.nombres, "trabajador_id": t.id,
            "periodo_cts": etiqueta, "base_cts": res['base_cts'], "meses": res['meses_computados'],
            "objetivo": objetivo, "ya_provisionado": previo_t,
            "delta_provision": round(objetivo - previo_t, 2),
            "periodo_cierre": cierre if delta_aj or dep is not None else None,
            "deposito": dep, "provisionado_cierre": prov_c, "delta_ajuste": delta_aj,
            "reg_periodo": PERIODO_REG if reg > 0 else None, "reg_monto": reg, "reg_fuente": reg_fuente,
            "delta_total": round((objetivo - previo_t) + delta_aj + reg, 2),
        })
    return filas


# ── Asiento de provisión (Excel SISCONT) + registro en el libro ──────────────────

def generar_asiento_provision(db, empresa_id: int, periodo_key: str, generado_por: str = None,
                              incluir_reg_nov_abr: bool = False) -> io.BytesIO:
    """
    Genera el voucher PC{mm}-{año} (gasto CTS al débito / CTS por pagar al crédito, por trabajador)
    con la provisión del mes y, en mayo/noviembre, el ajuste contra el depósito real; y REGISTRA ambos
    en el libro. No se puede regenerar un mes si ya hay uno posterior registrado.
    """
    anio, mes = _anio_mes(periodo_key)
    posteriores = sorted({
        f.periodo_key for f in db.query(ProvisionCTS).filter_by(empresa_id=empresa_id).all()
        if _anio_mes(f.periodo_key) > (anio, mes)
    })
    if posteriores:
        raise AsientoContableError(
            f"Ya hay provisiones de CTS registradas de meses posteriores ({', '.join(posteriores)}). "
            f"No se puede regenerar {periodo_key} sin invalidarlas."
        )

    filas_calc = calcular_provision_mes(db, empresa_id, periodo_key, incluir_reg_nov_abr=incluir_reg_nov_abr)
    movimientos = [f for f in filas_calc
                   if abs(f["delta_provision"]) > 0.004 or abs(f["delta_ajuste"]) > 0.004 or f["reg_monto"] > 0.004]
    if not movimientos:
        raise AsientoContableError(f"No hay provisión de CTS pendiente en {periodo_key} (nada que contabilizar).")

    cfg = db.query(ConfiguracionContable).filter_by(empresa_id=empresa_id).first()
    cuenta_gasto = ((getattr(cfg, CUENTA_GASTO, None) if cfg else None) or "").strip()
    cuenta_pasivo = ((getattr(cfg, CUENTA_PASIVO, None) if cfg else None) or "").strip()
    faltantes = []
    if not cuenta_gasto:
        faltantes.append("CTS — Gasto (Configuración Contable)")
    if not cuenta_pasivo:
        faltantes.append("CTS — Por Pagar (crédito) (Configuración Contable)")
    _rep = aviso_cuentas_repetidas("CTS", cuenta_gasto, cuenta_pasivo)
    if _rep:
        faltantes.append(_rep)
    if faltantes:
        raise AsientoContableError(
            "Faltan cuentas contables por configurar antes de generar la provisión.",
            cuentas_faltantes=faltantes,
        )

    fecha_asiento = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1]).strftime('%d/%m/%Y')
    from core.use_cases import numeracion_vouchers as _nvd
    glosa_prov = f"PROVISION CTS {MESES_ES.get(mes, '')} {anio} ({periodo_de_mes(anio, mes)})"
    if (anio, mes) == INICIO_PROVISION:
        glosa_prov += " - REGULARIZACION MAY-JUL"
    glosa_aj = f"AJUSTE CTS POR DEPOSITO {MESES_ES.get(mes, '')} {anio}"
    glosa_reg = f"PROVISION CTS {MESES_ES.get(mes, '')} {anio} ({PERIODO_REG}) - REGULARIZACION ENE-ABR 2026"

    def _lineas(f, monto, glosa, periodo_cts):
        num_doc = _nvd.doc_cts(periodo_cts)      # todo el periodo CTS comparte documento (provisión y ajuste)
        kw = dict(cod_prov_clie=f["dni"], ruc=f["dni"], r_social=f["nombre"])
        if monto > 0:
            return [_fila(11, 1, fecha_asiento, cuenta_gasto, monto, 0.0, num_doc, glosa, **kw),
                    _fila(11, 1, fecha_asiento, cuenta_pasivo, 0.0, monto, num_doc, glosa, **kw)]
        return [_fila(11, 1, fecha_asiento, cuenta_pasivo, -monto, 0.0, num_doc, glosa, **kw),     # reverso
                _fila(11, 1, fecha_asiento, cuenta_gasto, 0.0, -monto, num_doc, glosa, **kw)]

    filas = []
    for f in movimientos:
        if abs(f["delta_provision"]) > 0.004:
            filas += _lineas(f, f["delta_provision"], glosa_prov, f["periodo_cts"])
        if abs(f["delta_ajuste"]) > 0.004:
            filas += _lineas(f, f["delta_ajuste"], glosa_aj, f["periodo_cierre"])
        if f["reg_monto"] > 0.004:
            filas += _lineas(f, f["reg_monto"], glosa_reg, f["reg_periodo"])

    if round(sum(x["Monto Debe"] for x in filas) - sum(x["Monto Haber"] for x in filas), 2) != 0:
        raise AsientoContableError(
            "El asiento de provisión de CTS no cuadra. No se generó el archivo — "
            "este es un error interno, no de configuración."
        )

    # ── Registrar en el libro (reemplaza el mes si ya existía) ──
    try:
        db.query(ProvisionCTS).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).delete()
        for f in filas_calc:
            if abs(f["delta_provision"]) > 0.004 or f["objetivo"] > 0:
                db.add(ProvisionCTS(
                    empresa_id=empresa_id, trabajador_id=f["trabajador_id"], periodo_key=periodo_key,
                    periodo_cts=f["periodo_cts"], tipo="PROVISION", monto=f["delta_provision"],
                    base_cts=f["base_cts"], meses_computados=f["meses"], generado_por=generado_por,
                ))
            if abs(f["delta_ajuste"]) > 0.004:
                db.add(ProvisionCTS(
                    empresa_id=empresa_id, trabajador_id=f["trabajador_id"], periodo_key=periodo_key,
                    periodo_cts=f["periodo_cierre"], tipo="AJUSTE", monto=f["delta_ajuste"],
                    generado_por=generado_por,
                ))
            if f["reg_monto"] > 0.004:
                db.add(ProvisionCTS(
                    empresa_id=empresa_id, trabajador_id=f["trabajador_id"], periodo_key=periodo_key,
                    periodo_cts=f["reg_periodo"], tipo="PROVISION", monto=f["reg_monto"],
                    generado_por=generado_por,
                ))
        db.commit()
    except Exception:
        db.rollback()
        raise

    from core.use_cases import numeracion_vouchers as _nv
    _nv.numerar_filas(db, empresa_id, periodo_key, _nv.CLAVE_PROV_CTS, filas)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        pd.DataFrame(filas, columns=COLUMNAS_SISCONT).to_excel(writer, index=False, sheet_name='Asiento')
    buffer.seek(0)
    return buffer
