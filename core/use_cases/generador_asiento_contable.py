"""
Generador del Asiento Contable de Planilla — Excel de importación a SISCONT.

Alcance (confirmado con el usuario):
  - Julio (07) y diciembre (12) incluyen el pago de la gratificación + bono extraordinario.
    Lo ya provisionado mes a mes (libro `provisiones_gratificacion`, ver
    provision_gratificacion.py) se cancela contra "Gratificación por pagar" y solo la
    DIFERENCIA va a gasto (o se recupera si la provisión excedió). Sin provisiones
    registradas — p. ej. julio 2026, el mes de corte — todo el pago se reconoce como gasto
    en ese mes (el "ajuste en julio").
  - Solo trabajadores de Planilla (5ta categoría) — los locadores (4ta) no entran aquí,
    ellos emiten recibo por honorarios y se registran directo en el sistema contable.
  - Un solo voucher por planilla del mes (su Num.Voucher lo asigna numeracion_vouchers.py según el orden de generación) — sin asiento de pago, sin
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
from core.domain import seguros_empleador as seg_emp
from core.use_cases import numeracion_vouchers as _nv

# Marcador de versión — súbelo cada vez que se corrija algo en este archivo, para poder
# confirmar en pantalla (pestaña Asiento Contable) si el código desplegado es el último.
VERSION_GENERADOR = "2026-11-25-r2"

MESES_ES = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL", 5: "MAYO", 6: "JUNIO",
    7: "JULIO", 8: "AGOSTO", 9: "SEPTIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE",
}

# Conceptos de gratificación — NO pasan por el flujo genérico de "concepto -> cuenta":
# tienen tratamiento propio (cancelan la provisión del libro y la diferencia va a gasto,
# ver bloque "Gratificación pagada" más abajo).
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
# "Descuento EPS" (Ley 26790) también tiene su propio tratamiento: línea dedicada a la
# cuenta "EPS Por Pagar" (ver más abajo) — no debe caer en la cuenta de Préstamos.
_CLAVE_DSCTO_EPS = "Descuento EPS"
_DESCUENTOS_ESPECIALES = ("Faltas", "Tardanzas", _CLAVE_AJUSTE_AFP, _CLAVE_AJUSTE_OTROS, _CLAVE_RET_5TA, _CLAVE_DSCTO_EPS)

# _calcular_pension() en calculo_mensual.py TAMBIÉN escribe el detalle de AFP/ONP dentro
# de desglose_descuentos (con el nombre de la administradora incluido en la clave, ej.
# "APORTE OBLIGATORIO AFP INTEGRA") — pero ese monto ya se contabiliza aparte, leyendo
# directo las columnas "AFP Aporte"/"AFP Seguro"/"AFP Comis."/"ONP (13%)" de la sábana.
# Si no se excluye, se duplicaba: una vez bien (cuenta de AFP/ONP) y otra de más (crédito
# extra a Préstamos al Personal), "robándole" ese monto a Remuneraciones por Pagar.
_PREFIJOS_DETALLE_PENSION = ("APORTE OBLIGATORIO ", "PRIMA DE SEGURO ", "COMISIÓN ")


def _es_descuento_ya_manejado(nombre: str) -> bool:
    """True si esta clave de desglose_descuentos ya tiene su propio tratamiento contable
    (informativo, ajuste de auditoría, retención 5ta, o detalle de AFP/ONP) y NO debe
    pasar por el flujo genérico de 'descuento dinámico -> cuenta de Préstamos'."""
    if nombre in _DESCUENTOS_ESPECIALES or nombre == "Aporte ONP":
        return True
    return nombre.startswith(_PREFIJOS_DETALLE_PENSION)

_AFP_CUENTA_ATTR = {
    "AFP HABITAT": "cuenta_afp_habitat",
    "AFP INTEGRA": "cuenta_afp_integra",
    "AFP PRIMA": "cuenta_afp_prima",
    "AFP PROFUTURO": "cuenta_afp_profuturo",
}

# RUC/Razón Social de las entidades a quienes se les debe ONP, Retención de 5ta y cada
# AFP — se usan en las líneas globales (Cod.Prov.Clie/RUC/R.Social) para que SISCONT
# pueda identificar al acreedor de cada cuenta por pagar, aunque el monto esté
# totalizado por empresa (no por trabajador).
_RUC_SUNAT = "20131312955"
_NOMBRE_SUNAT = "SUNAT"

_AFP_RUC_RSOCIAL = {
    "AFP HABITAT": ("20551464971", "AFP Habitat S.A."),
    "AFP INTEGRA": ("20157036794", "AFP Integra S.A."),
    "AFP PRIMA": ("20510398158", "Prima AFP S.A."),
    "AFP PROFUTURO": ("20142829551", "Profuturo AFP S.A."),
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


def aviso_cuentas_repetidas(etiqueta: str, cuenta_gasto: str, cuenta_pasivo: str):
    """Texto de aviso si el gasto y el pasivo de un mismo beneficio tienen la MISMA cuenta (el asiento
    repetiría esa cuenta en el Debe y en el Haber y no registraría nada); None si están bien."""
    g, p = (cuenta_gasto or "").strip(), (cuenta_pasivo or "").strip()
    if g and p and g == p:
        return (f"{etiqueta}: la cuenta de gasto y la de pasivo son la misma ({g}); deben ser distintas "
                f"(Configuración Contable)")
    return None


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

    planilla =db.query(PlanillaMensual).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first()
    if not planilla or planilla.estado != 'CERRADA':
        raise AsientoContableError(f"La planilla del periodo {periodo_key} no está cerrada todavía.")

    df_resultados = pd.read_json(io.StringIO(planilla.resultado_json), orient='records')
    auditoria_data = json.loads(planilla.auditoria_json)
    if df_resultados.empty or 'Apellidos y Nombres' not in df_resultados.columns:
        raise AsientoContableError(
            f"No hay trabajadores de Planilla (5ta categoría) calculados en {periodo_key} "
            f"— probablemente ese mes solo hubo locadores (4ta categoría), que emiten "
            f"recibo por honorarios y no generan asiento por este módulo."
        )
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
    if necesita["dvac"]: _cuenta_fija('cuenta_descanso_vacacional', "Vacaciones — Gasto (débito) · Descanso Vacacional (Configuración Contable)")
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
        if not _es_descuento_ya_manejado(k) and k not in cuentas_concepto
    )
    if necesita_prestamos:
        _cuenta_fija('cuenta_prestamos_personal', "Préstamos al Personal (Configuración Contable)")

    necesita_eps = any(
        float((info.get('descuentos', {}) or {}).get(_CLAVE_DSCTO_EPS, 0) or 0) > 0
        for info in auditoria_data.values()
    )
    if necesita_eps:
        _cuenta_fija('cuenta_eps_por_pagar', "EPS Por Pagar (Configuración Contable)")

    # Gratificación pagada este mes (julio/diciembre): cancela lo provisionado en el libro
    # y solo la diferencia va a gasto. Con el libro vacío (p. ej. julio 2026, mes de corte)
    # todo el pago es gasto del mes. Import diferido: provision_gratificacion importa este módulo.
    from core.use_cases import provision_gratificacion as _pg
    _sem_pago = _pg.semestre_pagado_en(mes_num)
    _provisionado = _pg.provisiones_por_dni(db, empresa_id, _sem_pago, anio_num) if _sem_pago else {}
    grati_trab = {}   # dni -> {"pagado", "provisionado", "ajuste"}
    for _dni_g, _info_g in auditoria_data.items():
        _ing_g = (_info_g or {}).get('ingresos', {}) or {}
        _pagado = round(float(_ing_g.get(_pg.CLAVE_GRATI_PAGADA, 0) or 0)
                        + float(_ing_g.get(_pg.CLAVE_BONO_PAGADO, 0) or 0), 2)
        if _pagado <= 0:
            continue
        _g, _b = _provisionado.get(str(_dni_g), (0.0, 0.0))
        _prov = round(_g + _b, 2)
        grati_trab[str(_dni_g)] = {"pagado": _pagado, "provisionado": _prov, "ajuste": round(_pagado - _prov, 2)}
    if any(v["ajuste"] != 0 for v in grati_trab.values()):
        _cuenta_fija(_pg.CUENTA_GASTO, "Gratificación — Gasto (Configuración Contable)")
    if grati_trab:   # lo pagado se acredita a "Gratificaciones por pagar" (y lo provisionado se debita de ella)
        _cuenta_fija(_pg.CUENTA_PASIVO, "Gratificación — Por Pagar (crédito) (Configuración Contable)")
        _rep_g = aviso_cuentas_repetidas("Gratificación", getattr(cfg, _pg.CUENTA_GASTO, ''), getattr(cfg, _pg.CUENTA_PASIVO, ''))
        if _rep_g:
            faltantes.add(_rep_g)

    # Vacaciones gozadas en el mes: se cancelan contra lo provisionado (libro de vacaciones) y
    # solo el resto es gasto. Sin libro en uso (o antes del corte) todo sigue siendo gasto.
    from core.use_cases import provision_vacaciones as _pv
    vac_cancel = _pv.cancelaciones_planilla(db, empresa_id, periodo_key, auditoria_data)
    if any(v > 0 for v in vac_cancel.values()):
        _cuenta_fija(_pv.CUENTA_PASIVO, "Vacaciones — Por Pagar (crédito) (Configuración Contable)")
        _rep_v = aviso_cuentas_repetidas("Vacaciones", getattr(cfg, _pv.CUENTA_GASTO, ''), getattr(cfg, _pv.CUENTA_PASIVO, ''))
        if _rep_v:
            faltantes.add(_rep_v)

    # Seguros a cargo del empleador (Vida Ley / SCTR): solo se exigen las cuentas de los
    # seguros que tienen monto este mes.
    totales_seguros_check = seg_emp.totales_por_seguro(auditoria_data)
    for _seg, _tot in totales_seguros_check.items():
        if _tot > 0:
            _attr_gasto, _attr_pasivo = seg_emp.CUENTAS_CONTABLES[_seg]
            _cuenta_fija(_attr_gasto, f"{seg_emp.ETIQUETAS[_seg]} — Gasto (Configuración Contable)")
            _cuenta_fija(_attr_pasivo, f"{seg_emp.ETIQUETAS[_seg]} — Por Pagar (Configuración Contable)")

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
            if float(monto or 0) <= 0 or _es_descuento_ya_manejado(nombre_c):
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
    # Como texto "dd/mm/yyyy" (no como objeto date) para que SISCONT no lo reciba en
    # formato ISO — Fecha, Fec.Doc y Fec.Ven usan este mismo valor en cada fila.
    fecha_asiento = date(anio_num, mes_num, dias_mes).strftime('%d/%m/%Y')
    num_doc_asiento = f"BS{mes_num:02d}-{anio_num}"
    glosa_asiento = f"PLANILLA DE SUELDO {MESES_ES.get(mes_num, '')} {anio_num}"

    cuenta_sueldo = cuentas_concepto.get("SUELDO BASICO", "")
    cuenta_asig_fam = cuentas_concepto.get("ASIGNACION FAMILIAR", "")

    filas = []
    total_essalud = 0.0
    total_onp = 0.0
    total_5ta = 0.0
    total_afp = {k: 0.0 for k in _AFP_CUENTA_ATTR}
    total_seguros = {s: 0.0 for s in seg_emp.SEGUROS}  # Vida Ley / SCTR a cargo del empleador

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
        debe_ingresos_trab = 0.0  # Total Bruto de ESTE trabajador (sin EsSalud)
        for nombre_c, monto in ingresos.items():
            monto = float(monto or 0)
            if monto <= 0 or nombre_c in _CONCEPTOS_GRATI_EXCLUIDOS:
                continue
            if nombre_c == _pv.CLAVE_PAGO_VACACIONES and vac_cancel.get(dni, 0) > 0:
                # Vacaciones gozadas: Debe = pasivo provisionado (se cancela) + gasto por el resto
                canc = vac_cancel[dni]
                _glosa_v = f"{glosa_asiento} - VACACIONES"
                # El pasivo que se cancela es la partida de vacaciones del ejercicio (mismo Num.Doc que sus provisiones)
                _doc_v = _nv.doc_vacaciones(anio_num)
                filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, _pv.CUENTA_PASIVO, ''), canc, 0.0,
                                    _doc_v, _glosa_v, cod_prov_clie=dni, ruc=dni, r_social=nombre))
                resto = round(monto - canc, 2)
                if resto > 0:
                    filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, 'cuenta_descanso_vacacional', ''), resto, 0.0,
                                        _doc_v, _glosa_v, cod_prov_clie=dni, ruc=dni, r_social=nombre))
                d["debe"] += monto
                debe_ingresos_trab += monto
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
            debe_ingresos_trab += monto

        # Gratificación pagada (julio/diciembre): Debe = pasivo provisionado (se cancela) +
        # gasto por la diferencia; si la provisión excedió lo pagado, el sobrante se recupera
        # (Haber a gasto). El total pagado entra a "Remuneraciones por Pagar" vía el residual.
        g_pag = grati_trab.get(dni)
        if g_pag:
            # La glosa dice QUÉ semestre se paga; en el mes de corte (sin provisión previa) es la regularización
            _glosa_g = f"{glosa_asiento} - GRATIFICACION {_sem_pago} {anio_num}"
            if g_pag["provisionado"] == 0 and (anio_num, mes_num) == _pg.INICIO_PROVISION:
                _glosa_g += " (REGULARIZACION)"
            if g_pag["provisionado"] > 0:
                # Cancela la partida del semestre (mismo Num.Doc que sus provisiones mensuales)
                filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, _pg.CUENTA_PASIVO, ''),
                                    g_pag["provisionado"], 0.0, _nv.doc_gratificacion(_sem_pago, anio_num), _glosa_g,
                                    cod_prov_clie=dni, ruc=dni, r_social=nombre))
                d["debe"] += g_pag["provisionado"]
            if g_pag["ajuste"] > 0:
                filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, _pg.CUENTA_GASTO, ''),
                                    g_pag["ajuste"], 0.0, num_doc_asiento, _glosa_g,
                                    cod_prov_clie=dni, ruc=dni, r_social=nombre))
                d["debe"] += g_pag["ajuste"]
            elif g_pag["ajuste"] < 0:
                filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, _pg.CUENTA_GASTO, ''),
                                    0.0, -g_pag["ajuste"], num_doc_asiento, _glosa_g,
                                    cod_prov_clie=dni, ruc=dni, r_social=nombre))
                d["haber"] += -g_pag["ajuste"]
            debe_ingresos_trab += g_pag["pagado"]

        essalud_trab =float(row.get('Aporte Seg. Social', 0) or 0)
        onp_trab = float(row.get('ONP (13%)', 0) or 0)
        ret5ta_trab = float(row.get('Ret. 5ta Cat.', 0) or 0)
        total_essalud += essalud_trab
        total_onp += onp_trab
        total_5ta += ret5ta_trab
        d["debe"] += essalud_trab   # EsSalud es gasto también, aunque salga en línea global
        d["haber"] += essalud_trab + onp_trab + ret5ta_trab

        # Seguros a cargo del empleador: gasto y pasivo por el MISMO monto (cuadra por
        # construcción) — no salen del neto del trabajador, así que no tocan el residual.
        for _seg, _ap in (info.get('aportes_empleador', {}) or {}).items():
            if _seg not in total_seguros:
                continue
            _m = float((_ap or {}).get('monto', 0) or 0)
            if _m > 0:
                total_seguros[_seg] += _m
                d["debe"] += _m
                d["haber"] += _m

        monto_afp_calculado = sum(float(row.get(c, 0) or 0) for c in ["AFP Aporte", "AFP Seguro", "AFP Comis."])

        # "Ajuste AFP (Audit)" — ajuste manual del Panel de Auditoría Tributaria, se
        # resta del neto POR SU CUENTA (no es un "descuento dinámico" más) y debe ir a
        # la MISMA cuenta de AFP/ONP del trabajador, sea positivo o negativo — nunca se
        # descarta, aunque sea negativo (ver bug corregido: antes se perdía).
        aj_afp = float(descuentos.get(_CLAVE_AJUSTE_AFP, 0) or 0)
        credito_pension_trab = 0.0  # lo que se le retuvo por AFP/ONP, para el residual de abajo
        if sist in total_afp:
            total_afp[sist] += monto_afp_calculado + aj_afp
            d["haber"] += monto_afp_calculado + aj_afp
            credito_pension_trab = monto_afp_calculado + aj_afp
        elif sist == "ONP":
            total_onp += aj_afp
            d["haber"] += aj_afp
            credito_pension_trab = aj_afp  # onp_trab ya se sumó arriba en la línea de EsSalud/ONP/5ta

        # Créditos por trabajador: préstamos/descuentos dinámicos (cuenta propia)
        credito_prestamos_dinamicos = 0.0
        for nombre_c, monto in descuentos.items():
            monto = float(monto or 0)
            if monto <= 0 or _es_descuento_ya_manejado(nombre_c):
                continue
            cuenta_desc = cuentas_concepto.get(nombre_c) or getattr(cfg, 'cuenta_prestamos_personal', '')
            filas.append(_fila(11, 1, fecha_asiento, cuenta_desc, 0.0, monto, num_doc_asiento, glosa_asiento,
                                cod_prov_clie=dni, ruc=dni, r_social=nombre))
            d["haber"] += monto
            credito_prestamos_dinamicos += monto

        # Descuento EPS al trabajador (Ley 26790) — línea propia a "EPS Por Pagar" (se le
        # debe a la aseguradora privada, no a SUNAT ni es un préstamo). Igual que ONP/5ta/
        # AFP, se resta explícitamente del residual de abajo para no perderlo ni duplicarlo.
        credito_eps_trab = float(descuentos.get(_CLAVE_DSCTO_EPS, 0) or 0)
        if credito_eps_trab > 0:
            filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, 'cuenta_eps_por_pagar', ''),
                                0.0, credito_eps_trab, num_doc_asiento, glosa_asiento,
                                cod_prov_clie=dni, ruc=dni, r_social=nombre))
            d["haber"] += credito_eps_trab

        # Remuneraciones por Pagar se calcula como RESIDUAL (Total Bruto del trabajador
        # menos todo lo que ya se le acreditó a otras cuentas) — NO se usa el campo
        # "NETO A PAGAR" guardado en la planilla. Esto garantiza que el asiento cuadre
        # siempre por construcción, sin depender de que ese campo coincida exactamente
        # con la suma de sus componentes (evita descuadres si el dato guardado difiere).
        monto_remun_pagar = (
            debe_ingresos_trab - onp_trab - ret5ta_trab
            - credito_pension_trab - credito_prestamos_dinamicos - credito_eps_trab
        )
        # La gratificación (+ bono) pagada se acredita a "Gratificaciones por pagar" y no a
        # Remuneraciones por Pagar: es el pasivo contra el que se pagó/provisionó. Si las deducciones
        # del trabajador superaran lo demás, el faltante se toma de este crédito (siempre cuadra).
        if g_pag and monto_remun_pagar > 0:
            credito_grati = round(min(g_pag["pagado"], monto_remun_pagar), 2)
            filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, _pg.CUENTA_PASIVO, ''),
                                0.0, credito_grati, num_doc_asiento, _glosa_g,
                                cod_prov_clie=dni, ruc=dni, r_social=nombre))
            d["haber"] += credito_grati
            monto_remun_pagar = round(monto_remun_pagar - credito_grati, 2)
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
                            0.0, total_essalud, num_doc_asiento, glosa_asiento,
                            cod_prov_clie=_RUC_SUNAT, ruc=_RUC_SUNAT, r_social=_NOMBRE_SUNAT))
    for _seg in seg_emp.SEGUROS:
        _m = round(total_seguros[_seg], 2)
        if _m > 0:
            _attr_gasto, _attr_pasivo = seg_emp.CUENTAS_CONTABLES[_seg]
            _glosa_seg = f"{glosa_asiento} - {seg_emp.ETIQUETAS[_seg].upper()}"
            filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, _attr_gasto, ''),
                                _m, 0.0, num_doc_asiento, _glosa_seg))
            filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, _attr_pasivo, ''),
                                0.0, _m, num_doc_asiento, _glosa_seg))
    if total_onp > 0:
        filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, 'cuenta_onp', ''),
                            0.0, total_onp, num_doc_asiento, glosa_asiento,
                            cod_prov_clie=_RUC_SUNAT, ruc=_RUC_SUNAT, r_social=_NOMBRE_SUNAT))
    for admin, monto in total_afp.items():
        if monto > 0:
            ruc_afp, rsocial_afp = _AFP_RUC_RSOCIAL.get(admin, ("", ""))
            filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, _AFP_CUENTA_ATTR[admin], ''),
                                0.0, monto, num_doc_asiento, glosa_asiento,
                                cod_prov_clie=ruc_afp, ruc=ruc_afp, r_social=rsocial_afp))
    if total_5ta > 0:
        filas.append(_fila(11, 1, fecha_asiento, getattr(cfg, 'cuenta_retencion_5ta', ''),
                            0.0, total_5ta, num_doc_asiento, glosa_asiento,
                            cod_prov_clie=_RUC_SUNAT, ruc=_RUC_SUNAT, r_social=_NOMBRE_SUNAT))

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

    _nv.numerar_filas(db, empresa_id, periodo_key, _nv.CLAVE_PLANILLA, filas)
    df_out = pd.DataFrame(filas, columns=COLUMNAS_SISCONT)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_out.to_excel(writer, index=False, sheet_name='Asiento')
    buffer.seek(0)
    return buffer
