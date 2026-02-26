import streamlit as st
import pandas as pd

def inyectar_conceptos_por_defecto(empresa_id, df_actual):
    """
    Motor de Pre-Carga (Seeder). 
    Revisa si la empresa no tiene conceptos y le inyecta los 4 obligatorios de Ley.
    """
    # Si la empresa ya tiene conceptos creados, no hacemos nada
    if not df_actual[df_actual['Empresa_ID'] == empresa_id].empty:
        return df_actual
        
    # Definición estricta de Ley Peruana
    conceptos_ley = [
        {
            "Empresa_ID": empresa_id,
            "Nombre del Concepto": "SUELDO BASICO",
            "Tipo": "INGRESO",
            "Afecto AFP/ONP": True,
            "Afecto 5ta Cat.": True,
            "Afecto EsSalud": True,
            "Computable CTS": True,
            "Computable Grati": True
        },
        {
            "Empresa_ID": empresa_id,
            "Nombre del Concepto": "ASIGNACION FAMILIAR",
            "Tipo": "INGRESO",
            "Afecto AFP/ONP": True,
            "Afecto 5ta Cat.": True,
            "Afecto EsSalud": True,
            "Computable CTS": True,
            "Computable Grati": True
        },
        {
            "Empresa_ID": empresa_id,
            "Nombre del Concepto": "GRATIFICACION (JUL/DIC)",
            "Tipo": "INGRESO",
            "Afecto AFP/ONP": False,
            "Afecto 5ta Cat.": True,  # Sí paga 5ta
            "Afecto EsSalud": False,
            "Computable CTS": False,
            "Computable Grati": False
        },
        {
            "Empresa_ID": empresa_id,
            "Nombre del Concepto": "BONIFICACION EXTRAORDINARIA LEY 29351 (9%)",
            "Tipo": "INGRESO",
            "Afecto AFP/ONP": False,
            "Afecto 5ta Cat.": True, # Sí paga 5ta
            "Afecto EsSalud": False,
            "Computable CTS": False,
            "Computable Grati": False
        }
    ]
    
    df_nuevos = pd.DataFrame(conceptos_ley)
    return pd.concat([df_actual, df_nuevos], ignore_index=True)


def render():
    empresa_id = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')

    if not empresa_id:
        st.error("⚠️ Acceso denegado. Seleccione una empresa en el Dashboard.")
        return

    st.title("🧩 Maestro de Conceptos Remunerativos")
    st.markdown(f"Defina los ingresos y descuentos personalizados para: **{empresa_nombre}**")
    st.markdown("---")

    columnas_conceptos = [
        "Empresa_ID", "Nombre del Concepto", "Tipo", 
        "Afecto AFP/ONP", "Afecto 5ta Cat.", "Afecto EsSalud", 
        "Computable CTS", "Computable Grati"
    ]

    if 'conceptos_mock' not in st.session_state:
        st.session_state['conceptos_mock'] = pd.DataFrame(columns=columnas_conceptos)

    # 1. EJECUTAR EL MOTOR DE PRE-CARGA
    # Verificamos si hay que inyectar los datos por defecto para esta empresa
    st.session_state['conceptos_mock'] = inyectar_conceptos_por_defecto(
        empresa_id, 
        st.session_state['conceptos_mock']
    )

    # 2. Filtrar solo los conceptos de la EMPRESA ACTIVA (Aislamiento Multi-Tenant)
    df_todos = st.session_state['conceptos_mock']
    df_empresa = df_todos[df_todos['Empresa_ID'] == empresa_id].copy()

    if 'msg_exito_concepto' in st.session_state and st.session_state['msg_exito_concepto']:
        st.success(st.session_state['msg_exito_concepto'])
        st.session_state['msg_exito_concepto'] = None

    tab1, tab2 = st.tabs(["📋 Conceptos de la Empresa", "➕ Crear Nuevo Concepto (Bonos/Dsctos)"])

    with tab1:
        st.subheader("Catálogo de Conceptos Activos")
        st.markdown("Los conceptos universales de ley han sido pre-cargados automáticamente. Puede agregar conceptos personalizados desde la siguiente pestaña.")
        
        # Ocultamos la columna Empresa_ID para que la interfaz sea limpia
        df_visual = df_empresa.drop(columns=['Empresa_ID'])
        
        # Bloqueamos el nombre de los conceptos por defecto para que no los borren por error
        # pero permitimos que sigan agregando nuevos o editando los checks si hay algún régimen especial
        df_editado = st.data_editor(
            df_visual,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            disabled=["Nombre del Concepto", "Tipo"] # Protege el catálogo base
        )
        
        if st.button("💾 Guardar Cambios en Grilla", type="primary"):
            df_editado['Empresa_ID'] = empresa_id
            df_otras_empresas = df_todos[df_todos['Empresa_ID'] != empresa_id]
            st.session_state['conceptos_mock'] = pd.concat([df_otras_empresas, df_editado], ignore_index=True)
            st.success("✅ Reglas de conceptos actualizadas correctamente.")

    with tab2:
        st.subheader("Configurador de Reglas Laborales y Tributarias")
        
        with st.form("form_nuevo_concepto"):
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.markdown("**1. Datos Básicos**")
                nombre = st.text_input("Nombre del Concepto", placeholder="Ej: Bono de Productividad, Reintegro...")
                tipo = st.selectbox("Tipo de Concepto", ["INGRESO", "DESCUENTO"])
            
            with col2:
                st.markdown("**2. Afectaciones Tributarias (Marque lo que aplique)**")
                afecto_afp = st.checkbox("Afecto a Retención AFP/ONP", value=True)
                afecto_5ta = st.checkbox("Afecto a Impuesto 5ta Categoría", value=True)
                afecto_essalud = st.checkbox("Afecto a Aporte EsSalud (9%)", value=True)
                
                st.markdown("**3. Beneficios Sociales**")
                comp_cts = st.checkbox("Base Computable para CTS", value=False)
                comp_grati = st.checkbox("Base Computable para Gratificación", value=False)
                
            st.markdown("---")
            submit = st.form_submit_button("Crear Concepto", type="primary", use_container_width=True)
            
            if submit:
                if not nombre:
                    st.error("❌ El nombre del concepto es obligatorio.")
                elif nombre.upper() in df_empresa['Nombre del Concepto'].values:
                    st.error(f"❌ El concepto '{nombre.upper()}' ya existe en esta empresa.")
                else:
                    nuevo_concepto = {
                        "Empresa_ID": empresa_id,
                        "Nombre del Concepto": nombre.upper(),
                        "Tipo": tipo,
                        "Afecto AFP/ONP": afecto_afp,
                        "Afecto 5ta Cat.": afecto_5ta,
                        "Afecto EsSalud": afecto_essalud,
                        "Computable CTS": comp_cts,
                        "Computable Grati": comp_grati
                    }
                    st.session_state['conceptos_mock'] = pd.concat([st.session_state['conceptos_mock'], pd.DataFrame([nuevo_concepto])], ignore_index=True)
                    st.session_state['msg_exito_concepto'] = f"✅ Concepto '{nombre.upper()}' creado exitosamente."
                    st.rerun()