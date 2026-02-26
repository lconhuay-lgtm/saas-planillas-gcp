import streamlit as st

def inicializar_estado():
    """Inicializa las variables globales de la sesión si no existen."""
    if 'empresa_activa_id' not in st.session_state:
        st.session_state['empresa_activa_id'] = None
    
    if 'empresa_activa_nombre' not in st.session_state:
        st.session_state['empresa_activa_nombre'] = None

def set_empresa_activa(empresa_id: int, empresa_nombre: str):
    """Guarda la empresa seleccionada en la memoria temporal."""
    st.session_state['empresa_activa_id'] = empresa_id
    st.session_state['empresa_activa_nombre'] = empresa_nombre

def limpiar_empresa_activa():
    """Cierra la sesión de la empresa actual."""
    st.session_state['empresa_activa_id'] = None
    st.session_state['empresa_activa_nombre'] = None