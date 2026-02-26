import streamlit as st
from presentation.session_state import limpiar_empresa_activa

def render_sidebar():
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/3135/3135679.png", width=60)
        st.markdown("### ERP Contable")
        st.markdown("---")

        if st.session_state.get('empresa_activa_id'):
            st.success(f"🏢 **Empresa Activa:**\n\n{st.session_state['empresa_activa_nombre']}")
            
            st.markdown("### Módulos")
            menu = st.radio(
                "Navegación",
                ("Dashboard", "Parámetros Legales", "Maestro de Personal","Maestro de Conceptos" , "Ingreso de Asistencias", "Cálculo de Planilla", "Emisión de Boletas"),
                label_visibility="collapsed"
            )

            st.markdown("---")
            if st.button("🚪 Cambiar de Empresa", use_container_width=True):
                limpiar_empresa_activa()
                st.rerun()
                
            return menu
        else:
            st.warning("⚠️ Seleccione una empresa para habilitar los módulos.")
            return "Selector"