"""
Motor de cálculo de Liquidación por Cese.

Orquesta los motores que YA existen en el sistema en vez de reimplementar las
fórmulas legales por separado:
  - Gratificación y CTS truncas -> core/use_cases/calculo_beneficios_sociales.py
    (mismo motor que usa el módulo "Gratificaciones y CTS" — antes había una
    fórmula paralela, más simple e inconsistente, solo para liquidaciones).
  - Vacaciones pendientes -> core/use_cases/calculo_kardex.py (saldo real del
    Kardex, antes se pedía un número a mano).
  - Último depósito de CTS -> tabla DepositoCTS (fecha real, antes se adivinaba).
  - Préstamos pendientes -> se descuentan del neto (antes no se consideraban).
  - Retención de 5ta sobre la porción gravada -> reutiliza el motor de
    proyección anual real de calculo_mensual.py (considera lo ya ganado/
    retenido en el año, incluido el arrastre de otra empresa si el trabajador
    llegó por Traslado de Personal).
"""
import datetime
import types

from infrastructure.database.models import Prestamo, DepositoCTS, LiquidacionCese
from core.use_cases.calculo_beneficios_sociales import (
    calcular_gratificacion_trabajador, calcular_cts_trabajador,
    rango_cts, periodo_keys_rango, meses_con_servicio,
    dias_no_computables_cts, extras_computables_cts,
)
from core.use_cases.calculo_kardex import calcular_saldo_vacacional
from core.domain.exceptions import ReglaNegocioError


def rmv_vigente(db, empresa_id, fecha: datetime.date) -> float:
    """RMV vigente al mes de la fecha (o el último parámetro registrado antes).
    Falla de forma explícita en vez de usar una RMV fija desactualizada."""
    from infrastructure.repositories.repo_beneficios import cargar_parametro_vigente
    param = cargar_parametro_vigente(db, empresa_id, fecha.year, fecha.month)
    if not param or not param.rmv:
        raise ReglaNegocioError(
            f"No hay Parámetros Legales (RMV) registrados hasta {fecha.month:02d}-{fecha.year}. "
            "Regístrelos en el módulo Parámetros Legales antes de liquidar."
        )
    return float(param.rmv)


def _semestre_grati_de_fecha(fecha: datetime.date):
    """Semestre y año de gratificación al que pertenece la fecha de cese."""
    if fecha.month <= 6:
        return 'ENE-JUN', fecha.year
    return 'JUL-DIC', fecha.year


def _periodo_cts_de_fecha(fecha: datetime.date):
    """Periodo semestral de CTS (para el sexto de grati de referencia) y año de depósito
    al que pertenece la fecha de cese. NOV-ABR deposita en Mayo; MAY-OCT deposita en Nov."""
    if fecha.month <= 4:
        return 'NOV-ABR', fecha.year
    if fecha.month <= 10:
        return 'MAY-OCT', fecha.year
    return 'NOV-ABR', fecha.year + 1


