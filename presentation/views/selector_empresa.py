import streamlit as st
from infrastructure.database.connection import get_db
from infrastructure.database.models import Empresa
import datetime

def render():
    st.title("🗄️ Panel de Control Multi-Empresa")
    st.markdown("Seleccione el cliente (empresa) con el que desea trabajar en esta sesión.")
    st.markdown("---")

    # Conectar a la Nube (Neon)
    db = next(get_db())
    
    col_lista, col_form = st.columns([2, 1])
    
    with col_lista:
        st.subheader("Empresas Registradas")
        
        empresas_db = db.query(Empresa).all()
        
        if not empresas_db:
            st.info("No hay empresas registradas. Utilice el panel derecho para crear la primera.")
        else:
            for emp in empresas_db:
                with st.container(border=True):
                    st.markdown(f"#### {emp.razon_social}")
                    st.markdown(f"**RUC:** {emp.ruc} | **Régimen:** {emp.regimen_laboral}")
                    
                    if st.button("Seleccionar Empresa", key=f"sel_{emp.id}"):
                        st.session_state['empresa_activa_id'] = emp.id
                        st.session_state['empresa_activa_nombre'] = emp.razon_social
                        st.session_state['empresa_activa_ruc'] = emp.ruc
                        st.session_state['empresa_activa_regimen'] = emp.regimen_laboral
                        st.session_state['empresa_acogimiento'] = emp.fecha_acogimiento
                        st.rerun() 
                        
    with col_form:
        st.subheader("Nueva Empresa")
        
        # Al no usar st.form, la interfaz reacciona en tiempo real a las selecciones
        ruc = st.text_input("RUC (11 dígitos)*", max_chars=11)
        razon_social = st.text_input("Razón Social*")
        
        # --- NUEVO: SELECTOR DE RÉGIMEN LABORAL ---
        regimenes = ["Régimen General", "Régimen Especial - Micro Empresa", "Régimen Especial - Pequeña Empresa"]
        regimen_sel = st.selectbox("Régimen Laboral*", regimenes)
        
        # Link sutil y profesional
        st.markdown(
            "<a href='https://apps.trabajo.gob.pe/consultas-remype/app/index.html' target='_blank' style='font-size: 0.85em; color: #7F8C8D; text-decoration: none;'>🔍 <i>Verificar acreditación REMYPE (MTPE)</i></a>", 
            unsafe_allow_html=True
        )
        st.markdown("<br/>", unsafe_allow_html=True)
        
        # Lógica Condicional: Mostrar fecha solo si es MYPE
        fecha_acogimiento_sel = None
        if regimen_sel != "Régimen General":
            fecha_acogimiento_sel = st.date_input("Fecha de Acogimiento al Régimen MYPE*")
            st.caption("⚠️ Los trabajadores que ingresaron ANTES de esta fecha conservarán los beneficios del Régimen General de forma irrenunciable.")
            st.markdown("<br/>", unsafe_allow_html=True)

        representante = st.text_input("Representante Legal")
        correo = st.text_input("Correo Electrónico")
        domicilio = st.text_area("Domicilio Fiscal")
        
        st.markdown("*Campos obligatorios*")
        
        if st.button("➕ Registrar Empresa", type="primary", use_container_width=True):
            if len(ruc) != 11 or not ruc.isdigit():
                st.error("El RUC debe tener 11 números.")
            elif not razon_social:
                st.error("La Razón Social es obligatoria.")
            elif regimen_sel != "Régimen General" and not fecha_acogimiento_sel:
                st.error("Debe indicar la Fecha de Acogimiento al REMYPE.")
            else:
                existe = db.query(Empresa).filter(Empresa.ruc == ruc).first()
                if existe:
                    st.error("Ya existe una empresa con este RUC.")
                else:
                    nueva_emp = Empresa(
                        ruc=ruc, 
                        razon_social=razon_social, 
                        representante_legal=representante, 
                        correo_electronico=correo, 
                        domicilio=domicilio,
                        regimen_laboral=regimen_sel,
                        fecha_acogimiento=fecha_acogimiento_sel
                    )
                    db.add(nueva_emp)
                    db.commit()
                    st.success("¡Empresa registrada exitosamente!")
                    st.rerun()