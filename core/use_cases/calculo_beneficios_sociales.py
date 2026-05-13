"""
Motor de cálculo de Beneficios Sociales: Gratificaciones y CTS.
Ley 27735 (Gratificaciones) y D.L. 650 (CTS).
"""
import calendar
import datetime
from core.domain.payroll_engine import obtener_factores_regimen


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


# ── Función auxiliar: meses con ≥15 días laborados ────────────────────────────

def _meses_computados(fecha_ingreso: datetime.date,
                      fecha_cese,              # datetime.date | None
                      inicio_rango: datetime.date,
                      fin_rango: datetime.date) -> int:
    """
    Cuenta meses donde el trabajador prestó servicios ≥ 15 días calendario
    dentro del rango indicado (regla Ley 27735 / D.L. 650).
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

        if ef_fin >= ef_ini:
            dias = (ef_fin - ef_ini).days + 1
            if dias >= 15:
                meses += 1

        cur_month += 1
        if cur_month > 12:
            cur_month = 1
            cur_year += 1

    return meses


# ── Gratificaciones ────────────────────────────────────────────────────────────

def calcular_gratificacion_trabajador(
    trabajador,
    semestre: str,          # 'ENE-JUN' o 'JUL-DIC'
    anio: int,
    rmv: float,
    regimen_empresa: str = 'Régimen General',
    fecha_acogimiento=None,
    factor_override=None,   # float | None  (de Empresa.factor_proyeccion_grati)
    extras_computables: float = 0.0,  # suma de conceptos computable_grati adicionales
) -> dict:
    """
    Calcula la gratificación legal de un trabajador para un semestre dado.

    Devuelve dict con: base_computable, factor_grati, meses_computados,
    monto_grati, bono_9pct, total, codigo_sunat, aplica, observaciones.
    """
    from presentation.views.maestro_trabajadores import determinar_regimen_trabajador

    regimen_trab = determinar_regimen_trabajador(
        trabajador.fecha_ingreso, regimen_empresa, fecha_acogimiento
    )
    factores = obtener_factores_regimen(regimen_trab)

    # El factor_override de la empresa prevalece sobre el régimen
    factor_grati = (
        float(factor_override) if factor_override is not None
        else factores['grati']
    )

    monto_asig_fam  = (rmv * 0.10) if trabajador.asig_fam else 0.0
    base_computable = trabajador.sueldo_base + monto_asig_fam + extras_computables

    cfg       = SEMESTRES_GRATI[semestre]
    meses_sem = cfg['meses']
    inicio    = datetime.date(anio, meses_sem[0], 1)
    fin       = datetime.date(anio, meses_sem[-1],
                              calendar.monthrange(anio, meses_sem[-1])[1])

    fecha_ingreso = trabajador.fecha_ingreso or inicio
    fecha_cese    = getattr(trabajador, 'fecha_cese', None)

    meses_comp  = _meses_computados(fecha_ingreso, fecha_cese, inicio, fin)
    monto_grati = round(base_computable * factor_grati * (meses_comp / 6.0), 2)
    bono_9pct   = round(monto_grati * 0.09, 2)
    total       = round(monto_grati + bono_9pct, 2)

    obs = []
    if regimen_trab != regimen_empresa:
        obs.append(f'Derechos adquiridos ({regimen_trab})')
    if factor_override is not None and factor_override != factores['grati']:
        obs.append(f'Factor manual {factor_grati*100:.0f}%')
    if meses_comp < 6:
        obs.append(f'{meses_comp}/6 meses')
    if not trabajador.asig_fam:
        pass   # silencioso; la asig_fam es la info positiva que se menciona si aplica

    return {
        'regimen_trab':    regimen_trab,
        'factor_grati':    factor_grati,
        'base_computable': round(base_computable, 2),
        'monto_asig_fam':  round(monto_asig_fam, 2),
        'meses_computados': meses_comp,
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
) -> dict:
    """
    Calcula el depósito de CTS de un trabajador para un período dado.

    Devuelve dict con: base_computable, sexto_grati, base_cts, factor_cts,
    meses_computados, monto_cts, aplica, periodo_label, observaciones.
    """
    from presentation.views.maestro_trabajadores import determinar_regimen_trabajador

    regimen_trab = determinar_regimen_trabajador(
        trabajador.fecha_ingreso, regimen_empresa, fecha_acogimiento
    )
    factores   = obtener_factores_regimen(regimen_trab)
    factor_cts = factores['cts']

    monto_asig_fam   = (rmv * 0.10) if trabajador.asig_fam else 0.0
    remuneracion_base = trabajador.sueldo_base + monto_asig_fam + extras_computables
    sexto_grati       = round(grati_semestral / 6.0, 2)
    base_cts          = round(remuneracion_base + sexto_grati, 2)

    cfg = PERIODOS_CTS[periodo]
    if periodo == 'NOV-ABR':
        inicio_rango = datetime.date(anio_deposito - 1, cfg['mes_inicio'], 1)
        fin_rango    = datetime.date(anio_deposito, cfg['mes_fin'],
                                    calendar.monthrange(anio_deposito, cfg['mes_fin'])[1])
    else:  # MAY-OCT
        inicio_rango = datetime.date(anio_deposito, cfg['mes_inicio'], 1)
        fin_rango    = datetime.date(anio_deposito, cfg['mes_fin'],
                                    calendar.monthrange(anio_deposito, cfg['mes_fin'])[1])

    fecha_ingreso = trabajador.fecha_ingreso or inicio_rango
    fecha_cese    = getattr(trabajador, 'fecha_cese', None)

    meses_comp = _meses_computados(fecha_ingreso, fecha_cese, inicio_rango, fin_rango)
    monto_cts  = round(base_cts * factor_cts * (meses_comp / 12.0), 2)

    obs = []
    if regimen_trab != regimen_empresa:
        obs.append(f'Derechos adquiridos ({regimen_trab})')
    if factor_cts < 1.0 and factor_cts > 0:
        obs.append(f'Factor CTS {factor_cts*100:.0f}%')
    if meses_comp < 6:
        obs.append(f'{meses_comp}/6 meses')

    return {
        'regimen_trab':     regimen_trab,
        'factor_cts':       factor_cts,
        'remuneracion_base': round(remuneracion_base, 2),
        'monto_asig_fam':   round(monto_asig_fam, 2),
        'sexto_grati':      sexto_grati,
        'base_cts':         base_cts,
        'meses_computados': meses_comp,
        'monto_cts':        monto_cts,
        'aplica':           factor_cts > 0,
        'periodo_label':    (f"{inicio_rango.strftime('%d/%m/%Y')} "
                             f"– {fin_rango.strftime('%d/%m/%Y')}"),
        'observaciones':    ' | '.join(obs),
    }
