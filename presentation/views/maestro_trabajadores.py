import streamlit as st
import pandas as pd
from datetime import date
from infrastructure.services.sunat_api import consultar_dni_sunat

def render():
    empresa_id = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')

    if not empresa_id:
        st.error("⚠️ Acceso denegado. Seleccione una empresa en el Dashboard.")
        return

    st.title("👥 Maestro de Trabajadores")
    st.markdown(f"Gestionando planilla de: **{empresa_nombre}**")
    st.markdown("---")

    # Columna CCI agregada
    columnas_df = [
        "Tipo Doc.", "Num. Doc.", "Nombres y Apellidos", "Fecha Nac.", 
        "Cargo", "Fecha Ingreso", "Situación", "Sueldo Base", 
        "Banco", "Cuenta Bancaria", "CCI", 
        "Asig. Fam.", "EPS", "Sistema Pensión", "Comisión AFP", "CUSPP"
    ]
    
    if 'trabajadores_mock' not in st.session_state:
        st.session_state['trabajadores_mock'] = pd.DataFrame(columns=columnas_df)

    if 'temp_doc' not in st.session_state: st.session_state['temp_doc'] = ""
    if 'temp_nombres' not in st.session_state: st.session_state['temp_nombres'] = ""
    if 'msg_exito_maestro' not in st.session_state: st.session_state['msg_exito_maestro'] = None

    tab1, tab2 = st.tabs(["📋 Directorio del Personal", "➕ Registrar Nuevo Trabajador"])

    with tab1:
        st.subheader("Personal Registrado")
        df_editado = st.data_editor(
            st.session_state['trabajadores_mock'], num_rows="dynamic", use_container_width=True, hide_index=True
        )
        if st.button("💾 Guardar Cambios en Grilla", type="primary"):
            st.session_state['trabajadores_mock'] = df_editado
            st.success("Base de datos actualizada correctamente.")

    with tab2:
        st.subheader("Ficha de Ingreso de Personal")
        
        if st.session_state['msg_exito_maestro']:
            st.success(st.session_state['msg_exito_maestro'])
            st.session_state['msg_exito_maestro'] = None 

        st.markdown("**Consulta Rápida de Identidad (RENIEC/SUNAT)**")
        col_search_1, col_search_2 = st.columns([1, 2])
        with col_search_1:
            doc_busqueda = st.text_input("Ingrese DNI para buscar", value=st.session_state['temp_doc'], max_chars=8, key="input_doc_search")
            if st.button("🔍 Buscar DNI", use_container_width=True):
                with st.spinner('Consultando servidor...'):
                    resultado = consultar_dni_sunat(doc_busqueda)
                    if resultado['success']:
                        st.session_state['temp_doc'] = doc_busqueda
                        st.session_state['temp_nombres'] = resultado['nombres']
                        st.rerun()
                    else:
                        st.error(resultado['mensaje'])
        st.markdown("---")
        
        st.markdown("### Detalles del Trabajador")
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("##### 👤 Datos Personales")
            tipo_doc = st.selectbox("Tipo de Documento", ["DNI", "CE (Carné de Extranjería)", "Pasaporte", "PTP/CPP"])
            numero_doc = st.text_input("Número de Documento", value=st.session_state['temp_doc'])
            nombres = st.text_input("Nombres y Apellidos Completos", value=st.session_state['temp_nombres'])
            fecha_nac = st.date_input("Fecha de Nacimiento", value=date(1990, 1, 1), min_value=date(1940, 1, 1))
            
            st.markdown("##### 🏢 Datos Laborales y Pago")
            cargo = st.text_input("Posición / Cargo")
            fecha_ing = st.date_input("Fecha de Ingreso a Planilla", value=date.today())
            situacion = st.selectbox("Situación Actual", ["ACTIVO", "SUBSIDIADO", "CESE"])
            sueldo = st.number_input("Sueldo Base (S/)", min_value=1025.0, step=100.0)
            
            bancos_lista = ["BCP", "BBVA", "Interbank", "Scotiabank", "BanBif", "Banco de la Nación", "Caja Huancayo", "Caja Arequipa", "Otros", "Efectivo/Cheque"]
            banco = st.selectbox("Entidad Bancaria", bancos_lista)
            cuenta = st.text_input("Número de Cuenta Bancaria")
            cci = st.text_input("Código de Cuenta Interbancaria (CCI)", max_chars=20, help="Debe contener exactamente 20 dígitos numéricos.")
        
        with col2:
            st.markdown("##### 🏦 Datos Previsionales")
            sistema_pension = st.selectbox("Sistema de Pensión", ["NO AFECTO", "ONP", "AFP HABITAT", "AFP INTEGRA", "AFP PRIMA", "AFP PROFUTURO"], index=1)
            
            es_afp = sistema_pension.startswith("AFP")
            
            tipo_comision = st.selectbox("Tipo de Comisión", ["MIXTA", "FLUJO", "N/A"], disabled=not es_afp, index=0 if es_afp else 2)
            cuspp = st.text_input("Código CUSPP", disabled=not es_afp)
            
            if es_afp:
                st.markdown(
                    "<div style='margin-top: -15px; margin-bottom: 15px; text-align: right;'>"
                    "<a href='https://servicios.sbs.gob.pe/ReporteSituacionPrevisional/Afil_Consulta.aspx' "
                    "target='_blank' style='font-size: 12px; color: #888; text-decoration: none;'>🔍 Buscar CUSPP en SBS</a></div>", 
                    unsafe_allow_html=True
                )
            else:
                st.markdown("<div style='margin-top: -15px; margin-bottom: 15px;'>&nbsp;</div>", unsafe_allow_html=True)
            
            st.markdown("##### 🛡️ Beneficios y Seguros")
            asig_fam = st.checkbox("Percibe Asignación Familiar (10% RMV)")
            eps = st.checkbox("Afiliado a EPS (Aporte EsSalud 6.75%)")
            
        st.markdown("---")
        if st.button("Registrar Trabajador", type="primary", use_container_width=True):
            if not numero_doc or not nombres or not cargo:
                st.error("❌ Complete Documento, Nombres y Cargo.")
            elif numero_doc in st.session_state['trabajadores_mock']['Num. Doc.'].values:
                st.error(f"❌ ERROR: El documento {numero_doc} ya se encuentra registrado.") 
            elif es_afp and not cuspp:
                st.warning("⚠️ Ingrese el código CUSPP.")
            # NUEVA VALIDACIÓN ESTRICTA DEL CCI
            elif cci and (len(cci) != 20 or not cci.isdigit()):
                st.error("❌ ERROR: El Código de Cuenta Interbancaria (CCI) debe contener exactamente 20 dígitos numéricos.")
            else:
                nuevo_registro = {
                    "Tipo Doc.": tipo_doc, "Num. Doc.": numero_doc, "Nombres y Apellidos": nombres,
                    "Fecha Nac.": fecha_nac, "Cargo": cargo, "Fecha Ingreso": fecha_ing,
                    "Situación": situacion, "Sueldo Base": sueldo, 
                    "Banco": banco, "Cuenta Bancaria": cuenta, "CCI": cci,
                    "Asig. Fam.": "Sí" if asig_fam else "No",
                    "EPS": "Sí" if eps else "No", "Sistema Pensión": sistema_pension,
                    "Comisión AFP": tipo_comision if es_afp else "N/A", "CUSPP": cuspp if es_afp else "N/A"
                }
                
                df_temp = pd.DataFrame([nuevo_registro])
                st.session_state['trabajadores_mock'] = pd.concat([st.session_state['trabajadores_mock'], df_temp], ignore_index=True)
                
                st.session_state['temp_doc'] = ""
                st.session_state['temp_nombres'] = ""
                st.session_state['msg_exito_maestro'] = f"✅ Trabajador {nombres} registrado correctamente."
                st.rerun()