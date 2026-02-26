import streamlit as st
from presentation.session_state import set_empresa_activa
# from infrastructure.database.db_manager import get_db_session
# from infrastructure.repositories.repo_empresa import EmpresaRepository

def render():
    st.title("🗄️ Panel de Control Multi-Empresa")
    st.markdown("Seleccione el cliente (empresa) con el que desea trabajar en esta sesión.")
    st.markdown("---")

    # MOCK DE DATOS (Hasta que conectemos SQLAlchemy en vivo)
    # En producción, esto se reemplaza por: repo.get_all()
    empresas_mock = [
        {"id": 1, "ruc": "20392988565", "razon_social": "CONVERSIONES SAN JOSE SAC", "regimen": "GENERAL"},
        {"id": 2, "ruc": "20555555555", "razon_social": "TEXTILES LIMA EIRL", "regimen": "MYPE - PEQUEÑA"},
    ]

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Empresas Registradas")
        # Mostrar las empresas en formato de tarjetas corporativas
        for emp in empresas_mock:
            with st.container():
                # Diseño de tarjeta usando markdown y CSS inline
                st.markdown(f"""
                <div style="border: 1px solid #e0e0e0; border-radius: 8px; padding: 15px; margin-bottom: 10px; background-color: #f9f9f9;">
                    <h4 style="margin: 0; color: #1f77b4;">{emp['razon_social']}</h4>
                    <p style="margin: 5px 0 0 0; color: #555;"><strong>RUC:</strong> {emp['ruc']} | <strong>Régimen:</strong> {emp['regimen']}</p>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button(f"Seleccionar", key=f"btn_emp_{emp['id']}"):
                    set_empresa_activa(emp['id'], emp['razon_social'])
                    st.toast(f"Sesión iniciada en {emp['razon_social']}", icon="✅")
                    st.rerun() # Recarga la app para habilitar el menú lateral

    with col2:
        st.subheader("Nueva Empresa")
        with st.form("form_nueva_empresa"):
            ruc = st.text_input("RUC (11 dígitos)")
            razon = st.text_input("Razón Social")
            regimen = st.selectbox("Régimen Laboral", ["GENERAL", "PEQUEÑA EMPRESA", "MICROEMPRESA"])
            submit = st.form_submit_button("➕ Registrar Empresa", use_container_width=True)
            
            if submit:
                # Aquí iría la lógica de BD: repo.create(ruc, razon, regimen)
                st.success("Empresa registrada con éxito (Simulado).")