def _obtener_grati_referencia_cts(db, trabajador, empresa_id, periodo_cts, anio_dep_cts,
                                   regimen_empresa, fecha_acogimiento, factor_override, rmv) -> dict:
    """
    Monto de gratificación que sirve de base para el "sexto" de la CTS: la
    gratificación ORDINARIA que cae DENTRO del semestre CTS que se está calculando
    (julio para MAY-OCT, diciembre para NOV-ABR) — NO la gratificación TRUNCA que
    esta misma liquidación calcula para el semestre siguiente (son dos beneficios
    distintos: uno ya pagado hace meses, el otro un adelanto nuevo por el cese).

    Mismo criterio que ya usa el módulo "Gratificaciones y CTS" para depósitos
    regulares (presentation/views/gratificaciones_cts.py):
      1. Buscar el monto REAL pagado, registrado en VariablesMes de ese periodo.
      2. Si no existe, estimar asumiendo el semestre completo (6/6 meses) — puede
         no coincidir con lo realmente pagado si hubo ajustes manuales.
    El monto final SIEMPRE puede sobreescribirse a mano en la vista si el usuario
    conoce el monto exacto y el sistema no lo tiene registrado.
    """
    import json as _json
    from infrastructure.database.models import VariablesMes
    from presentation.views.gratificaciones_cts import _grati_periodo_key, _semestre_grati, _anio_grati

    periodo_key_ref = _grati_periodo_key(periodo_cts, anio_dep_cts)

    v = db.query(VariablesMes).filter_by(
        empresa_id=empresa_id, trabajador_id=trabajador.id, periodo_key=periodo_key_ref,
    ).first()
    if v:
        try:
            cj = _json.loads(v.conceptos_json or '{}')
            monto_real = float(cj.get("GRATIFICACION (JUL/DIC)", 0.0))
        except Exception:
            monto_real = 0.0
        if monto_real > 0:
            return {'monto': monto_real, 'fuente': 'planilla', 'periodo_key_ref': periodo_key_ref}

    # Fallback: estimado asumiendo el semestre de referencia completo (6/6 meses),
    # con fecha_cese=None para no truncarlo por el cese actual (ese semestre ya
    # transcurrió por completo antes del cese).
    trabajador_sim_hist = types.SimpleNamespace(
        fecha_ingreso=trabajador.fecha_ingreso, fecha_cese=None,
        sueldo_base=trabajador.sueldo_base, asig_fam=trabajador.asig_fam,
        num_doc=trabajador.num_doc,
    )
    rg = calcular_gratificacion_trabajador(
        trabajador_sim_hist, _semestre_grati(periodo_cts), _anio_grati(periodo_cts, anio_dep_cts), rmv,
        regimen_empresa=regimen_empresa, fecha_acogimiento=fecha_acogimiento, factor_override=factor_override,
    )
    return {'monto': rg['monto_grati'], 'fuente': 'estimado', 'periodo_key_ref': periodo_key_ref}


def saldo_prestamos_pendientes(db, trabajador_id, empresa_id) -> float:
    """Suma de cuotas PENDIENTES de préstamos ACTIVOS de este trabajador en su empresa."""
    prestamos = db.query(Prestamo).filter_by(
        trabajador_id=trabajador_id, empresa_id=empresa_id, estado='ACTIVO'
    ).all()
    return sum(float(c.monto) for pr in prestamos for c in pr.cuotas if c.estado == 'PENDIENTE')


def ultimo_deposito_cts(db, trabajador_id, empresa_id):
    """Último depósito de CTS ya efectivamente DEPOSITADO (fuente real, no adivinada)."""
    return (
        db.query(DepositoCTS)
        .filter_by(trabajador_id=trabajador_id, empresa_id=empresa_id, estado='DEPOSITADO')
        .order_by(DepositoCTS.fecha_deposito.desc())
        .first()
    )


def _calcular_pension_sobre_monto(db, trabajador, empresa_id, fecha_cese, monto) -> dict:
    """
    AFP/ONP sobre un monto de la liquidación — SÍ aplica a vacaciones truncas y al
    sueldo proporcional del mes de cese (son remuneración computable para pensión),
    a diferencia de CTS (exonerada por ley) y gratificación (exonerada por Ley 30334,
    que además la excluyó de EsSalud/ONP y en su lugar creó el Bono Ext. 9%).

    Reutiliza el motor real de calculo_mensual.py para no duplicar las reglas de las
    4 AFP (aporte/prima/comisión, exención de prima por límite de edad).
    """
    if monto <= 0:
        return {'total_pension': 0.0, 'dscto_onp': 0.0, 'aporte_afp': 0.0, 'prima_afp': 0.0, 'comis_afp': 0.0}

    sistema = str(trabajador.sistema_pension or 'NO AFECTO').upper()
    if sistema in ('NO AFECTO', ''):
        return {'total_pension': 0.0, 'dscto_onp': 0.0, 'aporte_afp': 0.0, 'prima_afp': 0.0, 'comis_afp': 0.0}

    from presentation.views.calculo_mensual import _calcular_pension
    from infrastructure.repositories.repo_planilla import cargar_parametros

    periodo_key_cese = f"{fecha_cese.month:02d}-{fecha_cese.year}"
    p = cargar_parametros(db, empresa_id, periodo_key_cese)
    if not p:
        return {'total_pension': 0.0, 'dscto_onp': 0.0, 'aporte_afp': 0.0, 'prima_afp': 0.0, 'comis_afp': 0.0}

    row_shim = {'Comisión AFP': trabajador.comision_afp or 'FLUJO', 'Fecha Nacimiento': trabajador.fecha_nac}
    return _calcular_pension(
        sistema, monto, row_shim, p, fecha_cese.month, fecha_cese.year,
        desglose_descuentos={}, obs_trab=[],
    )


