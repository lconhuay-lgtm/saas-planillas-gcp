import streamlit as st
import pandas as pd
from infrastructure.database.connection import get_db
from infrastructure.database.models import Empresa

def render():
    st.title("🏢 Panel de Control - Selección de Empresa")
    st.markdown("Bienvenido al Sistema de Planillas SaaS. Seleccione o registre una empresa para comenzar.")
    st.markdown("---")

    # 1. ABRIR CONEXIÓN A LA BASE DE DATOS NEON
    db = next(get_db())

    tab1, tab2 = st.tabs(["📋 Seleccionar Empresa Activa", "➕ Registrar Nueva Empresa"])

    # --- PESTAÑA 1: LISTADO Y SELECCIÓN ---
    with tab1:
        st.subheader("Directorio de Empresas")
        
        # Consultar todas las empresas directamente a la Nube (Neon)
        empresas_db = db.query(Empresa).all()
        
        if not empresas_db:
            st.info("No hay empresas registradas en la Base de Datos. Vaya a la pestaña 'Registrar Nueva Empresa'.")
        else:
            # Construir la tabla visual
            data = []
            for emp in empresas_db:
                data.append({
                    "RUC": emp.ruc,
                    "Razón Social": emp.razon_social,
                    "Representante Legal": emp.representante_legal,
                    "Correo Electrónico": emp.correo_electronico,
                    "Fecha Registro": emp.fecha_registro.strftime("%d/%m/%Y") if emp.fecha_registro else ""
                })
            df_empresas = pd.DataFrame(data)
            st.dataframe(df_empresas, use_container_width=True, hide_index=True)

            st.markdown("### Seleccionar Empresa para Trabajar")
            opciones = {f"{e.ruc} - {e.razon_social}": e for e in empresas_db}
            seleccion = st.selectbox("Seleccione la empresa a gestionar:", list(opciones.keys()))
            
            if st.button("🚀 Activar Empresa", type="primary"):
                emp_seleccionada = opciones[seleccion]
                
                # Guardamos en la memoria temporal (Session State) la empresa activa 
                # para que los otros módulos sepan con quién estamos trabajando.
                st.session_state['empresa_activa_id'] = emp_seleccionada.id
                st.session_state['empresa_activa_nombre'] = emp_seleccionada.razon_social
                st.session_state['empresa_activa_ruc'] = emp_seleccionada.ruc
                st.session_state['empresa_activa_domicilio'] = emp_seleccionada.domicilio
                
                st.success(f"✅ Empresa **{emp_seleccionada.razon_social}** activada correctamente.")
                st.info("👈 Ya puede navegar por los módulos del menú lateral para gestionar sus planillas.")

    # --- PESTAÑA 2: GUARDAR EN LA BASE DE DATOS ---
    with tab2:
        st.subheader("Formulario de Registro Corporativo")
        st.markdown("Los datos ingresados aquí se sincronizarán directamente con el servidor en la nube y aparecerán en los encabezados de las Boletas de Pago.")
        
        with st.form("form_nueva_empresa"):
            col1, col2 = st.columns(2)
            with col1:
                ruc = st.text_input("RUC (11 dígitos)*", max_chars=11)
                razon_social = st.text_input("Razón Social / Nombre Comercial*")
                correo = st.text_input("Correo Electrónico Corporativo")
            with col2:
                representante = st.text_input("Nombre del Representante Legal")
                domicilio = st.text_area("Domicilio Fiscal Completo", height=110)
            
            st.markdown("*Campos obligatorios*")
            submitted = st.form_submit_button("💾 Guardar Empresa en la Nube", type="primary", use_container_width=True)
            
            if submitted:
                if len(ruc) != 11 or not ruc.isdigit():
                    st.error("❌ El RUC debe tener exactamente 11 dígitos numéricos.")
                elif not razon_social:
                    st.error("❌ La Razón Social es obligatoria.")
                else:
                    # Validar que el RUC no esté duplicado en la base de datos
                    existe = db.query(Empresa).filter(Empresa.ruc == ruc).first()
                    if existe:
                        st.error(f"❌ Ya existe una empresa registrada con el RUC {ruc}.")
                    else:
                        # 2. INSERCIÓN DE DATOS MEDIANTE ORM
                        nueva_emp = Empresa(
                            ruc=ruc,
                            razon_social=razon_social,
                            domicilio=domicilio,
                            representante_legal=representante,
                            correo_electronico=correo
                        )
                        db.add(nueva_emp)
                        db.commit() # El "commit" es lo que graba físicamente en Neon
                        
                        st.success(f"🎉 ¡Éxito! La empresa **{razon_social}** se guardó permanentemente en la Base de Datos.")
                        st.rerun() # Recarga la página para que aparezca en la lista