import json
import calendar
import streamlit as st
import pandas as pd
import io
from datetime import datetime



# Base de Datos Neon
from sqlalchemy import or_
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Trabajador, Concepto, ParametroLegal, VariablesMes, PlanillaMensual, Prestamo, CuotaPrestamo, Empresa as EmpresaModel
from core.use_cases.calculo_honorarios import calcular_recibo_honorarios
from core.use_cases.generador_reportes_calculo import (
    generar_excel_sabana, generar_pdf_sabana, generar_pdf_quinta,
    generar_excel_honorarios, generar_pdf_honorarios,
    generar_pdf_combinado, generar_pdf_tesoreria, generar_pdf_personalizado,
    _periodo_legible_calc,
)


# ─── HELPERS DE BASE DE DATOS (ver infrastructure/repositories/repo_planilla.py) ─
from infrastructure.repositories.repo_planilla import (
    cargar_parametros, cargar_trabajadores_df, cargar_variables_df,
    cargar_conceptos_df, guardar_planilla, cargar_planilla_guardada,
)

MESES = ["01 - Enero", "02 - Febrero", "03 - Marzo", "04 - Abril", "05 - Mayo", "06 - Junio", 
         "07 - Julio", "08 - Agosto", "09 - Septiembre", "10 - Octubre", "11 - Noviembre", "12 - Diciembre"]


# --- 2. MOTOR DE RENDERIZADO Y CÁLCULO ---



def _cargar_contexto_calculo(empresa_id, periodo_key, mes_idx, anio_seleccionado) -> dict:
    """Carga el contexto auxiliar (histórico 5ta, cuotas, factor_g, notas) para el motor de planilla."""
    # Cargar historial de quinta categoría de periodos anteriores del mismo año
    historico_quinta: dict = {}
    try:
        db_hq = SessionLocal()
        for mes_ant in range(1, mes_idx):
            periodo_ant = f"{mes_ant:02d}-{anio_seleccionado}"
            plan_ant = db_hq.query(PlanillaMensual).filter_by(
                empresa_id=empresa_id, periodo_key=periodo_ant
            ).first()
            if plan_ant:
                try:
                    aud_ant = json.loads(plan_ant.auditoria_json or '{}')
                    for dni_ant, data_ant in aud_ant.items():
                        q_ant = data_ant.get('quinta', {})
                        b = float(q_ant.get('base_mes', 0.0))
                        r = float(q_ant.get('retencion', 0.0))
                        if b > 0 or r > 0:
                            if dni_ant not in historico_quinta:
                                historico_quinta[dni_ant] = {'rem_previa': 0.0, 'ret_previa': 0.0}
                            historico_quinta[dni_ant]['rem_previa'] += b
                            historico_quinta[dni_ant]['ret_previa'] += r
                except Exception:
                    pass
        db_hq.close()
    except Exception:
        pass

    # Precargar cuotas de préstamos pendientes del periodo (una sola consulta)
    cuotas_del_mes: dict = {}
    try:
        db_cuotas = SessionLocal()
        _cuotas = (
            db_cuotas.query(CuotaPrestamo)
            .join(Prestamo)
            .filter(
                Prestamo.empresa_id == empresa_id,
                CuotaPrestamo.periodo_key == periodo_key,
                CuotaPrestamo.estado == 'PENDIENTE',
            )
            .all()
        )
        for _c in _cuotas:
            _dni_c = _c.prestamo.trabajador.num_doc
            cuotas_del_mes.setdefault(_dni_c, []).append({
                'id':            _c.id,
                'numero_cuota':  _c.numero_cuota,
                'numero_cuotas': _c.prestamo.numero_cuotas,
                'concepto':      _c.prestamo.concepto,
                'monto':         float(_c.monto),
            })
        db_cuotas.close()
    except Exception:
        cuotas_del_mes = {}

    # --- Determinar factor de gratificación general para la empresa ---
    regimen_empresa_motor = st.session_state.get('empresa_activa_regimen', 'Régimen General')
    factor_g_manual = st.session_state.get('empresa_factor_grati', None)

    if factor_g_manual is not None:
        factor_g = float(factor_g_manual)
    else:
        if "Micro Empresa" in regimen_empresa_motor:
            factor_g = 0.0
        elif "Pequeña Empresa" in regimen_empresa_motor:
            factor_g = 0.5
        else:
            factor_g = 1.0

    # Precargar notas de gestión manuales
    notas_gestion_map = {}
    try:
        db_n = SessionLocal()
        _v_notas = db_n.query(VariablesMes).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).all()
        for _vn in _v_notas:
            notas_gestion_map[_vn.trabajador.num_doc] = getattr(_vn, 'notas_gestion', '') or ''
        db_n.close()
    except: pass
    return {
        'historico_quinta':  historico_quinta,
        'cuotas_del_mes':    cuotas_del_mes,
        'factor_g':          factor_g,
        'notas_gestion_map': notas_gestion_map,
    }