def _essalud_patronal_sobre_monto(db, trabajador, empresa_id, fecha_cese, monto) -> float:
    """
    EsSalud patronal sobre un monto de la liquidación — vacaciones truncas SÍ generan
    este aporte (código SUNAT 0114: afecto AFP/5ta/EsSalud), a diferencia de CTS y
    gratificación (exoneradas por Ley 30334). No afecta el neto del trabajador — es
    gasto/pasivo de la empresa, se usa solo para el Asiento Contable. No se aplica el
    piso de RMV aquí (ese piso protege la remuneración MENSUAL completa del trabajador,
    no un componente aislado de un evento de cese).
    """
    if monto <= 0:
        return 0.0

    from infrastructure.repositories.repo_planilla import cargar_parametros
    periodo_key_cese = f"{fecha_cese.month:02d}-{fecha_cese.year}"
    p = cargar_parametros(db, empresa_id, periodo_key_cese)
    if not p:
        return 0.0

    tasa = p['tasa_eps'] if getattr(trabajador, 'eps', False) else p['tasa_essalud']
    return round(monto * (tasa / 100), 2)


def _retencion_5ta_liquidacion(db, trabajador, empresa_id, fecha_cese, monto_gravado) -> dict:
    """
    Retención de 5ta sobre la porción gravada de la liquidación — vacaciones truncas
    (código SUNAT 0114) TAMBIÉN están afectas a 5ta, junto con grati trunca + bono 9%.
    CTS y Bono por Cese (código 0906) son inafectos, no se incluyen aquí. Se calcula en
    UNA sola llamada sobre el monto COMBINADO (no una por cada concepto), porque la
    retención de 5ta es progresiva sobre el ingreso total del periodo, no por concepto
    por separado. Reutiliza el motor real de proyección anual de calculo_mensual.py —
    considera lo ya ganado/retenido este año (incluido el arrastre de otra empresa si
    el trabajador vino por Traslado).

    A diferencia de un mes regular, aquí se retiene el 100% del impuesto incremental (no
    se divide entre meses futuros): no quedan más periodos con este empleador porque el
    trabajador está cesando.
    """
    if monto_gravado <= 0:
        return {'retencion': 0.0, 'aviso': None}

    from presentation.views.calculo_mensual import _calcular_quinta, _cargar_contexto_calculo
    from infrastructure.repositories.repo_planilla import cargar_parametros

    mes_cese = fecha_cese.month
    anio_cese = fecha_cese.year
    periodo_key_cese = f"{mes_cese:02d}-{anio_cese}"

    p = cargar_parametros(db, empresa_id, periodo_key_cese)
    if not p:
        return {
            'retencion': 0.0,
            'aviso': (f"Sin Parámetros Legales configurados para {periodo_key_cese} — "
                      f"la retención de 5ta no se pudo calcular con precisión."),
        }

    contexto = _cargar_contexto_calculo(empresa_id, periodo_key_cese, mes_cese, anio_cese)

    qta = _calcular_quinta(
        base_quinta_mes=monto_gravado, mes_idx=mes_cese, anio_calc=anio_cese, mes_calc=mes_cese, p=p,
        historico_quinta=contexto['historico_quinta'], dni_trabajador=trabajador.num_doc,
        sueldo_base_nominal=0.0, sueldo_computable=0.0, conceptos_recuperados_5ta=0.0,
        total_ausencias=0, ingreso_este_mes=False, factor_g=contexto['factor_g'],
        monto_no_recurrente_5ta=monto_gravado,
    )
    retencion = max(0.0, round(qta['impuesto_anual'] - qta['retencion_previa_historica'], 0))
    return {'retencion': float(retencion), 'aviso': None, 'detalle': qta}


