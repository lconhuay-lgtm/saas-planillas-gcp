"""
Generador del Asiento Contable de Planilla — Excel de importación a SISCONT.

Alcance de esta primera fase (confirmado con el usuario):
  - Solo periodos que NO sean julio (07) ni diciembre (12) — la gratificación de esos
    meses queda pendiente de un módulo de provisión mensual en una fase futura.
  - Solo trabajadores de Planilla (5ta categoría) — los locadores (4ta) no entran aquí,
    ellos emiten recibo por honorarios y se registran directo en el sistema contable.
  - Un solo voucher (Num.Voucher=1) por planilla del mes — sin asiento de pago, sin
    CTS/vacaciones/gratificación, sin liquidación de cesados (fases futuras).
  - Granularidad: el gasto y el neto a pagar van por trabajador; los aportes/tributos
    (ONP, AFP, EsSalud, 5ta) van totalizados por empresa.

Este módulo NO recalcula ningún sueldo — solo lee lo que el motor de planilla ya
calculó y guardó (PlanillaMensual.resultado_json / auditoria_json) y lo traduce a
cuentas contables.
"""
import io
import json
import calendar
from datetime import date

import pandas as pd

from infrastructure.database.models import PlanillaMensual, Concepto, ConfiguracionContable

# Marcador de versión — súbelo cada vez que se corrija algo en este archivo, para poder
# confirmar en pantalla (pestaña Asiento Contable) si el código desplegado es el último.
VERSION_GENERADOR = "2026-08-07-r4"

MESES_ES = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL", 5: "MAYO", 6: "JUNIO",
    7: "JULIO", 8: "AGOSTO", 9: "SEPTIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE",
}

# Julio y diciembre quedan fuera de esta fase (gratificación pendiente de provisión mensual)
_MESES_SIN_ASIENTO = (7, 12)

# Conceptos de gratificación — excluidos por diseño (nunca deberían tener monto fuera
# de jul/dic, pero se excluyen explícitamente como seguro adicional)
_CONCEPTOS_GRATI_EXCLUIDOS = {"Gratificación", "Bono Ext. 9%"}

# Claves de "desglose_descuentos" que NO son conceptos configurables ni préstamos —
# tienen su propio tratamiento contable especial (ver más abajo), no deben entrar al
# flujo genérico de "descuento dinámico -> cuenta de Préstamos".
_CLAVE_AJUSTE_AFP = "Ajuste AFP (Audit)"
_CLAVE_AJUSTE_OTROS = "Ajuste Varios (Audit)"
# "Retención 5ta Cat." TAMBIÉN aparece en desglose_descuentos (calculo_mensual.py la
# agrega ahí para mostrarla en la boleta) — pero ya se contabiliza aparte con el valor
# de la columna "Ret. 5ta Cat." de la sábana (variable total_5ta). Si no se excluye acá,
# se contaba DOS VECES: una vez bien (cuenta de Retención 5ta) y otra de más (crédito
# extra a Préstamos al Personal) — esto inflaba el Haber por encima del Debe.
_CLAVE_RET_5TA = "Retención 5ta Cat."
_DESCUENTOS_ESPECIALES = ("Faltas", "Tardanzas", _CLAVE_AJUSTE_AFP, _CLAVE_AJUSTE_OTROS, _CLAVE_RET_5TA)

_AFP_CUENTA_ATTR = {
    "AFP HABITAT": "cuenta_afp_habitat",
    "AFP INTEGRA": "cuenta_afp_integra",
    "AFP PRIMA": "cuenta_afp_prima",
    "AFP PROFUTURO": "cuenta_afp_profuturo",
}

COLUMNAS_SISCONT = [
    "Origen", "Num.Voucher", "Fecha", "Cuenta", "Monto Debe", "Monto Haber",
    "Moneda S/D", "T.Cambio", "Doc", "Num.Doc", "Fec.Doc", "Fec.Ven",
    "Cod.Prov.Clie", "C.Costo", "Presupuesto", "F.Efectivo", "Glosa",
    "Libro C/V/R", "Mto.Neto 1", "Mto.Neto 2", "Mto.Neto 3", "Mto.Neto 4",
    "Mto.Neto 5", "Mto.Neto 6", "Mto.Neto 7", "Mto.Neto 8", "Mto.Neto 9",
    "Mto.IGV", "Ref.Doc", "Ref.Num.Doc", "Ref.Fecha", "Det.Num", "Det.Fecha",
    "RUC", "R.Social", "Tipo", "Tip.Doc.Iden", "Medio de Pago",
    "Apellido 1", "Apellido 2", "Nombre", "T.Bien",
]


