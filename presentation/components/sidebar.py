import streamlit as st

def render_sidebar():
    with st.sidebar:
        st.markdown("### 💼 ERP Contable SaaS")
        st.markdown("---")
        
        empresa_id = st.session_state.get('empresa_activa_id')
        empresa_nombre = st.session_state.get('empresa_activa_nombre')
        
        # EL CANDADO: Si no hay empresa activa, solo mostramos el Selector
        if not empresa_id:
            st.warning("⚠️ Seleccione una empresa para habilitar los módulos.")
            menu = st.radio(
                "Navegación",
                ["Selector de Empresa"],
                label_visibility="collapsed"
            )
            return menu
            
        # SI YA HAY EMPRESA: Mostramos los módulos y el botón para cambiar de empresa
        else:
            st.success(f"🏢 Empresa Activa:\n**{empresa_nombre}**")
            
            if st.button("🔄 Cambiar de Empresa", use_container_width=True):
                # Limpiar memoria y recargar
                st.session_state['empresa_activa_id'] = None
                st.session_state['empresa_activa_nombre'] = None
                st.rerun()
                
            st.markdown("---")
            menu = st.radio(
                "Navegación",
                (
                    "Dashboard Principal",
                    "Parámetros Legales",
                    "Maestro de Personal",
                    "Maestro de Conceptos",
                    "Ingreso de Asistencias",
                    "Cálculo de Planilla",
                    "Emisión de Boletas",
                    "Reportería",
                ),
                label_visibility="collapsed"
            )
            return menu