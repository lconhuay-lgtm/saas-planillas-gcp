import streamlit as st
import pandas as pd

MESES = ["01 - Enero", "02 - Febrero", "03 - Marzo", "04 - Abril", "05 - Mayo", "06 - Junio", 
         "07 - Julio", "08 - Agosto", "09 - Septiembre", "10 - Octubre", "11 - Noviembre", "12 - Diciembre"]

def render():
    empresa_id = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')

    if not empresa_id:
        st.error("⚠️ Acceso denegado. Seleccione una empresa en el Dashboard.")
        return

    st.title("⏱️ Ingreso de Asistencias y Variables")
    st.markdown(f"**Empresa:** {empresa_nombre}")
    
    # --- NUEVO: SELECTOR DE PERIODO ---
    st.subheader("Seleccione el Periodo de Ingreso")
    col_m, col_a = st.columns([2, 1])
    mes_seleccionado = col_m.selectbox("Mes", MESES, key="asis_mes")
    anio_seleccionado = col_a.selectbox("Año", [2025, 2026, 2027, 2028], index=1, key="asis_anio")
    periodo_key = f"{mes_seleccionado[:2]}-{anio_seleccionado}"
    
    st.markdown("---")

    # 1. VALIDACIONES INICIALES
    if 'trabajadores_mock' not in st.session_state or st.session_state['trabajadores_mock'].empty:
        st.warning("⚠️ No hay trabajadores registrados. Vaya al 'Maestro de Trabajadores'.")
        return

    df_trabajadores = st.session_state['trabajadores_mock']
    df_activos = df_trabajadores[df_trabajadores['Situación'] == 'ACTIVO'].copy()

    if df_activos.empty:
        st.info("Todos los trabajadores están cesados. No hay nómina a procesar.")
        return

    # 2. OBTENER CONCEPTOS DINÁMICOS DE LA EMPRESA
    df_conceptos = st.session_state.get('conceptos_mock', pd.DataFrame())
    conceptos_empresa = df_conceptos[df_conceptos['Empresa_ID'] == empresa_id] if not df_conceptos.empty else pd.DataFrame()
    
    conceptos_fijos = ["SUELDO BASICO", "ASIGNACION FAMILIAR"]
    conceptos_ingresos = []
    conceptos_descuentos = []

    if not conceptos_empresa.empty:
        for _, row in conceptos_empresa.iterrows():
            nombre = row['Nombre del Concepto']
            if nombre not in conceptos_fijos:
                if row['Tipo'] == "INGRESO":
                    conceptos_ingresos.append(nombre)
                else:
                    conceptos_descuentos.append(nombre)

    # 3. HISTORIAL DE VARIABLES POR PERIODO
    if 'variables_por_periodo' not in st.session_state:
        st.session_state['variables_por_periodo'] = {}

    df_memoria = st.session_state['variables_por_periodo'].get(periodo_key, pd.DataFrame())

    if not df_memoria.empty:
        st.info(f"📝 Cargando datos previamente guardados para el periodo **{periodo_key}**.")
    else:
        st.success(f"✨ Nueva hoja de variables generada para el periodo **{periodo_key}**.")

    # --- SECCIÓN A: TIEMPOS ---
    dict_tiempos = {
        "DNI": df_activos["Num. Doc."],
        "Nombres y Apellidos": df_activos["Nombres y Apellidos"],
        "Días Faltados": [0] * len(df_activos),
        "Min. Tardanza": [0] * len(df_activos),
        "Hrs Extras 25%": [0.0] * len(df_activos),
        "Hrs Extras 35%": [0.0] * len(df_activos)
    }
    df_tiempos = pd.DataFrame(dict_tiempos)
    
    # --- SECCIÓN B: INGRESOS ---
    dict_ingresos = {
        "DNI": df_activos["Num. Doc."],
        "Nombres y Apellidos": df_activos["Nombres y Apellidos"],
        "Sueldo Base": df_activos["Sueldo Base"], 
        "Asig. Fam.": df_activos["Asig. Fam."]    
    }
    for col in conceptos_ingresos: dict_ingresos[col] = [0.0] * len(df_activos)
    df_ingresos = pd.DataFrame(dict_ingresos)

    # --- SECCIÓN C: DESCUENTOS ---
    dict_descuentos = {
        "DNI": df_activos["Num. Doc."],
        "Nombres y Apellidos": df_activos["Nombres y Apellidos"],
    }
    for col in conceptos_descuentos: dict_descuentos[col] = [0.0] * len(df_activos)
    df_descuentos = pd.DataFrame(dict_descuentos)

    # Restaurar datos si existen
    if not df_memoria.empty:
        for df_seccion in [df_tiempos, df_ingresos, df_descuentos]:
            for col in df_seccion.columns:
                if col in df_memoria.columns and col not in ["DNI", "Nombres y Apellidos", "Sueldo Base", "Asig. Fam."]:
                    df_seccion[col] = df_seccion['DNI'].map(df_memoria.set_index('Num. Doc.')[col]).fillna(0)

    # 4. INTERFAZ PROFESIONAL CON PESTAÑAS
    tab_tiempos, tab_ingresos, tab_descuentos = st.tabs([
        "⏰ Tiempos y Asistencias", "💰 Ingresos Variables", "📉 Descuentos Directos"
    ])

    col_config_tiempos = {
        "Días Faltados": st.column_config.NumberColumn(min_value=0, max_value=31, step=1),
        "Min. Tardanza": st.column_config.NumberColumn(min_value=0, step=1),
        "Hrs Extras 25%": st.column_config.NumberColumn(min_value=0.0, step=0.5, format="%.1f"),
        "Hrs Extras 35%": st.column_config.NumberColumn(min_value=0.0, step=0.5, format="%.1f")
    }

    col_config_moneda = {}
    for col in (conceptos_ingresos + conceptos_descuentos):
        col_config_moneda[col] = st.column_config.NumberColumn(min_value=0.0, step=50.0, format="S/ %.2f")

    with tab_tiempos:
        df_tiempos_edit = st.data_editor(df_tiempos, disabled=["DNI", "Nombres y Apellidos"], num_rows="fixed", use_container_width=True, hide_index=True, column_config=col_config_tiempos, key="ed_tiempos")

    with tab_ingresos:
        df_ingresos_edit = st.data_editor(df_ingresos, disabled=["DNI", "Nombres y Apellidos", "Sueldo Base", "Asig. Fam."], num_rows="fixed", use_container_width=True, hide_index=True, column_config=col_config_moneda, key="ed_ingresos")

    with tab_descuentos:
        if not conceptos_descuentos:
            st.info("No hay conceptos de descuento creados. Puede agregarlos en el 'Maestro de Conceptos'.")
            df_descuentos_edit = df_descuentos
        else:
            df_descuentos_edit = st.data_editor(df_descuentos, disabled=["DNI", "Nombres y Apellidos"], num_rows="fixed", use_container_width=True, hide_index=True, column_config=col_config_moneda, key="ed_descuentos")

    st.markdown("---")
    
    # 5. GUARDADO POR PERIODO
    if st.button(f"💾 Guardar Variables de {periodo_key}", type="primary", use_container_width=True):
        df_consolidado = df_tiempos_edit.copy()
        
        for col in conceptos_ingresos: df_consolidado[col] = df_ingresos_edit[col]
        for col in conceptos_descuentos: df_consolidado[col] = df_descuentos_edit[col]
            
        df_consolidado = df_consolidado.rename(columns={"DNI": "Num. Doc."})
        
        # Guardamos específicamente en el "cajón" de este mes
        st.session_state['variables_por_periodo'][periodo_key] = df_consolidado
        st.success(f"✅ ¡Variables de **{periodo_key}** guardadas exitosamente!")