def _calcular_haberes(
    row, p, horas_jornada, mes_calc, anio_calc,
    dni_trabajador, cuotas_del_mes, notas_gestion_map, conceptos_empresa,
) -> dict | None:
    """
    Calcula proporcionalidad, sueldos, asig. familiar, horas extras, cuotas y conceptos
    dinámicos. Retorna dict con bases y desgloses, o None si el trabajador no computa.
    """
    # --- TIEMPOS Y BASES FIJAS (Proporcionalidad Segura) ---
    try:
        fecha_ingreso = pd.to_datetime(row['Fecha Ingreso'])

        dias_del_mes = calendar.monthrange(anio_calc, mes_calc)[1]
        ingreso_este_mes = (fecha_ingreso.year == anio_calc and fecha_ingreso.month == mes_calc)
        dias_computables = dias_del_mes
        if ingreso_este_mes:
            dias_computables = max(0, dias_del_mes - fecha_ingreso.day + 1)
        elif fecha_ingreso.year > anio_calc or (fecha_ingreso.year == anio_calc and fecha_ingreso.month > mes_calc):
            dias_computables = 0
    except Exception:
        dias_del_mes = 30
        dias_computables = 30
        ingreso_este_mes = False

    # Trabajador aún no ingresa en este periodo — omitir completamente
    if dias_computables == 0:
        return None

    # Suspensiones desde suspensiones_json; fallback a Días Faltados
    susp_raw = str(row.get('suspensiones_json', '{}') or '{}')
    try:
        susp_dict = json.loads(susp_raw)
    except Exception:
        susp_dict = {}
    total_ausencias   = sum(susp_dict.values()) if susp_dict else float(row.get('Días Faltados', 0))
    dias_laborados    = max(0, int(dias_computables) - int(total_ausencias))
    horas_ordinarias  = int(dias_laborados * horas_jornada)

    sueldo_base_nominal = float(row['Sueldo Base'])
    valor_dia           = sueldo_base_nominal / 30.0   # Base 30 — Mes Comercial Mixto
    valor_hora          = valor_dia / horas_jornada

    # Corrección Mes Comercial (Base 30 estricta para cálculo financiero):
    if ingreso_este_mes and dias_computables < dias_del_mes:
        # Si el trabajador ingresó a mediados de mes: se le pagan los días calendario laborados
        dias_laborados = max(0, int(dias_computables) - int(total_ausencias))
        sueldo_computable = max(0.0, valor_dia * dias_laborados)
        factor_asistencia = dias_laborados / 30.0
    else:
        # Trabajador regular (mes completo): Sueldo base nominal menos sus días exactos de inasistencia (Base 30)
        dias_laborados = max(0, 30 - int(total_ausencias))
        sueldo_computable = max(0.0, sueldo_base_nominal - (int(total_ausencias) * valor_dia))
        factor_asistencia = dias_laborados / 30.0

    # --- OBSERVACIONES DEL PERIODO ---
    obs_trab = []
    if ingreso_este_mes:
        obs_trab.append(f"Ingresó el {fecha_ingreso.strftime('%d/%m/%Y')}")

    # Detalle de descuentos por ausencias para Tesorería
    monto_dscto_ausencias = round(sueldo_base_nominal - sueldo_computable, 2)
    if total_ausencias > 0:
        obs_trab.append(f"Días no laborados: {int(total_ausencias)} (Desc: S/ {monto_dscto_ausencias:,.2f})")

    dscto_tardanzas = float(row['Min. Tardanza']) * (valor_hora / 60)
    if dscto_tardanzas > 0:
        obs_trab.append(f"Tardanzas: {int(row['Min. Tardanza'])} min (Desc: S/ {dscto_tardanzas:,.2f})")

    # Integrar Nota de Gestión Manual
    nota_manual = notas_gestion_map.get(str(dni_trabajador), "")
    if nota_manual:
        obs_trab.append(f"NOTA: {nota_manual}")

    # Asig. familiar: se paga solo si hay sueldo computable > 0 y al menos 1 día remunerado.
    # Códigos remunerados (no descuentan asig.fam): 20=Desc.Médico, 23=Vacaciones, 25=Lic.c/Goce
    _COD_REM = {"20", "23", "25"}
    dias_remunerados = dias_laborados + sum(int(susp_dict.get(c, 0)) for c in _COD_REM)
    tiene_asig_fam = (row.get('Asig. Fam.', "No") == "Sí"
                      and sueldo_computable > 0
                      and dias_remunerados > 0)
    monto_asig_fam = (p['rmv'] * 0.10) if tiene_asig_fam else 0.0

    pago_he_25 = float(row.get('Hrs Extras 25%', 0.0)) * (valor_hora * 1.25)
    pago_he_35 = float(row.get('Hrs Extras 35%', 0.0)) * (valor_hora * 1.35)

    ingresos_totales    = sueldo_computable + monto_asig_fam + pago_he_25 + pago_he_35
    # Solo tardanzas como descuento manual; las faltas ya reducen sueldo_computable
    descuentos_manuales = dscto_tardanzas
    desglose_descuentos = {}
    if dscto_tardanzas > 0:
        desglose_descuentos["Tardanzas"] = round(dscto_tardanzas, 2)

    # ── CUOTAS DE PRÉSTAMOS/DESCUENTOS PROGRAMADOS ──────────────────
    # IMPORTANTE: Estos montos NO afectan bases de AFP, 5ta o EsSalud.
    # Solo se restan al final para llegar al NETO A PAGAR.
    for _cuota in cuotas_del_mes.get(str(dni_trabajador), []):
        _monto_c = _cuota['monto']
        descuentos_manuales += _monto_c
        _concepto_c = _cuota['concepto']
        desglose_descuentos[_concepto_c] = desglose_descuentos.get(_concepto_c, 0.0) + _monto_c
        obs_trab.append(
            f"{_concepto_c}: Cuota {_cuota['numero_cuota']}/{_cuota['numero_cuotas']}"
            f" (S/ {_monto_c:,.2f})"
        )

    # ── OBSERVACIONES ADICIONALES ────────────────────────────────────
    # Verificación bancaria
    if not str(row.get('Banco', '') or '').strip() or not str(row.get('Cuenta Bancaria', '') or '').strip():
        obs_trab.append("⚠️ Sin cuenta bancaria (Pago manual)")
    # Descanso médico (código 20) o accidente de trabajo (código 16)
    for _cod, _desc in [("20", "Descanso médico"), ("16", "Accidente de trabajo")]:
        if int(susp_dict.get(_cod, 0)) > 0:
            obs_trab.append(f"{_desc}: {int(susp_dict[_cod])} día(s)")

    # Las bases imponibles se calculan ANTES de aplicar descuentos de préstamos
    base_afp_onp        = ingresos_totales
    base_essalud        = ingresos_totales
    base_quinta_mes     = ingresos_totales

    desglose_ingresos = {
        f"Sueldo Base ({int(dias_laborados)} días)": round(sueldo_computable, 2),
        "Asignación Familiar": round(monto_asig_fam, 2),
    }
    if pago_he_25 > 0:
        desglose_ingresos["Horas Extras 25%"] = round(pago_he_25, 2)
    if pago_he_35 > 0:
        desglose_ingresos["Horas Extras 35%"] = round(pago_he_35, 2)

    # --- CONCEPTOS DINÁMICOS Y GRATIFICACIONES ---
    monto_grati = float(row.get('GRATIFICACION (JUL/DIC)', 0.0))
    if monto_grati > 0:
        monto_bono_9 = monto_grati * 0.09
        desglose_ingresos['Gratificación'] = round(monto_grati, 2)
        desglose_ingresos['Bono Ext. 9%'] = round(monto_bono_9, 2)
        ingresos_totales += (monto_grati + monto_bono_9)
        base_quinta_mes += (monto_grati + monto_bono_9)

    conceptos_omitidos = ["SUELDO BASICO", "ASIGNACION FAMILIAR", "GRATIFICACION (JUL/DIC)", "BONIFICACION EXTRAORDINARIA LEY 29351 (9%)"]
    otros_ingresos = 0.0
    conceptos_recuperados_5ta = 0.0
    for _, concepto in conceptos_empresa.iterrows():
        nombre_c = concepto['Nombre del Concepto']
        if nombre_c in conceptos_omitidos: continue
        if nombre_c in row and float(row[nombre_c]) > 0:
            monto_ingresado_nominal = float(row[nombre_c])
            if concepto.get('Prorrateable', False):
                monto_concepto = monto_ingresado_nominal * factor_asistencia
                # Si es un ingreso afecto a 5ta, guardamos el diferencial que se perdió por faltar
                if concepto['Tipo'] == "INGRESO" and concepto.get('Afecto 5ta Cat.', False):
                    conceptos_recuperados_5ta += (monto_ingresado_nominal - monto_concepto)
            else:
                monto_concepto = monto_ingresado_nominal

            if concepto['Tipo'] == "INGRESO":
                desglose_ingresos[nombre_c] = round(monto_concepto, 2)
                otros_ingresos += monto_concepto
                ingresos_totales += monto_concepto
                if concepto['Afecto AFP/ONP']: base_afp_onp += monto_concepto
                if concepto['Afecto EsSalud']: base_essalud += monto_concepto
                if concepto['Afecto 5ta Cat.']: base_quinta_mes += monto_concepto
            elif concepto['Tipo'] == "DESCUENTO":
                desglose_descuentos[nombre_c] = round(monto_concepto, 2)
                descuentos_manuales += monto_concepto
                if concepto['Afecto AFP/ONP']: base_afp_onp -= monto_concepto
                if concepto['Afecto EsSalud']: base_essalud -= monto_concepto
                if concepto['Afecto 5ta Cat.']: base_quinta_mes -= monto_concepto

    base_afp_onp = max(0.0, base_afp_onp)
    base_essalud = max(0.0, base_essalud)
    base_quinta_mes = max(0.0, base_quinta_mes)

    return {
        'dias_laborados':       dias_laborados,
        'dias_computables':     dias_computables,
        'dias_remunerados':     dias_remunerados,
        'horas_ordinarias':     horas_ordinarias,
        'susp_dict':            susp_dict,
        'sueldo_computable':    sueldo_computable,
        'sueldo_base_nominal':  sueldo_base_nominal,
        'monto_asig_fam':       monto_asig_fam,
        'pago_he_25':           pago_he_25,
        'pago_he_35':           pago_he_35,
        'monto_grati':          monto_grati,
        'otros_ingresos':       otros_ingresos,
        'ingreso_este_mes':     ingreso_este_mes,
        'total_ausencias':      total_ausencias,
        'ingresos_totales':     ingresos_totales,
        'descuentos_manuales':  descuentos_manuales,
        'base_afp_onp':         base_afp_onp,
        'base_essalud':         base_essalud,
        'base_quinta_mes':      base_quinta_mes,
        'conceptos_recuperados_5ta': conceptos_recuperados_5ta,
        'desglose_ingresos':    desglose_ingresos,
        'desglose_descuentos':  desglose_descuentos,
        'obs_trab':             obs_trab,
    }


def _calcular_pension(
    sistema, base_afp_onp, row, p, mes_calc, anio_calc,
    desglose_descuentos, obs_trab,
) -> dict:
    """
    Calcula aportes AFP (aporte, prima, comisión) o descuento ONP.
    Modifica desglose_descuentos y obs_trab in-place con las entradas de pensión.
    Retorna dict con los montos individuales.
    """
    aporte_afp = 0.0
    prima_afp = 0.0
    comis_afp = 0.0
    dscto_onp = 0.0

    if sistema == "ONP":
        dscto_onp = base_afp_onp * (p['tasa_onp'] / 100)
        if dscto_onp > 0: desglose_descuentos['Aporte ONP'] = round(dscto_onp, 2)
    elif sistema != "NO AFECTO":
        prefijo = ""
        if "HABITAT" in sistema: prefijo = "afp_habitat_"
        elif "INTEGRA" in sistema: prefijo = "afp_integra_"
        elif "PRIMA" in sistema: prefijo = "afp_prima_"
        elif "PROFUTURO" in sistema: prefijo = "afp_profuturo_"

        if prefijo:
            tasa_aporte = p[prefijo + "aporte"] / 100
            tasa_prima = p[prefijo + "prima"] / 100
            tasa_comision = p[prefijo + "mixta"]/100 if row['Comisión AFP'] == "MIXTA" else p[prefijo + "flujo"]/100

            aporte_afp = base_afp_onp * tasa_aporte

            # Exención de Prima de Seguro AFP por límite de edad
            aplica_prima = True
            fecha_nac_str = row.get('Fecha Nacimiento')
            if pd.notna(fecha_nac_str):
                try:
                    f_nac = pd.to_datetime(fecha_nac_str)
                    edad = anio_calc - f_nac.year - ((mes_calc, 1) < (f_nac.month, f_nac.day))
                    if edad >= p['edad_maxima_prima_afp']:
                        aplica_prima = False
                except: pass

            if aplica_prima:
                prima_afp = min(base_afp_onp, p['tope_afp']) * tasa_prima
            else:
                prima_afp = 0.0
                obs_trab.append(f"Prima AFP exonerada (Edad límite superada)")

            comis_afp = base_afp_onp * tasa_comision
            total_afp_ind = aporte_afp + prima_afp + comis_afp
            if total_afp_ind > 0: desglose_descuentos[f'Aporte {sistema}'] = round(total_afp_ind, 2)

    total_pension = dscto_onp + aporte_afp + prima_afp + comis_afp
    return {
        'total_pension': total_pension,
        'dscto_onp':     dscto_onp,
        'aporte_afp':    aporte_afp,
        'prima_afp':     prima_afp,
        'comis_afp':     comis_afp,
    }