class AsientoContableError(Exception):
    """Error esperado (periodo no soportado, planilla no cerrada, cuentas sin
    configurar) — el mensaje ya viene listo para mostrarle al usuario."""
    def __init__(self, mensaje, cuentas_faltantes=None, detalle_diagnostico=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.cuentas_faltantes = cuentas_faltantes or []
        # Lista de dicts {"dni", "nombre", "debe", "haber", "diferencia"} — solo se
        # llena cuando el asiento no cuadra, para señalar qué trabajador(es) lo causan.
        self.detalle_diagnostico = detalle_diagnostico or []


def _fila(origen, num_voucher, fecha, cuenta, debe, haber, num_doc, glosa,
          cod_prov_clie="", ruc="", r_social=""):
    fila = {c: "" for c in COLUMNAS_SISCONT}
    fila.update({
        "Origen": origen,
        "Num.Voucher": num_voucher,
        "Fecha": fecha,
        "Cuenta": cuenta,
        "Monto Debe": round(debe, 2),
        "Monto Haber": round(haber, 2),
        "Moneda S/D": "S",
        "T.Cambio": 1.000,
        "Doc": "BS",
        "Num.Doc": num_doc,
        "Fec.Doc": fecha,
        "Fec.Ven": fecha,
        "Cod.Prov.Clie": cod_prov_clie,
        "Glosa": glosa,
        "RUC": ruc,
        "R.Social": r_social,
    })
    return fila


def generar_asiento_planilla(db, empresa_id, periodo_key):
    """
    Genera el Excel del Asiento de Planilla del periodo. Retorna un io.BytesIO listo
    para descargar (o None si `raise_errors=False` y hubo un problema — por defecto
    lanza AsientoContableError, que ya trae el mensaje listo para el usuario).
    """
    mes_num = int(periodo_key[:2])
    anio_num = int(periodo_key[3:])

    if mes_num in _MESES_SIN_ASIENTO:
        raise AsientoContableError(
            f"El periodo {periodo_key} no genera asiento automático todavía — la "
            f"gratificación de julio/diciembre está pendiente de un módulo de "
            f"provisión mensual (fase futura). Este periodo se registra manualmente."
        )

    planilla = db.query(PlanillaMensual).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first()
    if not planilla or planilla.estado != 'CERRADA':
        raise AsientoContableError(f"La planilla del periodo {periodo_key} no está cerrada todavía.")

    df_resultados = pd.read_json(io.StringIO(planilla.resultado_json), orient='records')
    auditoria_data = json.loads(planilla.auditoria_json)
    df_data = df_resultados[df_resultados['Apellidos y Nombres'] != 'TOTALES']

    if df_data.empty:
        raise AsientoContableError(f"No hay trabajadores calculados en la planilla de {periodo_key}.")

    conceptos_db = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
    cuentas_concepto = {c.nombre: (c.cuenta_contable or "").strip() for c in conceptos_db}
    cfg = db.query(ConfiguracionContable).filter_by(empresa_id=empresa_id).first()

    faltantes = set()

    def _cuenta_fija(attr, etiqueta):
        val = ((getattr(cfg, attr, None) if cfg else None) or "").strip()
        if not val:
            faltantes.add(etiqueta)
        return val

    def _cuenta_concepto(nombre_concepto):
        val = cuentas_concepto.get(nombre_concepto, "")
        if not val:
            faltantes.add(f'Concepto "{nombre_concepto}" (Maestro de Conceptos)')
        return val

    # ── Determinar qué cuentas fijas hacen falta (solo las que van a tener monto) ──
    necesita = {"he25": False, "he35": False, "dvac": False, "dmed": False, "lgoce": False}
    afp_administradoras_usadas = set()
    for _, row in df_data.iterrows():
        sist = str(row.get('Sist. Pensión', '') or '')
        if sist in _AFP_CUENTA_ATTR:
            monto_afp = sum(float(row.get(c, 0) or 0) for c in ["AFP Aporte", "AFP Seguro", "AFP Comis."])
            if monto_afp > 0:
                afp_administradoras_usadas.add(sist)

    for info in auditoria_data.values():
        ingresos = info.get('ingresos', {}) or {}
        if any(float(v or 0) > 0 for k, v in ingresos.items() if k.startswith("Horas Extras 25")):
            necesita["he25"] = True
        if any(float(v or 0) > 0 for k, v in ingresos.items() if k.startswith("Horas Extras 35")):
            necesita["he35"] = True
        if float(ingresos.get("Descanso Vacacional", 0) or 0) > 0:
            necesita["dvac"] = True
        if float(ingresos.get("Descanso Médico", 0) or 0) > 0:
            necesita["dmed"] = True
        if float(ingresos.get("Licencia con Goce", 0) or 0) > 0:
            necesita["lgoce"] = True

    if necesita["he25"]: _cuenta_fija('cuenta_horas_extra_25', "Horas Extras 25% (Configuración Contable)")
    if necesita["he35"]: _cuenta_fija('cuenta_horas_extra_35', "Horas Extras 35% (Configuración Contable)")
    if necesita["dvac"]: _cuenta_fija('cuenta_descanso_vacacional', "Descanso Vacacional (Configuración Contable)")
    if necesita["dmed"]: _cuenta_fija('cuenta_descanso_medico', "Descanso Médico (Configuración Contable)")
    if necesita["lgoce"]: _cuenta_fija('cuenta_licencia_goce', "Licencia con Goce (Configuración Contable)")

    total_essalud_check = float(df_data.get('Aporte Seg. Social', pd.Series([0.0])).astype(float).sum() or 0)
    if total_essalud_check > 0:
        _cuenta_fija('cuenta_essalud_gasto', "EsSalud - Gasto (Configuración Contable)")
        _cuenta_fija('cuenta_essalud_pasivo', "EsSalud - Por Pagar (Configuración Contable)")

    total_onp_check = float(df_data.get('ONP (13%)', pd.Series([0.0])).astype(float).sum() or 0)
    if total_onp_check > 0:
        _cuenta_fija('cuenta_onp', "ONP (Configuración Contable)")

    for admin in afp_administradoras_usadas:
        _cuenta_fija(_AFP_CUENTA_ATTR[admin], f"{admin} (Configuración Contable)")

    total_5ta_check = float(df_data.get('Ret. 5ta Cat.', pd.Series([0.0])).astype(float).sum() or 0)
    if total_5ta_check > 0:
        _cuenta_fija('cuenta_retencion_5ta', "Retención 5ta Categoría (Configuración Contable)")

    _cuenta_fija('cuenta_remuneraciones_por_pagar', "Remuneraciones por Pagar (Configuración Contable)")

    # (los descuentos dinámicos con cuenta propia se validan más abajo; esto solo cubre
    # préstamos, que no son un "Concepto" configurable — usan la cuenta fija)
    necesita_prestamos = any(
        float(v or 0) > 0
        for info in auditoria_data.values()
        for k, v in (info.get('descuentos', {}) or {}).items()
        if k not in _DESCUENTOS_ESPECIALES and k not in cuentas_concepto
    )
    if necesita_prestamos:
        _cuenta_fija('cuenta_prestamos_personal', "Préstamos al Personal (Configuración Contable)")

    # ── Validar cuentas de conceptos dinámicos (ingresos y descuentos) ──
    for info in auditoria_data.values():
        for nombre_c, monto in (info.get('ingresos', {}) or {}).items():
            if float(monto or 0) <= 0 or nombre_c in _CONCEPTOS_GRATI_EXCLUIDOS:
                continue
            if nombre_c.startswith("Sueldo Base"):
                _cuenta_concepto("SUELDO BASICO")
            elif nombre_c == "Asignación Familiar":
                _cuenta_concepto("ASIGNACION FAMILIAR")
            elif nombre_c.startswith("Horas Extras") or nombre_c in ("Descanso Vacacional", "Descanso Médico", "Licencia con Goce"):
                continue  # ya cubiertas arriba por cuentas fijas
            else:
                _cuenta_concepto(nombre_c)
        for nombre_c, monto in (info.get('descuentos', {}) or {}).items():
            if float(monto or 0) <= 0 or nombre_c in _DESCUENTOS_ESPECIALES:
                continue
            if nombre_c not in cuentas_concepto:
                continue  # es un préstamo (no es Concepto) — ya cubierto por cuenta fija arriba
            _cuenta_concepto(nombre_c)

    if faltantes:
        raise AsientoContableError(
            "Faltan cuentas contables por configurar antes de generar el asiento.",
            cuentas_faltantes=sorted(faltantes),
        )

    # ── Ya validado: armar las filas del asiento ──
    dias_mes = calendar.monthrange(anio_num, mes_num)[1]
    fecha_asiento = date(anio_num, mes_num, dias_mes)
    num_doc_asiento = f"BS{mes_num:02d}-{anio_num}"
    glosa_asiento = f"PLANILLA DE SUELDO {MESES_ES.get(mes_num, '')} {anio_num}"

    cuenta_sueldo = cuentas_concepto.get("SUELDO BASICO", "")
    cuenta_asig_fam = cuentas_concepto.get("ASIGNACION FAMILIAR", "")

    filas = []
    total_essalud = 0.0
    total_onp = 0.0
    total_5ta = 0.0
    total_afp = {k: 0.0 for k in _AFP_CUENTA_ATTR}

    # Diagnóstico: Debe/Haber acumulado POR TRABAJADOR (incluye su porción de las
    # cuentas globales, aunque en el archivo salgan como una sola línea totalizada) —
    # así, si el asiento no cuadra, se puede señalar exactamente quién causa la
    # diferencia en vez de solo el total general.
    diagnostico = {}  # dni -> {"nombre": str, "debe": float, "haber": float}

    def _diag(dni, nombre):
        if dni not in diagnostico:
            diagnostico[dni] = {"nombre": nombre, "debe": 0.0, "haber": 0.0}
        return diagnostico[dni]

    for _, row in df_data.iterrows():
        dni = str(row['DNI'])
        nombre = row['Apellidos y Nombres']
        info = auditoria_data.get(dni, {})
        ingresos = info.get('ingresos', {}) or {}
        descuentos = info.get('descuentos', {}) or {}
        sist = str(row.get('Sist. Pensión', '') or '')
        d = _diag(dni, nombre)

        # Débitos: cada concepto de ingreso con monto > 0
        for nombre_c, monto in ingresos.items():
            monto = float(monto or 0)
            if monto <= 0 or nombre_c in _CONCEPTOS_GRATI_EXCLUIDOS:
                continue
            if nombre_c.startswith("Sueldo Base"):
                cuenta = cuenta_sueldo
            elif nombre_c == "Asignación Familiar":
                cuenta = cuenta_asig_fam
            elif nombre_c.startswith("Horas Extras 25"):
                cuenta = getattr(cfg, 'cuenta_horas_extra_25', '')
            elif nombre_c.startswith("Horas Extras 35"):
                cuenta = getattr(cfg, 'cuenta_horas_extra_35', '')
            elif nombre_c == "Descanso Vacacional":
                cuenta = getattr(cfg, 'cuenta_descanso_vacacional', '')
            elif nombre_c == "Descanso Médico":
                cuenta = getattr(cfg, 'cuenta_descanso_medico', '')
            elif nombre_c == "Licencia con Goce":
                cuenta = getattr(cfg, 'cuenta_licencia_goce', '')
            else:
                cuenta = cuentas_concepto.get(nombre_c, "")
            filas.append(_fila(11, 1, fecha_asiento, cuenta, monto, 0.0, num_doc_asiento, glosa_asiento,
                                cod_prov_clie=dni, ruc=dni, r_social=nombre))
            d["debe"] += monto

        essalud_trab = float(row.get('Aporte Seg. Social', 0) or 0)
        onp_trab = float(row.get('ONP (13%)', 0) or 0)
        ret5ta_trab = float(row.get('Ret. 5ta Cat.', 0) or 0)
        total_essalud += essalud_trab
        total_onp += onp_trab
        total_5ta += ret5ta_trab
        d["debe"] += essalud_trab   # EsSalud es gasto también, aunque salga en línea global
        d["haber"] += essalud_trab + onp_trab + ret5ta_trab

        monto_afp_calculado = sum(float(row.get(c, 0) or 0) for c in ["AFP Aporte", "AFP Seguro", "AFP Comis."])

        # "Ajuste AFP (Audit)" — ajuste manual del Panel de Auditoría Tributaria, se
        # resta del neto POR SU CUENTA (no es un "descuento dinámico" más) y debe ir a
        # la MISMA cuenta de AFP/ONP del trabajador, sea positivo o negativo — nunca se
        # descarta, aunque sea negativo (ver bug corregido: antes se perdía).
        aj_afp = float(descuentos.get(_CLAVE_AJUSTE_AFP, 0) or 0)
        if sist in total_afp:
            total_afp[sist] += monto_afp_calculado + aj_afp
            d["haber"] += monto_afp_calculado + aj_afp
        elif sist == "ONP":
            total_onp += aj_afp
            d["haber"] += aj_afp

        # Créditos por trabajador: préstamos/descuentos dinámicos (cuenta propia)
        tardanzas = float(descuentos.get('Tardanzas', 0) or 0)
        for nombre_c, monto in descuentos.items():
            monto = float(monto or 0)
            if monto <= 0 or nombre_c in _DESCUENTOS_ESPECIALES:
                continue
            cuenta_desc = cuentas_concepto.get(nombre_c) or getattr(cfg, 'cuenta_prestamos_personal', '')
            filas.append(_fila(11, 1, fecha_asiento, cuenta_desc, 0.0, monto, num_doc_asiento, glosa_asiento,
                                cod_prov_clie=dni, ruc=dni, r_social=nombre))
            d["haber"] += monto

        # Remuneraciones por Pagar = Neto + Tardanzas + Ajuste Varios (ninguno de los
        # dos tiene cuenta propia — reducen/aumentan lo que se le debe al trabajador
        # sin generar un pasivo hacia un tercero distinto).
        aj_otros = float(descuentos.get(_CLAVE_AJUSTE_OTROS, 0) or 0)
        neto = float(row.get('NETO A PAGAR', 0) or 0)
        monto_remun_pagar = neto + tardanzas + aj_otros
        if monto_remun_pagar > 0:
            filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, 'cuenta_remuneraciones_por_pagar', ''),
                                0.0, monto_remun_pagar, num_doc_asiento, glosa_asiento,
                                cod_prov_clie=dni, ruc=dni, r_social=nombre))
            d["haber"] += monto_remun_pagar

    # ── Líneas globales: EsSalud (gasto + pasivo), ONP, AFP x4, Retención 5ta ──
    if total_essalud > 0:
        filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, 'cuenta_essalud_gasto', ''),
                            total_essalud, 0.0, num_doc_asiento, glosa_asiento))
        filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, 'cuenta_essalud_pasivo', ''),
                            0.0, total_essalud, num_doc_asiento, glosa_asiento))
    if total_onp > 0:
        filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, 'cuenta_onp', ''),
                            0.0, total_onp, num_doc_asiento, glosa_asiento))
    for admin, monto in total_afp.items():
        if monto > 0:
            filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, _AFP_CUENTA_ATTR[admin], ''),
                                0.0, monto, num_doc_asiento, glosa_asiento))
    if total_5ta > 0:
        filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, 'cuenta_retencion_5ta', ''),
                            0.0, total_5ta, num_doc_asiento, glosa_asiento))

    # ── Seguro interno: el asiento SIEMPRE debe cuadrar ──
    total_debe = sum(f["Monto Debe"] for f in filas)
    total_haber = sum(f["Monto Haber"] for f in filas)
    if round(total_debe - total_haber, 2) != 0:
        detalle = []
        for dni, d in diagnostico.items():
            diferencia = round(d["debe"] - d["haber"], 2)
            if diferencia != 0:
                detalle.append({
                    "dni": dni, "nombre": d["nombre"],
                    "debe": round(d["debe"], 2), "haber": round(d["haber"], 2),
                    "diferencia": diferencia,
                })
        detalle.sort(key=lambda x: abs(x["diferencia"]), reverse=True)
        raise AsientoContableError(
            f"El asiento no cuadra (Debe: S/ {total_debe:,.2f} vs Haber: S/ {total_haber:,.2f}). "
            f"No se generó el archivo — este es un error interno, no de configuración.",
            detalle_diagnostico=detalle,
        )

    df_out = pd.DataFrame(filas, columns=COLUMNAS_SISCONT)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_out.to_excel(writer, index=False, sheet_name='Asiento')
    buffer.seek(0)
    return buffer
