"""
Motor de cálculo de Beneficios Sociales: Gratificaciones y CTS.
Ley 27735 (Gratificaciones) y D.L. 650 (CTS).
"""
import calendar
import datetime
from dateutil.relativedelta import relativedelta
from core.domain.payroll_engine import obtener_factores_regimen, determinar_regimen_trabajador


# ── Configuración de semestres y períodos ──────────────────────────────────────

SEMESTRES_GRATI = {
    'ENE-JUN': {
        'meses': list(range(1, 7)),
        'mes_pago': 7,
        'codigo_sunat': '0301',
        'label': 'Enero – Junio',
        'concepto_json_key': 'GRATIFICACION (JUL/DIC)',
    },
    'JUL-DIC': {
        'meses': list(range(7, 13)),
        'mes_pago': 12,
        'codigo_sunat': '0302',
        'label': 'Julio – Diciembre',
        'concepto_json_key': 'GRATIFICACION (JUL/DIC)',
    },
}

PERIODOS_CTS = {
    'NOV-ABR': {
        'mes_inicio': 11, 'desfase_inicio': -1,   # Nov del año anterior
        'mes_fin': 4,     'desfase_fin': 0,        # Abr del año de depósito
        'mes_deposito': 5,
        'label': 'Noviembre – Abril',
    },
    'MAY-OCT': {
        'mes_inicio': 5,  'desfase_inicio': 0,
        'mes_fin': 10,    'desfase_fin': 0,
        'mes_deposito': 11,
        'label': 'Mayo – Octubre',
    },
}


# Tabla 21 SUNAT — suspensiones que NO son tiempo computable para la CTS
# (D.S. 001-97-TR Art. 8: solo se computan los días de trabajo efectivo y los
# asimilados — vacaciones, licencias con goce, descanso médico, maternidad,
# huelga no ilegal, etc.). Se descuentan a razón de un treintavo por día.
#   01 Sanción disciplinaria · 03 Detención · 04 Inhabilitación/pena privativa
#   05 Permiso/licencia sin goce · 06 Caso fortuito/fuerza mayor
#   07 Falta no justificada · 08 Temporada/intermitente · 10 Sentencia
#   11 Medida cautelar · 12 Enfermedad de familiar (sin goce)
# No se incluyen 02 (huelga: computable salvo que se declare ilegal) ni
# 09 (maternidad: computable por mandato expreso del Art. 8).
SUSPENSIONES_NO_COMPUTABLES_CTS = frozenset(
    {"01", "03", "04", "05", "06", "07", "08", "10", "11", "12"}
)

# Claves de conceptos_json que nunca son "remuneración regular" para la CTS: la
# gratificación entra por el sexto, el bono 9% no es computable y los "_ajuste_*"
# son correcciones de auditoría, no pagos.
_CONCEPTOS_EXCLUIDOS_CTS = frozenset({
    "SUELDO BASICO", "ASIGNACION FAMILIAR", "GRATIFICACION (JUL/DIC)",
    "BONIFICACION EXTRAORDINARIA LEY 29351 (9%)",
})


def clave_periodo(periodo_key: str) -> tuple:
    """'MM-YYYY' -> (YYYY, MM) para ordenar cronológicamente. Ordenar los
    periodo_key como texto es incorrecto ('12-2025' > '11-2026')."""
    try:
        mm, yyyy = str(periodo_key).strip().split('-')
        return int(yyyy), int(mm)
    except (ValueError, AttributeError):
        return (0, 0)


def rango_cts(periodo: str, anio_deposito: int) -> tuple:
    """Fechas (inicio, fin) del semestre CTS que se deposita en mayo/noviembre de anio_deposito."""
    cfg = PERIODOS_CTS[periodo]
    if periodo == 'NOV-ABR':
        inicio = datetime.date(anio_deposito - 1, cfg['mes_inicio'], 1)
    else:
        inicio = datetime.date(anio_deposito, cfg['mes_inicio'], 1)
    fin = datetime.date(anio_deposito, cfg['mes_fin'],
                        calendar.monthrange(anio_deposito, cfg['mes_fin'])[1])
    return inicio, fin


def rango_grati(semestre: str, anio: int) -> tuple:
    """Fechas (inicio, fin) del semestre de gratificación (ENE-JUN o JUL-DIC) de un año."""
    meses = SEMESTRES_GRATI[semestre]['meses']
    return (datetime.date(anio, meses[0], 1),
            datetime.date(anio, meses[-1], calendar.monthrange(anio, meses[-1])[1]))