def calcular_liquidacion(db, trabajador, empresa_id, fecha_cese, regimen_empresa,
                          fecha_acogimiento=None, factor_override=None,
                          incluye_sueldo_mes_cese=False, monto_bono_cese=0.0,
                          grati_referencia_cts=None) -> dict:
    """
    Calcula la Liquidación de Beneficios Sociales completa de un trabajador.

    `fecha_cese` es la fecha que se está evaluando — NO requiere que el trabajador ya
    esté marcado CESADO en el Maestro de Personal (se simula sobre una copia en memoria,
    para poder calcular ANTES de actualizar el registro real).

    `grati_referencia_cts`: monto de la gratificación ordinaria (no la trunca) que se
    usa para el "sexto" de la CTS — si se omite (None), se autodetecta/estima con
    `_obtener_grati_referencia_cts()`. Pásalo explícito cuando la vista ya mostró el
    monto detectado/estimado al usuario y este lo confirmó o corrigió a mano.
    """
    # Objeto simulado (no persistido, no es el ORM real) con la fecha_cese que se está
    # evaluando — así los motores de Grati/CTS/Vacaciones truncan correctamente los meses
    # aunque el registro real en Maestro de Personal todavía diga ACTIVO. Se usa un objeto
    # aparte (no una copia del ORM) para no arriesgar el estado interno de SQLAlchemy.
    trabajador_sim = types.SimpleNamespace(
        fecha_ingreso=trabajador.fecha_ingreso,
        fecha_cese=fecha_cese,
        sueldo_base=trabajador.sueldo_base,
        asig_fam=trabajador.asig_fam,
        num_doc=trabajador.num_doc,
        dias_vacaciones_anuales=getattr(trabajador, 'dias_vacaciones_anuales', 30),
    )

    sueldo_base = float(trabajador.sueldo_base)

    rmv = rmv_vigente(db, empresa_id, fecha_cese)

    # 1. Sueldo proporcional del mes de cese — apagado por defecto: la planilla regular
    # de ese mes ya lo paga prorrateado. Solo se activa si la empresa NO corre planilla
    # regular para el mes de cese (evita el riesgo de pago duplicado).
    monto_sueldo_prop = 0.0
    dias_laborados_cese = fecha_cese.day
    if incluye_sueldo_mes_cese:
        valor_dia = sueldo_base / 30.0
        monto_sueldo_prop = round(valor_dia * dias_laborados_cese, 2)

    # 2. Vacaciones truncas — saldo REAL del Kardex de Vacaciones
    saldo_vac = calcular_saldo_vacacional(trabajador_sim, trabajador.vacaciones, fecha_calculo=fecha_cese)
    dias_vac_pend = float(saldo_vac.get('saldo', 0.0) or 0.0)
    monto_vac_truncas = round((sueldo_base / 30.0) * dias_vac_pend, 2)

    # 3. Gratificación trunca — mismo motor que "Gratificaciones y CTS"
    semestre_grati, anio_grati = _semestre_grati_de_fecha(fecha_cese)
    res_grati = calcular_gratificacion_trabajador(
        trabajador_sim, semestre_grati, anio_grati, rmv,
        regimen_empresa=regimen_empresa, fecha_acogimiento=fecha_acogimiento,
        factor_override=factor_override,
    )
    monto_grati_trunca = res_grati['monto_grati']
    monto_bono_9 = res_grati['bono_9pct']

    # 4. CTS trunca — mismo motor que "Gratificaciones y CTS". El "sexto" usa la
    # gratificación ORDINARIA del semestre que cae dentro del periodo CTS (julio para
    # MAY-OCT, diciembre para NOV-ABR) — NO la gratificación trunca calculada arriba,
    # que es un beneficio distinto (adelanto del semestre siguiente, aún no vencido).
    periodo_cts, anio_dep_cts = _periodo_cts_de_fecha(fecha_cese)
    if grati_referencia_cts is not None:
        from presentation.views.gratificaciones_cts import _grati_periodo_key
        grati_ref = {'monto': float(grati_referencia_cts), 'fuente': 'manual',
                     'periodo_key_ref': _grati_periodo_key(periodo_cts, anio_dep_cts)}
    else:
        grati_ref = _obtener_grati_referencia_cts(
            db, trabajador, empresa_id, periodo_cts, anio_dep_cts,
            regimen_empresa, fecha_acogimiento, factor_override, rmv,
        )
    # Faltas/suspensiones no computables y conceptos "Computable CTS" del tramo
    # del semestre transcurrido hasta el cese (mismo criterio que el depósito regular).
    from infrastructure.repositories.repo_beneficios import (
        cargar_variables_rango, nombres_conceptos_computables_cts,
    )
    inicio_cts, fin_cts = rango_cts(periodo_cts, anio_dep_cts)
    fin_tramo = min(fin_cts, fecha_cese)
    v_sem = cargar_variables_rango(
        db, empresa_id, periodo_keys_rango(inicio_cts, fin_tramo), trabajador_id=trabajador.id,
    ).get(trabajador.id, [])
    extras_cts = extras_computables_cts(
        v_sem, nombres_conceptos_computables_cts(db, empresa_id),
        meses_con_servicio(trabajador.fecha_ingreso, fecha_cese, inicio_cts, fin_cts),
    )
    res_cts = calcular_cts_trabajador(
        trabajador_sim, periodo_cts, anio_dep_cts, rmv,
        grati_semestral=grati_ref['monto'],
        regimen_empresa=regimen_empresa, fecha_acogimiento=fecha_acogimiento,
        extras_computables=extras_cts['total'],
        dias_no_computables=dias_no_computables_cts(v_sem),
    )
    monto_cts_trunca = res_cts['monto_cts']

    dep_cts_real = ultimo_deposito_cts(db, trabajador.id, empresa_id)
    fecha_ultimo_cts = dep_cts_real.fecha_deposito if dep_cts_real else None

    # 5. Préstamos pendientes — se descuentan, no se ignoran
    saldo_prestamos = saldo_prestamos_pendientes(db, trabajador.id, empresa_id)

    # 6. Retención de 5ta sobre la porción gravada — vacaciones truncas (código SUNAT
    # 0114) TAMBIÉN están afectas, junto con grati trunca + bono 9%. CTS y Bono por
    # Cese (código 0906) son inafectos. Un solo cálculo sobre el monto combinado.
    monto_gravado_5ta = monto_vac_truncas + monto_grati_trunca + monto_bono_9
    res_5ta = _retencion_5ta_liquidacion(db, trabajador, empresa_id, fecha_cese, monto_gravado_5ta)
    monto_retencion_5ta = res_5ta['retencion']

    # 7. AFP/ONP sobre vacaciones truncas (y sueldo proporcional, si se incluyó) — SÍ
    # son remuneración computable para pensión, a diferencia de CTS y gratificación.
    pen_vac = _calcular_pension_sobre_monto(db, trabajador, empresa_id, fecha_cese, monto_vac_truncas)
    pen_sueldo = _calcular_pension_sobre_monto(db, trabajador, empresa_id, fecha_cese, monto_sueldo_prop)
    monto_pension_afp_onp = round(pen_vac['total_pension'] + pen_sueldo['total_pension'], 2)
    # Desglose de la tríada AFP — el PLAME (.rem) declara aporte/prima/comisión por
    # separado (códigos 0608/0606/0601), no como un solo total. Queda en 0 en ONP.
    monto_aporte_afp = round(pen_vac['aporte_afp'] + pen_sueldo['aporte_afp'], 2)
    monto_prima_afp = round(pen_vac['prima_afp'] + pen_sueldo['prima_afp'], 2)
    monto_comision_afp = round(pen_vac['comis_afp'] + pen_sueldo['comis_afp'], 2)

    # 8. EsSalud patronal sobre vacaciones truncas (código SUNAT 0114) — no afecta el
    # neto del trabajador, es gasto/pasivo de la empresa (para el Asiento Contable).
    monto_essalud_vacaciones = _essalud_patronal_sobre_monto(db, trabajador, empresa_id, fecha_cese, monto_vac_truncas)

    # 9. Bono/Incentivo por Cese (código SUNAT 0906) — monto libre pactado, totalmente
    # exento (no afecto AFP/ONP, 5ta, ni EsSalud) según el propio catálogo SUNAT.
    monto_bono_cese = round(float(monto_bono_cese or 0.0), 2)

    total_bruto = round(
        monto_sueldo_prop + monto_vac_truncas + monto_grati_trunca + monto_bono_9
        + monto_cts_trunca + monto_bono_cese, 2
    )
    total_neto = round(total_bruto - saldo_prestamos - monto_retencion_5ta - monto_pension_afp_onp, 2)

    return {
        'fecha_ingreso': trabajador.fecha_ingreso,
        'fecha_cese': fecha_cese,
        'sueldo_base': sueldo_base,
        'incluye_sueldo_mes_cese': incluye_sueldo_mes_cese,
        'monto_sueldo_proporcional': monto_sueldo_prop,
        'dias_laborados_mes_cese': dias_laborados_cese,
        'dias_vacaciones_pendientes': dias_vac_pend,
        'monto_vacaciones_truncas': monto_vac_truncas,
        'vac_devengados': saldo_vac.get('devengados', 0.0),
        'vac_consumidos': saldo_vac.get('consumidos', 0.0),
        'vac_meses_completos': saldo_vac.get('meses_servicio', 0),
        'vac_dias_sueltos': saldo_vac.get('dias_sueltos', 0.0),
        'periodo_grati_ref': f"{semestre_grati} {anio_grati}",
        'meses_grati': res_grati['meses_computados'],
        'monto_grati_trunca': monto_grati_trunca,
        'monto_bono_9': monto_bono_9,
        'grati_base_computable': res_grati['base_computable'],
        'grati_factor': res_grati['factor_grati'],
        'grati_fecha_efectivo_ini': res_grati['fecha_efectivo_ini'],
        'grati_fecha_efectivo_fin': res_grati['fecha_efectivo_fin'],
        'periodo_cts_ref': f"{periodo_cts} (dep. {anio_dep_cts})",
        'meses_cts': res_cts['meses_computados'],
        'base_cts': res_cts['base_cts'],
        'monto_cts_trunca': monto_cts_trunca,
        'cts_remuneracion_base': res_cts['remuneracion_base'],
        'cts_factor': res_cts['factor_cts'],
        'cts_dias_sueltos': res_cts['dias_sueltos'],
        'cts_fecha_efectivo_ini': res_cts['fecha_efectivo_ini'],
        'cts_fecha_efectivo_fin': res_cts['fecha_efectivo_fin'],
        'grati_referencia_cts': grati_ref['monto'],
        'grati_referencia_cts_fuente': grati_ref['fuente'],
        'grati_referencia_cts_periodo': grati_ref['periodo_key_ref'],
        'fecha_ultimo_deposito_cts': fecha_ultimo_cts,
        'monto_prestamos_pendientes': saldo_prestamos,
        'monto_retencion_5ta': monto_retencion_5ta,
        'sistema_pension': str(trabajador.sistema_pension or 'NO AFECTO').upper(),
        'monto_pension_afp_onp': monto_pension_afp_onp,
        'monto_aporte_afp': monto_aporte_afp,
        'monto_prima_afp': monto_prima_afp,
        'monto_comision_afp': monto_comision_afp,
        'monto_essalud_vacaciones': monto_essalud_vacaciones,
        'monto_bono_cese': monto_bono_cese,
        'aviso_5ta': res_5ta.get('aviso'),
        'total_bruto': total_bruto,
        'total_neto': total_neto,
        # Detalle para mostrar en pantalla (transparencia/auditoría)
        'detalle_grati': res_grati,
        'detalle_cts': res_cts,
        'detalle_vacaciones': saldo_vac,
        'detalle_pension_vacaciones': pen_vac,
        'detalle_pension_sueldo': pen_sueldo,
    }


