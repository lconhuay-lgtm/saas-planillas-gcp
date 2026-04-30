import streamlit as st
import datetime
import calendar
import io

from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Trabajador, ParametroLegal
from core.domain.payroll_engine import obtener_factores_regimen


def _meses_entre(fecha_desde: datetime.date, fecha_hasta: datetime.date) -> float:
    """Calcula meses completos y fracción entre dos fechas."""
    if fecha_hasta <= fecha_desde:
        return 0.0
    total_dias = (fecha_hasta - fecha_desde).days
    return round(total_dias / 30.0, 4)


def _calcular_liquidacion(
    sueldo_base: float,
    asig_fam: bool,
    fecha_ingreso: datetime.date,
    fecha_cese: datetime.date,
    regimen_empresa: str,
    meses_grati_semestre: int,
    dias_vacaciones_pendientes: int,
    fecha_ultimo_cts: datetime.date,
    rmv: float,
) -> dict:
    """
    Calcula la liquidación de beneficios sociales por cese.
    Fórmulas MTPE / Régimen Laboral Peruano.
    """
    factores = obtener_factores_regimen(regimen_empresa)
    dias_vac_anio = factores.get('vacaciones', 30)

    monto_asig_fam = (rmv * 0.10) if asig_fam else 0.0
    remuneracion_computable = sueldo_base + monto_asig_fam

    # 1. Sueldo proporcional del mes de cese
    valor_dia = sueldo_base / 30.0
    dias_laborados_cese = fecha_cese.day
    sueldo_proporcional = round(valor_dia * dias_laborados_cese, 2)

    # 2. Vacaciones truncas
    # Remuneración vacacional = (sueldo/30) × días_pendientes
    monto_vacaciones_truncas = round((sueldo_base / 30.0) * dias_vacaciones_pendientes, 2)

    # 3. Gratificación trunca
    # (Sueldo + Asig.Fam) × (meses_en_semestre / 6)
    factor_grati = factores.get('grati', 1.0)
    monto_grati_trunca = round(remuneracion_computable * factor_grati * (meses_grati_semestre / 6.0), 2)
    # Bonificación extraordinaria 9% sobre grati trunca (Ley 29351)
    monto_bono_ext = round(monto_grati_trunca * 0.09, 2)

    # 4. CTS trunca
    # Base CTS = Sueldo + Asig.Fam + (1/6 de gratificación)
    factor_cts = factores.get('cts', 1.0)
    base_cts = remuneracion_computable + (monto_grati_trunca / meses_grati_semestre if meses_grati_semestre else 0)
    meses_cts = _meses_entre(fecha_ultimo_cts, fecha_cese)
    monto_cts_trunca = round(base_cts * factor_cts * (meses_cts / 12.0), 2) if meses_cts > 0 else 0.0

    total = sueldo_proporcional + monto_vacaciones_truncas + monto_grati_trunca + monto_bono_ext + monto_cts_trunca

    return {
        'sueldo_proporcional':      sueldo_proporcional,
        'dias_laborados_cese':      dias_laborados_cese,
        'vacaciones_truncas':       monto_vacaciones_truncas,
        'dias_vacaciones_pend':     dias_vacaciones_pendientes,
        'grati_trunca':             monto_grati_trunca,
        'bono_ext_9':               monto_bono_ext,
        'meses_grati':              meses_grati_semestre,
        'cts_trunca':               monto_cts_trunca,
        'meses_cts':                round(meses_cts, 2),
        'base_cts':                 round(base_cts, 2),
        'total_liquidacion':        round(total, 2),
        'remuneracion_computable':  round(remuneracion_computable, 2),
        'asig_fam':                 round(monto_asig_fam, 2),
        'factor_grati':             factor_grati,
        'factor_cts':               factor_cts,
        'dias_vac_anio':            dias_vac_anio,
    }