def periodo_keys_rango(inicio: datetime.date, fin: datetime.date) -> list:
    """Lista de periodo_key 'MM-YYYY' de cada mes entre inicio y fin (inclusive)."""
    keys = []
    y, m = inicio.year, inicio.month
    while (y, m) <= (fin.year, fin.month):
        keys.append(f"{m:02d}-{y}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return keys


def meses_con_servicio(fecha_ingreso, fecha_cese, inicio: datetime.date, fin: datetime.date) -> int:
    """Meses calendario del rango en los que el trabajador tuvo vínculo al menos un día."""
    n = 0
    for pk in periodo_keys_rango(inicio, fin):
        y, m = clave_periodo(pk)
        mes_ini = datetime.date(y, m, 1)
        mes_fin = datetime.date(y, m, calendar.monthrange(y, m)[1])
        if fecha_ingreso and fecha_ingreso > mes_fin:
            continue
        if fecha_cese and fecha_cese < mes_ini:
            continue
        n += 1
    return n


def dias_no_computables_cts(variables_meses: list) -> int:
    """
    Días de suspensión NO computables para la CTS dentro del semestre.

    `variables_meses`: lista de dicts {'suspensiones': {"07": 2, ...},
    'dias_faltados': int} — uno por mes. Mismo criterio que el motor de planilla:
    si el mes no tiene suspensiones_json, el campo legado dias_faltados se
    trata como falta injustificada (código 07).
    """
    total = 0
    for v in variables_meses or []:
        susp = v.get('suspensiones') or {}
        if susp:
            for cod, dias in susp.items():
                if str(cod).strip().zfill(2) in SUSPENSIONES_NO_COMPUTABLES_CTS:
                    try:
                        total += int(float(dias or 0))
                    except (TypeError, ValueError):
                        pass
        else:
            total += int(v.get('dias_faltados') or 0)
    return max(0, total)


def extras_computables_cts(variables_meses: list, nombres_computables, meses_servicio: int = 6) -> dict:
    """
    Remuneraciones complementarias computables para la CTS (D.S. 001-97-TR
    Arts. 16-19): conceptos de ingreso marcados "Computable CTS" en el Maestro
    de Conceptos que el trabajador percibió con regularidad.

    Criterio adoptado:
      - Semestre completo (6 meses de servicio): es regular si se percibió en
        al menos 3 de los 6 meses; se incorpora la suma / 6.
      - Semestre incompleto (ingreso o cese dentro del periodo): es regular si
        se percibió en al menos la mitad de los meses con servicio; se
        incorpora la suma / meses con servicio.
    """
    nombres = set(nombres_computables or ())
    divisor = max(1, min(6, int(meses_servicio or 0)))
    umbral = 3 if divisor >= 6 else -(-divisor // 2)  # techo de divisor/2

    montos, meses_con = {}, {}
    for v in variables_meses or []:
        for nombre, monto in (v.get('conceptos') or {}).items():
            if (nombre not in nombres or nombre in _CONCEPTOS_EXCLUIDOS_CTS
                    or str(nombre).startswith('_')):
                continue
            try:
                m = float(monto or 0)
            except (TypeError, ValueError):
                continue
            if m > 0:
                montos[nombre] = montos.get(nombre, 0.0) + m
                meses_con[nombre] = meses_con.get(nombre, 0) + 1

    detalle = {n: round(montos[n] / divisor, 2) for n in montos if meses_con[n] >= umbral}
    return {
        'total': round(sum(detalle.values()), 2),
        'detalle': detalle,
        'no_regulares': sorted(n for n in montos if meses_con[n] < umbral),
    }


# La gratificación usa la misma regla de regularidad (D.S. 005-2002-TR Art. 3:
# percibido en al menos 3 meses del semestre, se incorpora el promedio).
extras_computables_regulares = extras_computables_cts


# ── Bonificación extraordinaria (Ley 30334) ─────────────────────────────────────
# Equivale al aporte a EsSalud que la gratificación deja de pagar: 9 %, o 6.75 %
# si el trabajador está afiliado a una EPS.
TASA_BONO_EXTRAORDINARIO = 0.09
TASA_BONO_EXTRAORDINARIO_EPS = 0.0675


def tasa_bono_extraordinario(tiene_eps) -> float:
    return TASA_BONO_EXTRAORDINARIO_EPS if tiene_eps else TASA_BONO_EXTRAORDINARIO


# ── Gratificación voluntaria ────────────────────────────────────────────────────
# Para Micro Empresa la gratificación no es obligatoria (0 %) y para Pequeña Empresa
# es media (50 %), pero la empresa puede otorgar más por decisión propia. La opción
# elegida es un PISO: nunca baja lo que la ley ya obliga (Régimen General o
# trabajadores con derechos adquiridos siguen recibiendo el 100 %).
OPCIONES_GRATI_VOLUNTARIA = {
    "Según ley": None,
    "Media gratificación (50%)": 0.5,
    "Gratificación completa (100%)": 1.0,
}


def factor_grati_aplicable(factor_legal: float, factor_voluntario=None) -> float:
    """Factor final: el mayor entre el mínimo legal y lo que la empresa decidió otorgar."""
    try:
        voluntario = float(factor_voluntario) if factor_voluntario is not None else 0.0
    except (TypeError, ValueError):
        voluntario = 0.0
    return max(float(factor_legal), min(1.0, max(0.0, voluntario)))


def _meses_completos(fecha_ingreso: datetime.date,
                     fecha_cese,              # datetime.date | None
                     inicio_rango: datetime.date,
                     fin_rango: datetime.date) -> int:
    """
    Cuenta SOLO meses calendario ÍNTEGROS (del día 1 al último día del mes) dentro
    del rango — a diferencia de CTS/vacaciones (que reconocen fracciones de mes por
    día, ver _meses_y_dias_en_rango y calculo_kardex.py), la gratificación exige mes
    calendario completo (Ley 27735 / D.S. 005-2002-TR Art. 3: "proporcional a los
    meses calendarios completos laborados"): ni un solo día de por medio (ni 29 de
    30) se redondea a mes completo, ni se paga proporcional por día.
    """
    meses = 0
    cur_year  = inicio_rango.year
    cur_month = inicio_rango.month

    while (cur_year, cur_month) <= (fin_rango.year, fin_rango.month):
        dias_en_mes = calendar.monthrange(cur_year, cur_month)[1]
        mes_ini = datetime.date(cur_year, cur_month, 1)
        mes_fin = datetime.date(cur_year, cur_month, dias_en_mes)

        ef_ini = max(mes_ini, fecha_ingreso)
        ef_fin = mes_fin if not fecha_cese else min(mes_fin, fecha_cese)

        if ef_ini == mes_ini and ef_fin == mes_fin:
            meses += 1

        cur_month += 1
        if cur_month > 12:
            cur_month = 1
            cur_year += 1

    return meses


def _meses_y_dias_en_rango(fecha_ingreso: datetime.date,
                           fecha_cese,              # datetime.date | None
                           inicio_rango: datetime.date,
                           fin_rango: datetime.date) -> tuple:
    """
    Meses completos y días sueltos EFECTIVAMENTE laborados dentro de [inicio_rango,
    fin_rango], acotado por fecha_ingreso/fecha_cese si caen dentro del rango —
    "dozavos y treintavos" (D.S. 001-97-TR Art. 21, CTS; D.S. 012-92-TR Art. 23,
    Vacaciones): el resto de días NO se redondea a mes completo ni se descarta, se
    paga proporcional al día. Mismo criterio que calculo_kardex.py.
    """
    efectivo_ini = max(inicio_rango, fecha_ingreso)
    efectivo_fin = fin_rango if not fecha_cese else min(fin_rango, fecha_cese)

    if efectivo_fin < efectivo_ini:
        return 0, 0, efectivo_ini, efectivo_ini

    # +1 día: efectivo_fin es el ÚLTIMO DÍA TRABAJADO (inclusive) dentro del rango,
    # pero relativedelta mide tiempo transcurrido de forma EXCLUSIVA del punto de
    # partida. Sin este ajuste, un mes calendario completo (ej. 01/09 al 30/09,
    # trabajado íntegro) se contaría como "29 días sueltos" en vez de 1 mes completo.
    # Mismo criterio que calculo_kardex.py (vacaciones).
    delta = relativedelta(efectivo_fin + datetime.timedelta(days=1), efectivo_ini)
    return (delta.years * 12) + delta.months, delta.days, efectivo_ini, efectivo_fin


# ── Gratificaciones ────────────────────────────────────────────────────────────

def calcular_gratificacion_trabajador(
    trabajador,
    semestre: str,          # 'ENE-JUN' o 'JUL-DIC'
    anio: int,
    rmv: float,
    regimen_empresa: str = 'Régimen General',
    fecha_acogimiento=None,
    factor_override=None,   # float | None — gratificación voluntaria (0.5 / 1.0), ver abajo
    extras_computables: float = 0.0,  # promedio de conceptos "Computable Grati" regulares
) -> dict:
    """
    Calcula la gratificación de un trabajador para un semestre dado.

    `factor_override`: lo que la empresa decide otorgar (media o completa). Funciona
    como piso, nunca como techo: el factor final es max(mínimo legal, voluntario),
    así una política de "media gratificación" no recorta a quien por ley le toca
    el 100 % (Régimen General o derechos adquiridos).

    La bonificación extraordinaria es 9 % (6.75 % si el trabajador tiene EPS).

    Devuelve dict con: base_computable, factor_grati, factor_legal, es_voluntaria,
    meses_computados, monto_grati, bono_9pct, tasa_bono, total, codigo_sunat,
    aplica, observaciones.
    """
    regimen_trab = determinar_regimen_trabajador(
        trabajador.fecha_ingreso, regimen_empresa, fecha_acogimiento
    )
    factores = obtener_factores_regimen(regimen_trab)
    factor_legal = float(factores['grati'])
    factor_grati = factor_grati_aplicable(factor_legal, factor_override)
    es_voluntaria = factor_grati > factor_legal

    monto_asig_fam  = (rmv * 0.10) if trabajador.asig_fam else 0.0
    base_computable = trabajador.sueldo_base + monto_asig_fam + extras_computables

    cfg       = SEMESTRES_GRATI[semestre]
    meses_sem = cfg['meses']
    inicio    = datetime.date(anio, meses_sem[0], 1)
    fin       = datetime.date(anio, meses_sem[-1],
                              calendar.monthrange(anio, meses_sem[-1])[1])

    fecha_ingreso = trabajador.fecha_ingreso or inicio
    fecha_cese    = getattr(trabajador, 'fecha_cese', None)

    efectivo_ini = max(inicio, fecha_ingreso)
    efectivo_fin = fin if not fecha_cese else min(fin, fecha_cese)

    meses_comp  = _meses_completos(fecha_ingreso, fecha_cese, inicio, fin)
    monto_grati = round(base_computable * factor_grati * (meses_comp / 6.0), 2)
    tasa_bono   = tasa_bono_extraordinario(getattr(trabajador, 'eps', False))
    bono_9pct   = round(monto_grati * tasa_bono, 2)
    total       = round(monto_grati + bono_9pct, 2)

    obs = []
    if regimen_trab != regimen_empresa:
        obs.append(f'Derechos adquiridos ({regimen_trab})')
    if es_voluntaria:
        obs.append(f'Voluntaria {factor_grati*100:.0f}% (por ley: {factor_legal*100:.0f}%)')
    if meses_comp < 6:
        obs.append(f'{meses_comp}/6 meses')
    if tasa_bono != TASA_BONO_EXTRAORDINARIO:
        obs.append(f'Bono extraordinario {tasa_bono*100:.2f}% (EPS)')
    if extras_computables:
        obs.append(f'Incluye S/ {extras_computables:,.2f} de conceptos computables')

    return {
        'regimen_trab':    regimen_trab,
        'factor_grati':    factor_grati,
        'factor_legal':    factor_legal,
        'es_voluntaria':   es_voluntaria,
        'tasa_bono':       tasa_bono,
        'extras_computables': round(float(extras_computables or 0.0), 2),
        'base_computable': round(base_computable, 2),
        'monto_asig_fam':  round(monto_asig_fam, 2),
        'meses_computados': meses_comp,
        'fecha_efectivo_ini': efectivo_ini,
        'fecha_efectivo_fin': efectivo_fin,
        'semestre_label':  cfg['label'],
        'monto_grati':     monto_grati,
        'bono_9pct':       bono_9pct,
        'total':           total,
        'codigo_sunat':    cfg['codigo_sunat'],
        'concepto_json_key': cfg['concepto_json_key'],
        'aplica':          factor_grati > 0,
        'observaciones':   ' | '.join(obs),
    }


# ── CTS ───────────────────────────────────────────────────────────────────────

def calcular_cts_trabajador(
    trabajador,
    periodo: str,           # 'NOV-ABR' o 'MAY-OCT'
    anio_deposito: int,     # año del mes de depósito (Mayo o Noviembre)
    rmv: float,
    grati_semestral: float = 0.0,   # grati pagada/calculada para el semestre de referencia
    regimen_empresa: str = 'Régimen General',
    fecha_acogimiento=None,
    extras_computables: float = 0.0,
    dias_no_computables: int = 0,     # faltas / suspensiones no computables del semestre
    remuneracion_basica=None,         # float | None — sueldo vigente al cierre del periodo
) -> dict:
    """
    Calcula el depósito de CTS de un trabajador para un período dado.

    `remuneracion_basica`: sueldo vigente al cierre del semestre (abril/octubre) o a
    la fecha de cese. Si es None se usa trabajador.sueldo_base (valor actual del maestro).
    `dias_no_computables`: días de suspensión que no generan CTS (ver
    SUSPENSIONES_NO_COMPUTABLES_CTS); se descuentan a razón de 1/360 de la base.

    Devuelve dict con: base_computable, sexto_grati, base_cts, factor_cts,
    meses_computados, monto_cts, aplica, periodo_label, observaciones.
    """
    regimen_trab = determinar_regimen_trabajador(
        trabajador.fecha_ingreso, regimen_empresa, fecha_acogimiento
    )
    factores   = obtener_factores_regimen(regimen_trab)
    factor_cts = factores['cts']

    sueldo_usado = float(remuneracion_basica if remuneracion_basica is not None
                         else (trabajador.sueldo_base or 0.0))
    monto_asig_fam   = (rmv * 0.10) if trabajador.asig_fam else 0.0
    remuneracion_base = sueldo_usado + monto_asig_fam + extras_computables
    sexto_grati       = round(grati_semestral / 6.0, 2)
    base_cts          = round(remuneracion_base + sexto_grati, 2)

    inicio_rango, fin_rango = rango_cts(periodo, anio_deposito)

    fecha_ingreso = trabajador.fecha_ingreso or inicio_rango
    fecha_cese    = getattr(trabajador, 'fecha_cese', None)

    # Dozavos y treintavos (D.S. 001-97-TR Art. 21) — igual criterio que Vacaciones:
    # el resto de días del mes en curso se paga proporcional al día, no se redondea
    # a mes completo ni se descarta.
    meses_comp, dias_sueltos, efectivo_ini, efectivo_fin = _meses_y_dias_en_rango(
        fecha_ingreso, fecha_cese, inicio_rango, fin_rango
    )
    # Art. 8: los días no computables se descuentan a razón de un treintavo del mes
    # (1/360 de la base anual). Nunca puede quedar negativo.
    dias_no_comp = max(0, int(dias_no_computables or 0))
    fraccion = max(0.0, meses_comp / 12.0 + dias_sueltos / 360.0 - dias_no_comp / 360.0)
    monto_cts = round(base_cts * factor_cts * fraccion, 2)

    obs = []
    if regimen_trab != regimen_empresa:
        obs.append(f'Derechos adquiridos ({regimen_trab})')
    if factor_cts < 1.0 and factor_cts > 0:
        obs.append(f'Factor CTS {factor_cts*100:.0f}%')
    if meses_comp < 6:
        obs.append(f'{meses_comp} mes(es) {dias_sueltos} día(s) de 6 meses' if dias_sueltos else f'{meses_comp}/6 meses')
    if dias_no_comp:
        obs.append(f'{dias_no_comp} día(s) no computable(s) descontado(s)')
    if extras_computables:
        obs.append(f'Incluye S/ {extras_computables:,.2f} de conceptos computables')

    return {
        'regimen_trab':     regimen_trab,
        'factor_cts':       factor_cts,
        'sueldo_base_usado': round(sueldo_usado, 2),
        'extras_computables': round(float(extras_computables or 0.0), 2),
        'remuneracion_base': round(remuneracion_base, 2),
        'monto_asig_fam':   round(monto_asig_fam, 2),
        'sexto_grati':      sexto_grati,
        'base_cts':         base_cts,
        'meses_computados': meses_comp,
        'dias_sueltos':     dias_sueltos,
        'dias_no_computables': dias_no_comp,
        'fecha_efectivo_ini': efectivo_ini,
        'fecha_efectivo_fin': efectivo_fin,
        'monto_cts':        monto_cts,
        'aplica':           factor_cts > 0,
        'periodo_label':    (f"{inicio_rango.strftime('%d/%m/%Y')} "
                             f"– {fin_rango.strftime('%d/%m/%Y')}"),
        'observaciones':    ' | '.join(obs),
    }