def generar_liquidacion_borrador_automatica(
    db, trabajador, empresa_id, fecha_cese, regimen_empresa,
    fecha_acogimiento=None, factor_override=None, generado_por=None,
):
    """
    Calcula y persiste (db.add, SIN commit) una Liquidación por Cese en estado
    BORRADOR automáticamente, para no depender de que alguien recuerde entrar al
    módulo "Liquidación por Cese" a generarla a mano — se usa apenas un trabajador
    queda CESADO (por Traslado individual/masivo, o por cese directo en el Maestro
    de Personal). Usa los mismos valores por defecto que el formulario manual
    (sin sueldo proporcional del mes, sin bono de cese, grati de referencia para
    CTS autodetectada/estimada) — queda como punto de partida para que un
    Administrador/Supervisor la revise, ajuste si hace falta y apruebe.

    No genera nada para locadores (no tienen beneficios sociales) ni si ya existe
    una liquidación registrada para este trabajador con esta misma fecha_cese
    (evita duplicados si la operación se reintenta o revierte y rehace). El
    llamador es responsable de hacer commit — si el commit falla, la generación
    de esta liquidación NO debe impedir ni revertir la operación de cese/traslado
    que la originó.

    Retorna el objeto LiquidacionCese creado (aún no commiteado), o None si no
    aplica.
    """
    if getattr(trabajador, 'tipo_contrato', None) == 'LOCADOR':
        return None
    if not fecha_cese:
        return None

    ya_existe = db.query(LiquidacionCese).filter_by(
        trabajador_id=trabajador.id, empresa_id=empresa_id, fecha_cese_snapshot=fecha_cese,
    ).first()
    if ya_existe:
        return None

    liq = calcular_liquidacion(
        db, trabajador, empresa_id, fecha_cese, regimen_empresa,
        fecha_acogimiento=fecha_acogimiento, factor_override=factor_override,
    )

    nueva_liq = LiquidacionCese(
        empresa_id=empresa_id,
        trabajador_id=trabajador.id,
        generado_por=generado_por or "Sistema (automático)",
        fecha_ingreso_snapshot=liq['fecha_ingreso'],
        fecha_cese_snapshot=liq['fecha_cese'],
        sueldo_base_snapshot=liq['sueldo_base'],
        incluye_sueldo_mes_cese=liq['incluye_sueldo_mes_cese'],
        monto_sueldo_proporcional=liq['monto_sueldo_proporcional'],
        dias_laborados_mes_cese=liq['dias_laborados_mes_cese'],
        dias_vacaciones_pendientes=liq['dias_vacaciones_pendientes'],
        monto_vacaciones_truncas=liq['monto_vacaciones_truncas'],
        vac_devengados=liq['vac_devengados'],
        vac_consumidos=liq['vac_consumidos'],
        vac_meses_completos=liq['vac_meses_completos'],
        vac_dias_sueltos=liq['vac_dias_sueltos'],
        periodo_grati_ref=liq['periodo_grati_ref'],
        meses_grati=liq['meses_grati'],
        monto_grati_trunca=liq['monto_grati_trunca'],
        monto_bono_9=liq['monto_bono_9'],
        grati_base_computable=liq['grati_base_computable'],
        grati_factor=liq['grati_factor'],
        grati_fecha_efectivo_ini=liq['grati_fecha_efectivo_ini'],
        grati_fecha_efectivo_fin=liq['grati_fecha_efectivo_fin'],
        periodo_cts_ref=liq['periodo_cts_ref'],
        meses_cts=liq['meses_cts'],
        base_cts=liq['base_cts'],
        monto_cts_trunca=liq['monto_cts_trunca'],
        cts_remuneracion_base=liq['cts_remuneracion_base'],
        cts_factor=liq['cts_factor'],
        cts_dias_sueltos=liq['cts_dias_sueltos'],
        cts_fecha_efectivo_ini=liq['cts_fecha_efectivo_ini'],
        cts_fecha_efectivo_fin=liq['cts_fecha_efectivo_fin'],
        fecha_ultimo_deposito_cts=liq['fecha_ultimo_deposito_cts'],
        grati_referencia_cts=liq['grati_referencia_cts'],
        grati_referencia_cts_fuente=liq['grati_referencia_cts_fuente'],
        grati_referencia_cts_periodo=liq['grati_referencia_cts_periodo'],
        monto_prestamos_pendientes=liq['monto_prestamos_pendientes'],
        monto_retencion_5ta=liq['monto_retencion_5ta'],
        sistema_pension_snapshot=liq['sistema_pension'],
        monto_pension_afp_onp=liq['monto_pension_afp_onp'],
        monto_aporte_afp=liq['monto_aporte_afp'],
        monto_prima_afp=liq['monto_prima_afp'],
        monto_comision_afp=liq['monto_comision_afp'],
        monto_essalud_vacaciones=liq['monto_essalud_vacaciones'],
        monto_bono_cese=liq['monto_bono_cese'],
        total_bruto=liq['total_bruto'],
        total_neto=liq['total_neto'],
        estado='BORRADOR',
    )
    db.add(nueva_liq)
    return nueva_liq