def render():
    empresa_id      = st.session_state.get('empresa_activa_id')
    empresa_nombre  = st.session_state.get('empresa_activa_nombre')
    regimen_empresa = st.session_state.get('empresa_activa_regimen', 'Régimen General')

    if not empresa_id:
        st.error("⚠️ Seleccione una empresa en el Panel de Control para continuar.")
        return

    st.title("📄 Liquidación por Cese")
    st.markdown(f"**Empresa:** {empresa_nombre} | **Régimen:** {regimen_empresa}")
    st.markdown("---")
    st.info(
        "Calcula los beneficios sociales adeudados al trabajador al momento de su cese. "
        "Los datos históricos (último depósito CTS, días de vacaciones pendientes) "
        "deben ingresarse manualmente por ahora."
    )

    db = SessionLocal()
    try:
        trabajadores = (
            db.query(Trabajador)
            .filter(
                Trabajador.empresa_id == empresa_id,
                Trabajador.tipo_contrato != 'LOCADOR',
            )
            .order_by(Trabajador.nombres)
            .all()
        )

        # Parámetros legales del período más reciente
        param_rec = (
            db.query(ParametroLegal)
            .filter_by(empresa_id=empresa_id)
            .order_by(ParametroLegal.periodo_key.desc())
            .first()
        )
        rmv = param_rec.rmv if param_rec else 1025.0

    finally:
        db.close()

    if not trabajadores:
        st.warning("No hay trabajadores de planilla registrados.")
        return

    # ── Formulario de liquidación ──────────────────────────────────────────────
    opciones_trab = {f"{t.nombres} — DNI {t.num_doc}": t for t in trabajadores}
    sel = st.selectbox("Trabajador", list(opciones_trab.keys()))
    t = opciones_trab[sel]

    col1, col2 = st.columns(2)
    fecha_ingreso_val = t.fecha_ingreso or datetime.date.today()
    fecha_cese_val    = getattr(t, 'fecha_cese', None) or datetime.date.today()

    with col1:
        st.markdown("##### Datos del trabajador")
        st.write(f"**Sueldo Base:** S/ {t.sueldo_base:,.2f}")
        st.write(f"**Asig. Familiar:** {'Sí' if t.asig_fam else 'No'}")
        st.write(f"**Fecha Ingreso:** {fecha_ingreso_val.strftime('%d/%m/%Y')}")
        st.write(f"**RMV vigente:** S/ {rmv:,.2f}")

    with col2:
        st.markdown("##### Parámetros de cese")
        fecha_cese_inp = st.date_input(
            "Fecha de cese",
            value=fecha_cese_val,
            min_value=fecha_ingreso_val,
            max_value=datetime.date.today() + datetime.timedelta(days=365),
        )

        hoy = fecha_cese_inp
        # Determinar meses en el semestre actual (Ene-Jun o Jul-Dic)
        semestre_inicio = datetime.date(hoy.year, 1, 1) if hoy.month <= 6 else datetime.date(hoy.year, 7, 1)
        meses_grati_default = max(1, round(_meses_entre(semestre_inicio, hoy)))
        meses_grati = st.number_input(
            "Meses en el semestre actual (para grati trunca)",
            min_value=0, max_value=6, value=min(meses_grati_default, 6),
            help="Meses transcurridos desde Enero o Julio (según semestre) hasta la fecha de cese."
        )

        dias_vac = st.number_input(
            "Días de vacaciones pendientes (no gozados)",
            min_value=0, max_value=365, value=0,
            help="Días de vacaciones acumulados que el trabajador no ha gozado."
        )

        # Fecha último depósito CTS (default: último mayo o noviembre)
        anio_cts = hoy.year if hoy.month > 5 else hoy.year - 1
        mes_cts  = 5 if hoy.month > 5 else 11
        fecha_cts_default = datetime.date(anio_cts, mes_cts, 31 if mes_cts == 5 else 30)
        fecha_cts_default = min(fecha_cts_default, datetime.date.today())
        fecha_ultimo_cts = st.date_input(
            "Fecha del último depósito de CTS",
            value=fecha_cts_default,
            help="Generalmente Mayo o Noviembre del último año de depósito."
        )

    st.markdown("---")

    if st.button("🧮 Calcular Liquidación", type="primary", use_container_width=True):
        if fecha_cese_inp < fecha_ingreso_val:
            st.error("La fecha de cese no puede ser anterior a la fecha de ingreso.")
        else:
            liq = _calcular_liquidacion(
                sueldo_base=t.sueldo_base,
                asig_fam=bool(t.asig_fam),
                fecha_ingreso=fecha_ingreso_val,
                fecha_cese=fecha_cese_inp,
                regimen_empresa=regimen_empresa,
                meses_grati_semestre=int(meses_grati),
                dias_vacaciones_pendientes=int(dias_vac),
                fecha_ultimo_cts=fecha_ultimo_cts,
                rmv=rmv,
            )

            st.success(f"**Total a pagar al trabajador: S/ {liq['total_liquidacion']:,.2f}**")
            st.markdown("---")
            st.markdown("#### Desglose de Liquidación")

            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("##### Conceptos")
                items = [
                    (f"Sueldo proporcional ({liq['dias_laborados_cese']} días)", liq['sueldo_proporcional']),
                    (f"Vacaciones truncas ({liq['dias_vacaciones_pend']} días)", liq['vacaciones_truncas']),
                    (f"Gratificación trunca ({liq['meses_grati']} mes(es))", liq['grati_trunca']),
                    ("Bono Ext. 9% (Ley 29351)", liq['bono_ext_9']),
                    (f"CTS trunca ({liq['meses_cts']} meses)", liq['cts_trunca']),
                ]
                for concepto, monto in items:
                    mc1, mc2 = st.columns([3, 1])
                    mc1.write(concepto)
                    mc2.write(f"S/ {monto:,.2f}")
                st.markdown("---")
                tc1, tc2 = st.columns([3, 1])
                tc1.markdown("**TOTAL LIQUIDACIÓN**")
                tc2.markdown(f"**S/ {liq['total_liquidacion']:,.2f}**")

            with col_b:
                st.markdown("##### Bases de cálculo")
                st.write(f"Remuneración computable: S/ {liq['remuneracion_computable']:,.2f}")
                st.write(f"Asig. familiar incluida: S/ {liq['asig_fam']:,.2f}")
                st.write(f"Factor gratificación: {liq['factor_grati']*100:.0f}%")
                st.write(f"Factor CTS: {liq['factor_cts']*100:.0f}%")
                st.write(f"Base CTS: S/ {liq['base_cts']:,.2f}")
                st.write(f"Días vac/año (régimen): {liq['dias_vac_anio']}")
                st.write(f"RMV aplicada: S/ {rmv:,.2f}")

            st.info(
                "⚠️ Este cálculo es referencial. Verifique los datos históricos "
                "(CTS, vacaciones) con los registros contables de la empresa antes "
                "de proceder al pago."
            )