def _calcular_quinta(
    base_quinta_mes, mes_idx, anio_calc, mes_calc, p,
    historico_quinta, dni_trabajador,
    sueldo_base_nominal, sueldo_computable, conceptos_recuperados_5ta,
    total_ausencias, ingreso_este_mes, factor_g,
) -> dict:
    """
    Calcula la retención de 5ta categoría con proyección anual (método PLAME).
    Retorna dict con la retención y datos de auditoría.
    """
    uit = p['uit']
    meses_restantes = 12 - mes_idx
    hist_q = historico_quinta.get(str(dni_trabajador), {})
    rem_previa_historica = hist_q.get('rem_previa', 0.0)
    retencion_previa_historica = hist_q.get('ret_previa', 0.0)
    # Proyección usa sueldo nominal completo: las ausencias son excepcionales
    base_quinta_proyeccion = base_quinta_mes
    if total_ausencias > 0 or ingreso_este_mes:
        base_quinta_proyeccion = round(base_quinta_mes + (sueldo_base_nominal - sueldo_computable) + conceptos_recuperados_5ta, 2)
    proyeccion_gratis = 0.0
    if mes_idx <= 6:
        proyeccion_gratis = base_quinta_proyeccion * 2 * factor_g * 1.09
    elif mes_idx <= 11:
        proyeccion_gratis = base_quinta_proyeccion * 1 * factor_g * 1.09
    proyeccion_sueldos_restantes = base_quinta_proyeccion * meses_restantes

    renta_bruta_anual = int(round(rem_previa_historica + base_quinta_mes + proyeccion_sueldos_restantes + proyeccion_gratis))
    renta_neta_anual = int(round(renta_bruta_anual - (7 * uit)))

    impuesto_anual = 0.0
    retencion_quinta = 0.0
    detalle_tramos = []
    divisor = 1
    if mes_idx in [1, 2, 3]: divisor = 12
    elif mes_idx == 4: divisor = 9
    elif mes_idx in [5, 6, 7]: divisor = 8
    elif mes_idx == 8: divisor = 5
    elif mes_idx in [9, 10, 11]: divisor = 4

    if renta_neta_anual > 0:
        renta_restante = renta_neta_anual
        tramos = [(5 * uit, 0.08), (15 * uit, 0.14), (15 * uit, 0.17), (10 * uit, 0.20), (float('inf'), 0.30)]
        for limite, tasa in tramos:
            if renta_restante > 0:
                monto_tramo = min(renta_restante, limite)
                imp_tramo = monto_tramo * tasa
                impuesto_anual += imp_tramo
                detalle_tramos.append({"rango": f"Hasta {limite/uit} UIT", "tasa": f"{int(tasa*100)}%", "base": monto_tramo, "impuesto": imp_tramo})
                renta_restante -= monto_tramo
        retencion_quinta = float(int(round(max(0.0, (impuesto_anual - retencion_previa_historica) / divisor))))

    return {
        'retencion_quinta':           retencion_quinta,
        'impuesto_anual':             impuesto_anual,
        'detalle_tramos':             detalle_tramos,
        'renta_bruta_anual':          renta_bruta_anual,
        'renta_neta_anual':           renta_neta_anual,
        'divisor':                    divisor,
        'rem_previa_historica':       rem_previa_historica,
        'retencion_previa_historica': retencion_previa_historica,
        'meses_restantes':            meses_restantes,
        'proy_sueldo':               proyeccion_sueldos_restantes,
        'proy_grati':                proyeccion_gratis,
    }


def _calcular_fila_trabajador(row, p, horas_jornada, mes_calc, anio_calc, mes_idx, periodo_key,
                              historico_quinta, cuotas_del_mes, notas_gestion_map,
                              conceptos_empresa, factor_g):
    """Calcula los campos de planilla para un trabajador. Retorna (fila_dict, auditoria_dict) o None."""
    # Filtro de fecha de ingreso y cese para personal en planilla
    try:
        fi_p = pd.to_datetime(row['Fecha Ingreso'])
        if fi_p.year > anio_calc or (fi_p.year == anio_calc and fi_p.month > mes_calc):
            return None
        
        # Si tiene fecha de cese y es anterior al mes de cálculo, omitir
        if 'fecha_cese' in row and pd.notna(row['fecha_cese']):
            fc_p = pd.to_datetime(row['fecha_cese'])
            if fc_p.year < anio_calc or (fc_p.year == anio_calc and fc_p.month < mes_calc):
                return None
    except: pass

    dni_trabajador = row['Num. Doc.']
    nombres = row['Nombres y Apellidos_x']
    sistema = str(row.get('Sistema Pensión', 'NO AFECTO')).upper()

    # ── BASES Y HABERES ──────────────────────────────────────────────────────
    h = _calcular_haberes(
        row, p, horas_jornada, mes_calc, anio_calc,
        dni_trabajador, cuotas_del_mes, notas_gestion_map, conceptos_empresa,
    )
    if h is None:
        return None

    # ── PENSIONES ───────────────────────────────────────────────────────────
    pen = _calcular_pension(
        sistema, h['base_afp_onp'], row, p, mes_calc, anio_calc,
        h['desglose_descuentos'], h['obs_trab'],
    )

    # ── 5TA CATEGORÍA ────────────────────────────────────────────────────────
    qta = _calcular_quinta(
        h['base_quinta_mes'], mes_idx, anio_calc, mes_calc, p,
        historico_quinta, dni_trabajador,
        h['sueldo_base_nominal'], h['sueldo_computable'], h['conceptos_recuperados_5ta'],
        h['total_ausencias'], h['ingreso_este_mes'], factor_g,
    )

    # Desempaquetar variables mutables (se modifican en ajustes de auditoría)
    desglose_descuentos = h['desglose_descuentos']
    obs_trab            = h['obs_trab']
    retencion_quinta    = qta['retencion_quinta']
    descuentos_manuales = h['descuentos_manuales']

    # --- APLICACIÓN DE AJUSTES DE AUDITORÍA (MANUALES) ---
    conceptos_manuales = {}
    try:
        _cj_raw = row.get('conceptos_json', '{}')
        if isinstance(_cj_raw, str):
            conceptos_manuales = json.loads(_cj_raw or '{}')
        elif isinstance(_cj_raw, dict):
            conceptos_manuales = _cj_raw
    except:
        conceptos_manuales = {}

    aj_afp    = float(conceptos_manuales.get('_ajuste_afp', 0.0) or 0.0)
    aj_quinta = float(conceptos_manuales.get('_ajuste_quinta', 0.0) or 0.0)
    aj_otros  = float(conceptos_manuales.get('_ajuste_otros', 0.0) or 0.0)

    if aj_afp != 0:
        desglose_descuentos['Ajuste AFP (Audit)'] = round(aj_afp, 2)
        # aj_afp NO se suma a descuentos_manuales: tiene columna propia en la sábana
        obs_trab.append(f"Ajuste AFP: S/ {aj_afp:,.2f}")

    if aj_quinta != 0:
        retencion_quinta = max(0.0, retencion_quinta + aj_quinta)
        if retencion_quinta > 0:
            desglose_descuentos['Retención 5ta Cat.'] = float(retencion_quinta)
        elif 'Retención 5ta Cat.' in desglose_descuentos:
            del desglose_descuentos['Retención 5ta Cat.']
        obs_trab.append(f"Ajuste 5ta: S/ {aj_quinta:,.2f}")

    if aj_otros != 0:
        desglose_descuentos['Ajuste Varios (Audit)'] = round(aj_otros, 2)
        descuentos_manuales += aj_otros
        obs_trab.append(f"Ajuste Manual: S/ {aj_otros:,.2f}")

    # --- SEGURO SOCIAL (ESSALUD o SIS) Y NETO ---
    # Regla: EsSalud mínimo sobre RMV siempre que el trabajador tenga al
    # menos 1 día remunerado (trabajado o pagado).  Si el mes completo fue
    # suspensión sin goce de haber (días_remunerados == 0) → EsSalud = 0.
    seguro_social = str(row.get('Seguro Social', 'ESSALUD')).upper()
    _mes_completo_ssgh = (h['dias_remunerados'] == 0)

    if _mes_completo_ssgh:
        # Suspensión sin goce de haber todo el mes → sin aporte patronal
        aporte_essalud = 0.0
        etiqueta_seguro = ("SIS" if seguro_social == "SIS"
                           else ("ESSALUD-EPS" if row.get('EPS', 'No') == "Sí"
                                 else "ESSALUD"))
    elif seguro_social == "SIS":
        aporte_essalud = 15.0  # Monto fijo SIS - Solo Micro Empresa
        etiqueta_seguro = "SIS"
    elif row.get('EPS', 'No') == "Sí":
        aporte_essalud = max(h['base_essalud'], p['rmv']) * (p['tasa_eps'] / 100)
        etiqueta_seguro = "ESSALUD-EPS"
    else:
        aporte_essalud = max(h['base_essalud'], p['rmv']) * (p['tasa_essalud'] / 100)
        etiqueta_seguro = "ESSALUD"

    neto_pagar = h['ingresos_totales'] - pen['total_pension'] - aj_afp - retencion_quinta - descuentos_manuales

    # --- FILA DE LA SÁBANA CORPORATIVA ---
    fila = {
        "DNI": dni_trabajador,
        "Apellidos y Nombres": nombres,
        "Sist. Pensión": sistema,
        "Seg. Social": etiqueta_seguro,
        "Sueldo Base": round(h['sueldo_computable'], 2),
        "Asig. Fam.": round(h['monto_asig_fam'], 2),
        "Otros Ingresos": round((h['pago_he_25'] + h['pago_he_35'] + h['monto_grati'] + h['otros_ingresos']), 2),
        "TOTAL BRUTO": round(h['ingresos_totales'], 2),
        "ONP (13%)": round(pen['dscto_onp'], 2),
        "AFP Aporte": round(pen['aporte_afp'], 2),
        "AFP Seguro": round(pen['prima_afp'], 2),
        "AFP Comis.": round(pen['comis_afp'], 2),
        "Ajuste AFP": round(aj_afp, 2),
        "Ret. 5ta Cat.": float(retencion_quinta),
        "Dsctos/Faltas": round(descuentos_manuales, 2),
        "NETO A PAGAR": round(neto_pagar, 2),
        "Aporte Seg. Social": round(aporte_essalud, 2),
        # Alias para compatibilidad con boletas (leen 'EsSalud Patronal')
        "EsSalud Patronal": round(aporte_essalud, 2),
        # Datos bancarios para reporte de tesorería
        "Banco":     str(row.get('Banco', '') or ''),
        "N° Cuenta": str(row.get('Cuenta Bancaria', '') or ''),
        "CCI":       str(row.get('CCI', '') or ''),
        "Observaciones": " | ".join(obs_trab) if obs_trab else "",
    }

    auditoria = {
        "nombres": nombres, "periodo": periodo_key,
        "dias": h['dias_laborados'],               # días efectivamente laborados
        "dias_computables": h['dias_computables'],  # base de proporcionalidad
        "observaciones": " | ".join(obs_trab),
        "rem_diaria": round(h['sueldo_base_nominal'] / 30.0, 2),
        "horas_ordinarias": h['horas_ordinarias'],  # para .JOR de PLAME
        "suspensiones": h['susp_dict'],             # para .SNL de PLAME
        "base_afp": round(h['base_afp_onp'], 2),   # para AFPnet
        "seguro_social": etiqueta_seguro,
        "aporte_seg_social": round(aporte_essalud, 2),
        "ingresos": h['desglose_ingresos'], "descuentos": desglose_descuentos,
        "totales": {"ingreso": h['ingresos_totales'], "descuento": (pen['total_pension'] + aj_afp + retencion_quinta + descuentos_manuales), "neto": neto_pagar},
        "quinta": {
            "rem_previa": qta['rem_previa_historica'], "ret_previa": qta['retencion_previa_historica'],
            "base_mes": h['base_quinta_mes'], "meses_restantes": qta['meses_restantes'],
            "proy_sueldo": qta['proy_sueldo'], "proy_grati": qta['proy_grati'],
            "bruta_anual": qta['renta_bruta_anual'], "uit_valor": p['uit'], "uit_7": 7 * p['uit'],
            "neta_anual": qta['renta_neta_anual'], "detalle_tramos": qta['detalle_tramos'],
            "imp_anual": qta['impuesto_anual'], "divisor": qta['divisor'], "retencion": retencion_quinta
        }
    }
    return fila, auditoria

def _render_planilla_tab(empresa_id, empresa_nombre, mes_seleccionado, anio_seleccionado, periodo_key, mes_idx):
    # ─── LEER DATOS DESDE NEON ────────────────────────────────────────────────
    db = SessionLocal()
    try:
        # 1. Parámetros Legales
        p = cargar_parametros(db, empresa_id, periodo_key)
        if not p:
            st.error(f"🛑 ALTO: No se han configurado los Parámetros Legales para el periodo **{periodo_key}**.")
            st.info("Vaya al módulo 'Parámetros Legales' y configure las tasas para este periodo.")
            return

        # 1b. Jornada diaria de la empresa (default 8 h)
        empresa_obj = db.query(EmpresaModel).filter_by(id=empresa_id).first()
        horas_jornada = float(getattr(empresa_obj, 'horas_jornada_diaria', None) or 8.0)

        # 2. Trabajadores activos (considerando fecha de cese para el periodo)
        df_trab = cargar_trabajadores_df(db, empresa_id, periodo_key=periodo_key)
        if df_trab.empty:
            st.warning("⚠️ No hay trabajadores activos registrados en el Maestro de Personal.")
            return

        # 3. Conceptos de la empresa
        conceptos_list = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
        conceptos_empresa = cargar_conceptos_df(db, empresa_id)

        # 4. Variables del periodo
        df_var = cargar_variables_df(db, empresa_id, periodo_key, conceptos_list)
        if df_var.empty:
            st.warning(f"⚠️ No se han ingresado Asistencias para **{periodo_key}**.")
            st.info("Vaya al módulo 'Ingreso de Asistencias' y guarde las variables del mes.")
            return

        # Merge principal (igual que antes)
        df_planilla = pd.merge(df_trab, df_var, on="Num. Doc.", how="inner")

        # Compatibilidad con emision_boletas.py (lee de session_state)
        st.session_state['trabajadores_mock'] = df_trab
        if 'variables_por_periodo' not in st.session_state:
            st.session_state['variables_por_periodo'] = {}
        st.session_state['variables_por_periodo'][periodo_key] = df_var

    finally:
        db.close()

    # ── VERIFICAR ESTADO DE CIERRE ─────────────────────────────────────────
    es_cerrada = False
    try:
        db_ck = SessionLocal()
        plan_ck = db_ck.query(PlanillaMensual).filter_by(
            empresa_id=empresa_id, periodo_key=periodo_key
        ).first()
        db_ck.close()
        if plan_ck and getattr(plan_ck, 'estado', 'ABIERTA') == 'CERRADA':
            es_cerrada = True
    except Exception:
        pass

    # ── VERIFICAR LOCADORES SIN ASISTENCIA GUARDADA ──────────────────────────
    locadores_pendientes = False
    try:
        db_lv = SessionLocal()
        # Solo locadores que ya deberían haber ingresado según su fecha de ingreso
        _mes_c = int(periodo_key[:2])
        _ani_c = int(periodo_key[3:])
        
        locs_activos = db_lv.query(Trabajador).filter_by(
            empresa_id=empresa_id, situacion="ACTIVO", tipo_contrato="LOCADOR"
        ).all()
        
        locs_que_corresponden = [
            l for l in locs_activos 
            if not (l.fecha_ingreso and (l.fecha_ingreso.year > _ani_c or (l.fecha_ingreso.year == _ani_c and l.fecha_ingreso.month > _mes_c)))
        ]
        
        if locs_que_corresponden:
            ids_locs = [l.id for l in locs_que_corresponden]
            n_vars_loc = db_lv.query(VariablesMes).filter(
                VariablesMes.empresa_id == empresa_id,
                VariablesMes.periodo_key == periodo_key,
                VariablesMes.trabajador_id.in_(ids_locs)
            ).count()
            locadores_pendientes = (n_vars_loc < len(locs_que_corresponden))
        db_lv.close()
    except Exception:
        locadores_pendientes = False

    # El rol 'consulta' (Auditor) no tiene acceso a botones de acción
    es_auditor = st.session_state.get('usuario_rol') == 'consulta'

    if es_cerrada:
        st.error(f"🔒 La planilla del periodo **{periodo_key}** ya fue CERRADA y contabilizada. Vaya al final de la página para reabrirla si tiene permisos de Supervisor.")
    elif es_auditor:
        st.warning("🧐 **Modo Auditoría:** Usted tiene acceso de solo lectura. No puede ejecutar cálculos ni modificar datos.")
    else:
        if locadores_pendientes:
            st.warning(
                f"⚠️ **CÁLCULO BLOQUEADO:** Hay locadores de servicio sin asistencia guardada para **{periodo_key}**. "
                f"Vaya al módulo **'Ingreso de Asistencias'** → pestaña **'🧾 2. Valorización de Locadores'** "
                f"y guarde antes de ejecutar el motor de planilla."
            )
        st.info("💡 **Novedad:** Ahora puedes configurar qué conceptos dinámicos (ej. Movilidad) se reducen automáticamente por faltas desde el **Maestro de Conceptos**.")
        if st.button(f"🚀 Ejecutar Motor de Planilla - {periodo_key}", type="primary", use_container_width=True, disabled=es_auditor):
            st.session_state['ultima_planilla_calculada'] = True
            
            # INICIALIZACIÓN GARANTIZADA
            resultados = []
            auditoria_data = {}

            mes_calc  = int(mes_seleccionado[:2])
            anio_calc = int(anio_seleccionado)
            contexto  = _cargar_contexto_calculo(empresa_id, periodo_key, mes_idx, anio_seleccionado)
            seq_num   = 0
            for index, row in df_planilla.iterrows():
                resultado = _calcular_fila_trabajador(
                    row, p, horas_jornada, mes_calc, anio_calc, mes_idx, periodo_key,
                    contexto['historico_quinta'], contexto['cuotas_del_mes'],
                    contexto['notas_gestion_map'], conceptos_empresa, contexto['factor_g'],
                )
                if resultado is not None:
                    seq_num += 1
                    fila, auditoria_row = resultado
                    fila['N°'] = seq_num
                    resultados.append(fila)
                    auditoria_data[fila['DNI']] = auditoria_row

            df_resultados = pd.DataFrame(resultados).fillna(0.0)
            
            # --- FILA DE TOTALES DINÁMICA ---
            cols_texto = {"N°", "DNI", "Apellidos y Nombres", "Sist. Pensión", "Seg. Social", "Banco", "N° Cuenta", "CCI", "Observaciones"}
            totales = {"N°": "", "DNI": "", "Apellidos y Nombres": "TOTALES", "Sist. Pensión": "", "Seg. Social": "", "Banco": "", "N° Cuenta": "", "CCI": "", "Observaciones": ""}
            for col in df_resultados.columns:
                if col not in cols_texto:
                    totales[col] = df_resultados[col].sum()
                
            df_resultados = pd.concat([df_resultados, pd.DataFrame([totales])], ignore_index=True)
            st.session_state['res_planilla'] = df_resultados
            st.session_state['auditoria_data'] = auditoria_data

            # --- GUARDAR PLANILLA EN NEON (persistencia real) ---
            try:
                db2 = SessionLocal()
                
                # Validación Maestra Date-Aware: ¿Existen locadores activos para ESTE periodo?
                _m_calc = int(periodo_key[:2])
                _a_calc = int(periodo_key[3:])
                _locs_all = db2.query(Trabajador).filter_by(empresa_id=empresa_id, situacion="ACTIVO", tipo_contrato="LOCADOR").all()
                n_loc_periodo = len([
                    l for l in _locs_all 
                    if not (l.fecha_ingreso and (l.fecha_ingreso.year > _a_calc or (l.fecha_ingreso.year == _a_calc and l.fecha_ingreso.month > _m_calc)))
                ])
                
                df_loc_to_save = st.session_state.get(f'res_honorarios_{periodo_key}')
                
                # Si el maestro dice 0, forzamos un DataFrame vacío para LIMPIAR el snapshot fantasma
                if n_loc_periodo == 0:
                    df_loc_to_save = pd.DataFrame()
                elif df_loc_to_save is None:
                    # Recuperar snapshot existente para no perderlo si el usuario solo calculó la 5ta categoría
                    p_exist = db2.query(PlanillaMensual).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first()
                    if p_exist and p_exist.honorarios_json and p_exist.honorarios_json != '[]':
                        df_loc_to_save = pd.read_json(io.StringIO(p_exist.honorarios_json), orient='records')

                guardar_planilla(db2, empresa_id, periodo_key, df_resultados, auditoria_data, df_locadores=df_loc_to_save)
                db2.close()
            except Exception as e:
                st.warning(f"Planilla calculada pero no se pudo guardar en la nube: {e}")

    # --- RECUPERACIÓN DE SNAPSHOT (Inmutabilidad para Periodos Cerrados) ---
    # Si es un periodo CERRADO, forzamos la carga desde la base de datos y bloqueamos recálculos
    if es_cerrada:
        try:
            db3 = SessionLocal()
            df_rec, aud_rec = cargar_planilla_guardada(db3, empresa_id, periodo_key)
            # Cargar también snapshot de honorarios
            p_snap = db3.query(PlanillaMensual).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first()
            db3.close()
            
            if df_rec is not None and not df_rec.empty:
                st.session_state['res_planilla'] = df_rec
                st.session_state['auditoria_data'] = aud_rec
                st.session_state['ultima_planilla_calculada'] = True
                
                # Sincronizar snapshot de honorarios si existe
                if p_snap and p_snap.honorarios_json and p_snap.honorarios_json != '[]':
                    st.session_state[f'res_honorarios_{periodo_key}'] = pd.read_json(io.StringIO(p_snap.honorarios_json), orient='records')
        except Exception as e:
            st.error(f"Error al cargar snapshot inmutable: {e}")
    
    # Para periodos ABIERTOS, intentar recuperar si no se ha calculado en esta sesión
    elif not st.session_state.get('ultima_planilla_calculada', False):
        try:
            db3 = SessionLocal()
            df_rec, aud_rec = cargar_planilla_guardada(db3, empresa_id, periodo_key)
            db3.close()
            if df_rec is not None and not df_rec.empty:
                st.session_state['res_planilla'] = df_rec
                st.session_state['auditoria_data'] = aud_rec
                st.session_state['ultima_planilla_calculada'] = True
                st.info(f"📂 Planilla de **{periodo_key}** recuperada desde la nube.")
        except Exception:
            pass

    # --- RENDERIZADO VISUAL ---
    if st.session_state.get('ultima_planilla_calculada', False):
        df_resultados = st.session_state['res_planilla']
        auditoria_data = st.session_state.get('auditoria_data', {})

        if not es_cerrada:
            st.success("✅ Planilla generada con éxito.")

        st.markdown("### 📊 Matriz de Nómina")
        st.dataframe(df_resultados.iloc[:-1], use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("#### 📥 Exportación Corporativa (Planilla)")
        empresa_ruc_s = st.session_state.get('empresa_activa_ruc', '')
        empresa_reg_s = st.session_state.get('empresa_activa_regimen', '')
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            try:
                excel_file = generar_excel_sabana(df_resultados, empresa_nombre, periodo_key, empresa_ruc=empresa_ruc_s)
                st.download_button("📊 Descargar Sábana (.xlsx)", data=excel_file, file_name=f"PLANILLA_{periodo_key}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key="dl_plan_xl")
            except Exception: pass
        with col_btn2:
            try:
                pdf_buffer = generar_pdf_sabana(df_resultados, empresa_nombre, periodo_key, empresa_ruc=empresa_ruc_s, empresa_regimen=empresa_reg_s)
                st.download_button("📄 Descargar Sábana y Resumen (PDF)", data=pdf_buffer, file_name=f"SABANA_{periodo_key}.pdf", mime="application/pdf", use_container_width=True, key="dl_plan_pdf")
            except Exception: pass



# ─── MOTOR DE HONORARIOS (4ta Categoría) ─────────────────────────────────────

def _render_honorarios_tab(empresa_id, empresa_nombre, periodo_key):
    """Motor de cálculo para Locadores de Servicio (4ta Categoría)."""
    db = SessionLocal()
    try:
        # 1. Parámetros legales del periodo
        p = cargar_parametros(db, empresa_id, periodo_key)
        if not p:
            st.error(f"🛑 No se han configurado los Parámetros Legales para **{periodo_key}**.")
            st.info("Vaya al módulo 'Parámetros Legales' y configure las tasas para este periodo.")
            return

        tasa_4ta = p.get('tasa_4ta', 8.0)
        tope_4ta = p.get('tope_4ta', 1500.0)

        # 2. Locadores activos
        mes_int  = int(periodo_key[:2])
        anio_int = int(periodo_key[3:])

        locadores_db = (
            db.query(Trabajador)
            .filter_by(empresa_id=empresa_id, situacion="ACTIVO", tipo_contrato="LOCADOR")
            .all()
        )

        # Filtrar locadores por fecha de ingreso y fecha de cese
        locadores = [
            l for l in locadores_db
            if not (l.fecha_ingreso and (l.fecha_ingreso.year > anio_int or (l.fecha_ingreso.year == anio_int and l.fecha_ingreso.month > mes_int)))
            and not (getattr(l, 'fecha_cese', None) and (l.fecha_cese.year < anio_int or (l.fecha_cese.year == anio_int and l.fecha_cese.month < mes_int)))
        ]

        if not locadores:
            st.info("ℹ️ No hay Locadores de Servicio activos registrados en el Maestro de Personal.")
            return

        # 3. Variables del periodo para locadores
        variables_mes = (
            db.query(VariablesMes)
            .filter_by(empresa_id=empresa_id, periodo_key=periodo_key)
            .all()
        )
        vars_por_doc: dict = {}
        for v in variables_mes:
            dni = v.trabajador.num_doc
            conceptos_data = json.loads(v.conceptos_json or '{}')
            vars_por_doc[dni] = {
                'dias_no_prestados': getattr(v, 'dias_descuento_locador', 0) or 0,
                'otros_pagos':       float(conceptos_data.get('_otros_pagos_loc', 0.0) or 0.0),
                'otros_descuentos':  float(conceptos_data.get('_otros_descuentos_loc', 0.0) or 0.0),
            }

        # 4. Días del mes
        dias_del_mes = calendar.monthrange(anio_int, mes_int)[1]

    finally:
        db.close()

    # Verificar estado de cierre
    es_cerrada = False
    try:
        db_ck = SessionLocal()
        plan_ck = db_ck.query(PlanillaMensual).filter_by(
            empresa_id=empresa_id, periodo_key=periodo_key
        ).first()
        db_ck.close()
        if plan_ck and getattr(plan_ck, 'estado', 'ABIERTA') == 'CERRADA':
            es_cerrada = True
    except Exception:
        pass

    st.caption(f"Tasa retención 4ta Cat.: **{tasa_4ta}%** | Tope mínimo para retener: **S/ {tope_4ta:,.2f}**")

    if es_cerrada:
        st.error(f"🔒 Los honorarios del periodo **{periodo_key}** ya fueron CERRADOS.")
    elif st.button(f"🧮 Calcular Honorarios - {periodo_key}", type="primary", use_container_width=True, disabled=es_auditor):
        resultados_loc = []
        
        # Precargar cuotas de préstamos para locadores
        cuotas_loc = {}
        try:
            db_cl = SessionLocal()
            _c_loc = db_cl.query(CuotaPrestamo).join(Prestamo).filter(
                Prestamo.empresa_id == empresa_id,
                CuotaPrestamo.periodo_key == periodo_key,
                CuotaPrestamo.estado == 'PENDIENTE'
            ).all()
            for _cloc in _c_loc:
                cuotas_loc.setdefault(_cloc.prestamo.trabajador.num_doc, []).append(_cloc)
            db_cl.close()
        except Exception:
            pass

        # Precargar notas para locadores
        notas_loc_map = {}
        try:
            db_nl = SessionLocal()
            _v_nl = db_nl.query(VariablesMes).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).all()
            for _vnl in _v_nl:
                notas_loc_map[_vnl.trabajador.num_doc] = getattr(_vnl, 'notas_gestion', '') or ''
            db_nl.close()
        except: pass

        for loc in locadores:
            dni = loc.num_doc
            vars_loc = vars_por_doc.get(dni, {})
            
            # Sumar cuotas de préstamos a otros descuentos del locador
            monto_cuotas_loc = sum(float(c.monto) for c in cuotas_loc.get(dni, []))
            if monto_cuotas_loc > 0:
                vars_loc['otros_descuentos'] = vars_loc.get('otros_descuentos', 0.0) + monto_cuotas_loc
                cuotas_desc = [f"{c.prestamo.concepto} (Cuota {c.numero_cuota})" for c in cuotas_loc.get(dni, [])]
                obs_p = f"Dscto. Préstamos: {', '.join(cuotas_desc)}"
            else:
                obs_p = ""

            resultado = calcular_recibo_honorarios(
                loc, vars_loc, dias_del_mes,
                tasa_4ta=tasa_4ta, tope_4ta=tope_4ta,
                anio_calc=anio_int, mes_calc=mes_int,
            )
            
            if obs_p:
                resultado['observaciones'] = f"{resultado['observaciones']} | {obs_p}" if resultado['observaciones'] else obs_p
            
            # Integrar Nota de Gestión Manual para locadores
            nota_m_loc = notas_loc_map.get(dni, "")
            if nota_m_loc:
                resultado['observaciones'] = f"{resultado['observaciones']} | NOTA: {nota_m_loc}" if resultado['observaciones'] else f"NOTA: {nota_m_loc}"
            
            # Agregar monto de descuento por días no prestados para Tesorería
            if resultado['dias_no_prestados'] > 0:
                desc_dias = f"Días no prestados: {resultado['dias_no_prestados']} (Desc: S/ {resultado['monto_descuento']:,.2f})"
                resultado['observaciones'] = f"{resultado['observaciones']} | {desc_dias}" if resultado['observaciones'] else desc_dias

            resultados_loc.append({
                "DNI":                 dni,
                "Locador":             loc.nombres,
                "Honorario Base":      resultado['honorario_base'],
                "Días Laborados":      resultado['dias_laborados'],
                "Días no Prestados":   resultado['dias_no_prestados'],
                "Descuento Días":      resultado['monto_descuento'],
                "Otros Pagos":         resultado['otros_pagos'],
                "Pago Bruto":          resultado['pago_bruto'],
                "Retención 4ta (8%)":  resultado['retencion_4ta'],
                "Otros Descuentos":    resultado['otros_descuentos'],
                "NETO A PAGAR":        resultado['neto_a_pagar'],
                "Banco":               getattr(loc, 'banco', '') or '',
                "N° Cuenta":           getattr(loc, 'cuenta_bancaria', '') or '',
                "CCI":                 getattr(loc, 'cci', '') or '',
                "Observaciones":       resultado['observaciones'],
            })
        st.session_state[f'res_honorarios_{periodo_key}'] = pd.DataFrame(resultados_loc)

        # Persistir snapshot de locadores a BD de forma inmediata e independiente del motor 5ta
        try:
            _df_hon_save = pd.DataFrame(resultados_loc)
            db_hon = SessionLocal()
            _plan_hon = db_hon.query(PlanillaMensual).filter_by(
                empresa_id=empresa_id, periodo_key=periodo_key
            ).first()
            _hon_json_str = _df_hon_save.to_json(orient='records', date_format='iso')
            if _plan_hon:
                _plan_hon.honorarios_json = _hon_json_str
            else:
                db_hon.add(PlanillaMensual(
                    empresa_id=empresa_id,
                    periodo_key=periodo_key,
                    resultado_json='[]',
                    auditoria_json='{}',
                    honorarios_json=_hon_json_str,
                ))
            db_hon.commit()
            db_hon.close()
        except Exception as _e_hon_save:
            st.warning(f"Honorarios calculados pero no se pudo guardar snapshot en la nube: {_e_hon_save}")

    key_res = f'res_honorarios_{periodo_key}'
    if st.session_state.get(key_res) is not None and not st.session_state[key_res].empty:
        df_loc = st.session_state[key_res]
        st.success("✅ Valorización de Honorarios generada.")
        st.dataframe(df_loc, use_container_width=True, hide_index=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Pago Bruto",      f"S/ {df_loc['Pago Bruto'].sum():,.2f}")
        c2.metric("Total Retención 4ta",   f"S/ {df_loc['Retención 4ta (8%)'].sum():,.2f}")
        c3.metric("Total Neto a Pagar",    f"S/ {df_loc['NETO A PAGAR'].sum():,.2f}")

        st.markdown("---")
        st.markdown("#### 📥 Exportación Corporativa (Locadores)")
        col_h1, col_h2 = st.columns(2)
        empresa_ruc_h = st.session_state.get('empresa_activa_ruc', '')
        empresa_reg_h = st.session_state.get('empresa_activa_regimen', '')
        with col_h1:
            buf_xls = generar_excel_honorarios(df_loc, empresa_nombre, periodo_key, empresa_ruc=empresa_ruc_h)
            st.download_button(
                "📊 Descargar Valorización (.xlsx)",
                data=buf_xls,
                file_name=f"HONORARIOS_{periodo_key}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with col_h2:
            pdf_hon = generar_pdf_honorarios(df_loc, empresa_nombre, periodo_key, empresa_ruc=empresa_ruc_h, empresa_regimen=empresa_reg_h)
            st.download_button(
                "📄 Descargar Valorización (PDF)",
                data=pdf_hon,
                file_name=f"HONORARIOS_{periodo_key}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
    else:
        if not es_cerrada:
            st.info("Presione el botón para calcular los honorarios del periodo.")




def _render_seccion_tesoreria(empresa_id, empresa_nombre, periodo_key):
    """Sección de Gestión de Tesorería: reporte PDF + panel de auditoría tributaria."""
    # ── SECCIÓN GLOBAL DE TESORERÍA ──────────────────────────────────────────
    df_plan_glob = st.session_state.get('res_planilla', pd.DataFrame())
    df_loc_glob  = st.session_state.get(f'res_honorarios_{periodo_key}', pd.DataFrame())
    aud_glob  = st.session_state.get('auditoria_data', {})

    # Rescate de snapshot en BD si la sesión está vacía (tras reapertura)
    if df_loc_glob.empty:
        try:
            _db_s = SessionLocal()
            _p_s = _db_s.query(PlanillaMensual).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first()
            if _p_s and _p_s.honorarios_json and _p_s.honorarios_json != '[]':
                df_loc_glob = pd.read_json(io.StringIO(_p_s.honorarios_json), orient='records')
                st.session_state[f'res_honorarios_{periodo_key}'] = df_loc_glob
            _db_s.close()
        except: pass

    if not df_plan_glob.empty or not df_loc_glob.empty:
        st.markdown("---")
        st.subheader("🏦 Gestión de Tesorería")

        # Verificar estado de cierre
        es_cerrada_teso = False
        try:
            db_ct = SessionLocal()
            plan_ct = db_ct.query(PlanillaMensual).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first()
            if plan_ct and getattr(plan_ct, 'estado', 'ABIERTA') == 'CERRADA':
                es_cerrada_teso = True
            db_ct.close()
        except: pass

        if es_cerrada_teso:
            st.info("ℹ️ **Periodo Cerrado:** Para obtener el reporte oficial de tesorería y archivos bancarios inmutables, debe ir al módulo **Reportería**, pestaña **🏦 Reporte Tesorería**.")
        else:
            try:
                _db_chk = SessionLocal()
                _m_t = int(periodo_key[:2])
                _a_t = int(periodo_key[3:])
                _locs_t = _db_chk.query(Trabajador).filter_by(empresa_id=empresa_id, situacion='ACTIVO', tipo_contrato='LOCADOR').all()
                _n_loc_glob = len([
                    l for l in _locs_t 
                    if not (l.fecha_ingreso and (l.fecha_ingreso.year > _a_t or (l.fecha_ingreso.year == _a_t and l.fecha_ingreso.month > _m_t)))
                ])
                _db_chk.close()
            except:
                _n_loc_glob = 0
            
            if _n_loc_glob > 0 and df_loc_glob.empty:
                st.warning("⚠️ **Reporte Bloqueado:** Se detectaron locadores activos en este periodo sin honorarios calculados. Calcule en la pestaña '🧾 2' para habilitar el reporte de tesorería.")
            else:
                try:
                    buf_teso_f = generar_pdf_tesoreria(
                        df_planilla=df_plan_glob if not df_plan_glob.empty else None,
                        df_loc=df_loc_glob if not df_loc_glob.empty else None,
                        empresa_nombre=empresa_nombre,
                        periodo_key=periodo_key,
                        auditoria_data=aud_glob,
                        empresa_ruc=st.session_state.get('empresa_activa_ruc', ''),
                    )
                    st.download_button(
                        "🏦 Descargar Reporte de Tesorería (PDF)",
                        data=buf_teso_f,
                        file_name=f"TESORERIA_{periodo_key}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        type="primary",
                        key="btn_teso_global_v_final"
                    )
                except Exception: pass

        st.markdown("---")
        with st.expander("🔍 Panel de Auditoría Tributaria y Liquidaciones", expanded=False):
            if not aud_glob:
                st.info("No hay datos de auditoría calculados.")
            else:
                opciones_trab = [f"{dni} - {info['nombres']}" for dni, info in aud_glob.items()]
                trabajador_sel = st.selectbox("Seleccione un trabajador para ver su detalle legal:", opciones_trab, label_visibility="collapsed")
                
                if trabajador_sel:
                    dni_sel = trabajador_sel.split(" - ")[0]
                    data = aud_glob[dni_sel]
                    q = data['quinta']
                    t_audit1, t_audit2 = st.tabs(["💰 Boleta Mensual", "🏛️ Certificado de 5ta Categoría"])
                    with t_audit1:
                        c_a1, c_a2 = st.columns(2)
                        with c_a1:
                            for k, v in data['ingresos'].items(): st.markdown(f"- **{k}:** S/ {v:,.2f}")
                            st.success(f"**Total Ingresos: S/ {data['totales']['ingreso']:,.2f}**")
                        with c_a2:
                            for k, v in data['descuentos'].items(): st.markdown(f"- **{k}:** S/ {v:,.2f}")
                            st.error(f"**Total Descuentos: S/ {data['totales']['descuento']:,.2f}**")
                    with t_audit2:
                        if q['neta_anual'] <= 0: st.success("Este trabajador NO supera las 7 UIT anuales.")
                        else:
                            pdf_5ta = generar_pdf_quinta(q, empresa_nombre, periodo_key, data['nombres'])
                            st.download_button("📄 Descargar Certificado de 5ta Categoría (PDF)", data=pdf_5ta, file_name=f"QUINTA_{dni_sel}_{periodo_key}.pdf", mime="application/pdf")



def _render_seccion_reporte_combinado(empresa_id, empresa_nombre, periodo_key):
    """Sección de Reporte Consolidado de Costo Laboral (Planilla + Locadores)."""
    # ── REPORTE COMBINADO (Planilla + Locadores) ───────────────────────────────
    df_plan_comb = st.session_state.get('res_planilla', pd.DataFrame())
    df_loc_comb  = st.session_state.get(f'res_honorarios_{periodo_key}', pd.DataFrame())

    if not df_plan_comb.empty:
        # Gate del reporte combinado: misma lógica que en _render_planilla_tab
        try:
            _db_gc = SessionLocal()
            _n_loc_gc = _db_gc.query(Trabajador).filter_by(
                empresa_id=empresa_id, situacion='ACTIVO', tipo_contrato='LOCADOR'
            ).count()
            _db_gc.close()
        except Exception:
            _n_loc_gc = 0
        _gate_comb = (_n_loc_gc == 0) or (not df_loc_comb.empty)

        st.markdown("---")
        with st.expander("📋 Reporte Consolidado de Costo Laboral (Planilla + Locadores)", expanded=False):
            st.markdown(
                "Genera un único documento PDF/Excel que combina la sábana de planilla y la "
                "valorización de locadores, más un resumen del costo laboral total de la empresa."
            )
            if not _gate_comb:
                st.warning(
                    "⚠️ Esta empresa tiene **Locadores de Servicio activos**. "
                    "Calcule primero los **Honorarios** en la pestaña '🧾 2. Honorarios (4ta Categoría)' "
                    "para que el reporte incluya la información completa."
                )
            elif df_loc_comb.empty:
                st.info("ℹ️ No hay datos de honorarios calculados para este periodo. El reporte combinado incluirá solo la planilla.")

            if _gate_comb:
                empresa_ruc_c = st.session_state.get('empresa_activa_ruc', '')
                empresa_reg_c = st.session_state.get('empresa_activa_regimen', '')
                col_comb1, col_comb2 = st.columns(2)
                with col_comb1:
                    pdf_comb = generar_pdf_combinado(
                        df_plan_comb,
                        df_loc_comb if not df_loc_comb.empty else None,
                        empresa_nombre, periodo_key,
                        empresa_ruc=empresa_ruc_c, empresa_regimen=empresa_reg_c
                    )
                    st.download_button(
                        "📄 Descargar Reporte Combinado (PDF)",
                        data=pdf_comb,
                        file_name=f"COSTO_LABORAL_{periodo_key}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        type="primary",
                    )
                with col_comb2:
                    buf_comb_xl = io.BytesIO()
                    with pd.ExcelWriter(buf_comb_xl, engine='openpyxl') as writer:
                        df_plan_comb.to_excel(writer, sheet_name=f'Planilla_{periodo_key[:2]}', index=False)
                        if not df_loc_comb.empty:
                            # Excluir observaciones y datos bancarios de la hoja de locadores en Excel combinado
                            cols_xl_loc = [c for c in df_loc_comb.columns if c not in ["Observaciones", "Banco", "N° Cuenta", "CCI"]]
                            df_loc_comb[cols_xl_loc].to_excel(writer, sheet_name=f'Honorarios_{periodo_key[:2]}', index=False)
                    buf_comb_xl.seek(0)
                    st.download_button(
                        "📊 Descargar Reporte Combinado (.xlsx)",
                        data=buf_comb_xl,
                        file_name=f"COSTO_LABORAL_{periodo_key}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )



def _render_seccion_cierre(empresa_id, empresa_nombre, periodo_key):
    """Sección de Cierre del Periodo: confirmar cierre o reabrir según rol de usuario."""
    # ── SECCIÓN GLOBAL DE CIERRE DEL PERIODO ──────────────────────────────────
    st.markdown("---")
    st.markdown("### 🔒 Cierre del Periodo")

    rol_usuario = st.session_state.get('usuario_rol', 'analista')
    nombre_usuario = st.session_state.get('usuario_nombre', '')

    estado_actual = "ABIERTA"
    planilla_db_cierre = None
    try:
        db_c = SessionLocal()
        planilla_db_cierre = db_c.query(PlanillaMensual).filter_by(
            empresa_id=empresa_id, periodo_key=periodo_key
        ).first()
        db_c.close()
        if planilla_db_cierre:
            estado_actual = getattr(planilla_db_cierre, 'estado', 'ABIERTA') or 'ABIERTA'
    except Exception:
        pass

    if estado_actual == "CERRADA":
        cerrada_por  = getattr(planilla_db_cierre, 'cerrada_por', '') or '—'
        fecha_cierre = getattr(planilla_db_cierre, 'fecha_cierre', None)
        fecha_str    = fecha_cierre.strftime("%d/%m/%Y %H:%M") if fecha_cierre else '—'
        st.error(f"**PERIODO CERRADO** — Responsable: {cerrada_por}  |  Fecha: {fecha_str}")
        if rol_usuario in ["supervisor", "admin"]:
            st.info("Como Administrador/Supervisor puede reabrir este periodo para modificaciones.")
            if st.button("🔓 Reabrir Periodo", use_container_width=False):
                try:
                    db_up = SessionLocal()
                    p = db_up.query(PlanillaMensual).filter_by(
                        empresa_id=empresa_id, periodo_key=periodo_key
                    ).first()
                    if p:
                        p.estado = "ABIERTA"
                        p.cerrada_por = None
                        p.fecha_cierre = None
                        # Revertir cuotas de préstamos a PENDIENTE
                        _cuotas_rev = (
                            db_up.query(CuotaPrestamo)
                            .join(Prestamo)
                            .filter(
                                Prestamo.empresa_id == empresa_id,
                                CuotaPrestamo.periodo_key == periodo_key,
                                CuotaPrestamo.estado == 'PAGADA',
                            )
                            .all()
                        )
                        for _cr in _cuotas_rev:
                            _cr.estado = 'PENDIENTE'
                        db_up.commit()
                        db_up.close()
                        st.toast("Periodo REABIERTO para edición", icon="🔓")
                        st.rerun()
                except Exception as e_re:
                    st.error(f"Error al reabrir: {e_re}")
        else:
            st.warning("Solo un **Supervisor** o **Admin** puede reabrir este periodo.")
    else:
        st.info(f"El periodo **{periodo_key}** está **ABIERTO**. Puede recalcularse hasta que sea cerrado.")
        if rol_usuario in ["supervisor", "admin"]:
            with st.expander("Cerrar Periodo"):
                st.warning("Al cerrar el periodo se bloquearán las ediciones y asistencias.")
                if st.button("Confirmar Cierre de Periodo", type="primary"):
                    try:
                        db_up = SessionLocal()
                        p = db_up.query(PlanillaMensual).filter_by(
                            empresa_id=empresa_id, periodo_key=periodo_key
                        ).first()

                        # ── VALIDACIÓN ENTERPRISE: ambos motores deben estar calculados ──────────
                        _m_c = int(periodo_key[:2])
                        _a_c = int(periodo_key[3:])
                        _trab_all = db_up.query(Trabajador).filter_by(empresa_id=empresa_id, situacion="ACTIVO").all()
                        
                        _n_planilla = len([
                            t for t in _trab_all 
                            if t.tipo_contrato == "PLANILLA" and not (t.fecha_ingreso and (t.fecha_ingreso.year > _a_c or (t.fecha_ingreso.year == _a_c and t.fecha_ingreso.month > _m_c)))
                        ])
                        _n_locs = len([
                            t for t in _trab_all 
                            if t.tipo_contrato == "LOCADOR" and not (t.fecha_ingreso and (t.fecha_ingreso.year > _a_c or (t.fecha_ingreso.year == _a_c and t.fecha_ingreso.month > _m_c)))
                        ])

                        _resultado_snap = (getattr(p, 'resultado_json', '[]') if p else '[]') or '[]'
                        _hon_snap       = (getattr(p, 'honorarios_json', '[]') if p else '[]') or '[]'
                        try:
                            _resultado_list = json.loads(_resultado_snap)
                        except Exception:
                            _resultado_list = []
                        try:
                            _hon_list = json.loads(_hon_snap)
                        except Exception:
                            _hon_list = []

                        _errores = []
                        if _n_planilla > 0 and len(_resultado_list) == 0:
                            _errores.append(
                                f"• **Planilla 5ta Categoría** — {_n_planilla} trabajador(es) activo(s) sin planilla calculada. "
                                "Vaya a la tab **1. Planilla** y ejecute el motor de cálculo."
                            )
                        if _n_locs > 0 and len(_hon_list) == 0:
                            _errores.append(
                                f"• **Honorarios 4ta Categoría** — {_n_locs} locador(es) activo(s) sin honorarios calculados. "
                                "Vaya a la tab **2. Honorarios** y presione **🧮 Calcular Honorarios**."
                            )

                        if _errores:
                            db_up.close()
                            st.error(
                                "🚫 **CIERRE BLOQUEADO** — Faltan cálculos obligatorios antes de cerrar el periodo:\n\n" +
                                "\n\n".join(_errores)
                            )
                        else:
                            # Inyección: Crear registro si el mes solo tiene locadores y no se generó planilla 5ta
                            if not p:
                                p = PlanillaMensual(
                                    empresa_id=empresa_id,
                                    periodo_key=periodo_key,
                                    resultado_json="[]",
                                    auditoria_json="{}"
                                )
                                db_up.add(p)
                                db_up.flush()

                            p.estado = "CERRADA"
                            p.cerrada_por = nombre_usuario
                            p.fecha_cierre = datetime.now()

                            # Marcar cuotas del periodo como PAGADAS
                            _cuotas_pag = (
                                db_up.query(CuotaPrestamo)
                                .join(Prestamo)
                                .filter(
                                    Prestamo.empresa_id == empresa_id,
                                    CuotaPrestamo.periodo_key == periodo_key,
                                    CuotaPrestamo.estado == 'PENDIENTE',
                                )
                                .all()
                            )
                            for _cp in _cuotas_pag:
                                _cp.estado = 'PAGADA'

                            db_up.commit()
                            db_up.close()
                            st.toast(f"Periodo {periodo_key} CERRADO exitosamente", icon="🔒")
                            st.rerun()
                    except Exception as e_cl:
                        st.error(f"Error al cerrar: {e_cl}")
        else:
            st.info("Solo un **Supervisor** o **Admin** puede cerrar el periodo.")


# ─── RENDER PRINCIPAL ─────────────────────────────────────────────────────────

def render():
    st.title("⚙️ Ejecución de Planilla Mensual")
    st.markdown("---")

    empresa_id     = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')

    # Determinar automáticamente el próximo periodo abierto
    default_mes_idx = datetime.now().month - 1
    anio_default = datetime.now().year
    if empresa_id:
        try:
            db_auto = SessionLocal()
            cerrados = db_auto.query(PlanillaMensual.periodo_key).filter_by(
                empresa_id=empresa_id, estado='CERRADA'
            ).all()
            db_auto.close()
            periodos_cerrados = [c[0] for c in cerrados]
            
            # Buscar el primer mes del año actual que no esté cerrado
            for idx in range(12):
                p_key = f"{(idx + 1):02d}-{anio_default}"
                if p_key not in periodos_cerrados:
                    default_mes_idx = idx
                    break
        except: pass

    col_m, col_a = st.columns([2, 1])
    mes_seleccionado  = col_m.selectbox("Mes de Cálculo", MESES, index=default_mes_idx, key="calc_mes")
    anio_seleccionado = col_a.selectbox("Año de Cálculo", [2025, 2026, 2027, 2028], index=[2025, 2026, 2027, 2028].index(anio_default), key="calc_anio")
    periodo_key = f"{mes_seleccionado[:2]}-{anio_seleccionado}"

    # Limpieza de estados si el usuario cambia de periodo para evitar contaminación de datos
    if st.session_state.get('_ultimo_periodo_visto') != periodo_key:
        for key in ['res_planilla', 'auditoria_data', 'ultima_planilla_calculada']:
            st.session_state.pop(key, None)
        st.session_state['_ultimo_periodo_visto'] = periodo_key
    mes_idx = MESES.index(mes_seleccionado) + 1

    tab_plan, tab_hon = st.tabs(["📋 1. Planilla (5ta Categoría)", "🧾 2. Honorarios (4ta Categoría)"])

    with tab_plan:
        _render_planilla_tab(empresa_id, empresa_nombre, mes_seleccionado, anio_seleccionado, periodo_key, mes_idx)

    with tab_hon:
        _render_honorarios_tab(empresa_id, empresa_nombre, periodo_key)

    _render_seccion_tesoreria(empresa_id, empresa_nombre, periodo_key)
    _render_seccion_reporte_combinado(empresa_id, empresa_nombre, periodo_key)
    _render_seccion_cierre(empresa_id, empresa_nombre, periodo_key)
