import streamlit as st
import pandas as pd
import datetime
from infrastructure.database.connection import get_db
from infrastructure.database.models import Trabajador

def determinar_regimen_trabajador(fecha_ingreso, regimen_empresa, fecha_acogimiento):
    """Lógica legal de protección de derechos adquiridos"""
    if regimen_empresa == "Régimen General" or not fecha_acogimiento:
        return "Régimen General"
    if fecha_ingreso < fecha_acogimiento:
        return "Régimen General (Derechos Adquiridos)"
    return regimen_empresa

def consultar_dni_automatico(dni):
    """Simulación de API de Reniec/Sunat"""
    # En el futuro, aquí conectas con: requests.get(f"tu_api_url/{dni}")
    base_datos_ficticia = {
        "12345678": {"nombres": "SOTO MENDOZA, RICARDO DANIEL", "nacimiento": datetime.date(1985, 5, 20)},
        "87654321": {"nombres": "ALVAREZ RUIZ, MARIA ELENA", "nacimiento": datetime.date(1992, 10, 15)},
    }
    return base_datos_ficticia.get(dni, None)

def render():
    empresa_id = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')
    regimen_empresa = st.session_state.get('empresa_activa_regimen', 'Régimen General')
    fecha_acogimiento = st.session_state.get('empresa_acogimiento', None)

    if not empresa_id:
        st.error("⚠️ Seleccione una empresa en el Panel de Control para continuar.")
        return

    st.title("👥 Maestro de Personal")
    st.markdown(f"**Empresa:** {empresa_nombre} | **Régimen:** {regimen_empresa}")
    st.markdown("---")

    db = next(get_db())
    tab_lista, tab_nuevo = st.tabs(["📋 Directorio de Personal", "➕ Alta de Trabajador"])

    # --- PESTAÑA 1: LISTADO ---
    with tab_lista:
        trabajadores_db = db.query(Trabajador).filter(Trabajador.empresa_id == empresa_id).all()
        if not trabajadores_db:
            st.info("No hay trabajadores registrados.")
        else:
            data = []
            for t in trabajadores_db:
                reg = determinar_regimen_trabajador(t.fecha_ingreso, regimen_empresa, fecha_acogimiento)
                data.append({
                    "DNI/CE": t.num_doc,
                    "Apellidos y Nombres": t.nombres,
                    "Cargo": t.cargo,
                    "Fecha Ingreso": t.fecha_ingreso.strftime('%d/%m/%Y'),
                    "Régimen": reg,
                    "Sueldo Base": f"S/ {t.sueldo_base:,.2f}"
                })
            st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

    # --- PESTAÑA 2: ALTA CON BÚSQUEDA AUTOMÁTICA ---
    with tab_nuevo:
        st.subheader("1. Identidad y Datos Básicos")
        
        c1, c2, c3, c4 = st.columns([1, 1.5, 3, 1.5])
        t_doc = c1.selectbox("Tipo Doc.", ["DNI", "CE", "PTP"])
        n_doc = c2.text_input("Número de Documento", max_chars=12, help="Escriba 8 dígitos para búsqueda automática")
        
        # Lógica de Búsqueda Automática
        nombres_auto = ""
        fecha_nac_auto = datetime.date(1990, 1, 1)
        
        if t_doc == "DNI" and len(n_doc) == 8:
            resultado = consultar_dni_automatico(n_doc)
            if resultado:
                nombres_auto = resultado["nombres"]
                fecha_nac_auto = resultado["nacimiento"]
                st.toast(f"✅ Datos de {n_doc} encontrados", icon="👤")
        
        nombres = c3.text_input("Apellidos y Nombres*", value=nombres_auto.upper())
        f_nac = c4.date_input("Fecha Nacimiento*", value=fecha_nac_auto)

        st.subheader("2. Información Laboral")
        cl1, cl2, cl3 = st.columns(3)
        cargo = cl1.text_input("Cargo / Puesto")
        f_ingreso = cl2.date_input("Fecha de Ingreso*", value=datetime.date.today())
        s_base = cl3.number_input("Sueldo Mensual (S/)*", min_value=1025.0, step=50.0)

        st.subheader("3. Régimen Pensionario")
        p1, p2, p3 = st.columns(3)
        s_pension = p1.selectbox("Sistema de Pensión", ["ONP", "AFP INTEGRA", "AFP PRIMA", "AFP PROFUTURO", "AFP HABITAT", "NO AFECTO"])
        
        # Bloqueo dinámico AFP
        es_afp = s_pension.startswith("AFP")
        t_comision = p2.selectbox("Tipo de Comisión", ["FLUJO", "MIXTA"], disabled=not es_afp)
        cuspp = p3.text_input("CUSPP", disabled=not es_afp)

        st.subheader("4. Información de Pago")
        b1, b2, b3 = st.columns(3)
        banco_sel = b1.selectbox("Banco", ["BCP", "BBVA", "INTERBANK", "SCOTIABANK", "BANBIF", "EFECTIVO/CHEQUE"])
        
        # Bloqueo dinámico Banco
        es_banco = banco_sel != "EFECTIVO/CHEQUE"
        n_cuenta = b2.text_input("Número de Cuenta", disabled=not es_banco)
        cci = b3.text_input("CCI (20 dígitos)", max_chars=20, disabled=not es_banco)

        st.markdown("---")
        col_opt1, col_opt2 = st.columns(2)
        a_fam = col_opt1.checkbox("Asignación Familiar")
        eps_afecto = col_opt2.checkbox("Afecto a EPS")

        if st.button("💾 Registrar e Inscribir en la Nube", type="primary", use_container_width=True):
            if not n_doc or not nombres or s_base < 1025:
                st.error("❌ Complete los campos obligatorios correctamente.")
            else:
                try:
                    nuevo_t = Trabajador(
                        empresa_id=empresa_id,
                        tipo_doc=t_doc,
                        num_doc=n_doc,
                        nombres=nombres.upper(),
                        fecha_nac=f_nac,
                        fecha_ingreso=f_ingreso,
                        cargo=cargo,
                        sueldo_base=s_base,
                        asig_fam=a_fam,
                        sistema_pension=s_pension,
                        comision_afp=t_comision if es_afp else "NO APLICA",
                        cuspp=cuspp if es_afp else "",
                        banco=banco_sel,
                        cuenta_bancaria=n_cuenta if es_banco else "",
                        cci=cci if es_banco else "",
                        eps=eps_afecto,
                        situacion="ACTIVO"
                    )
                    db.add(nuevo_t)
                    db.commit()
                    st.balloons()
                    st.success(f"✅ ¡Trabajador **{nombres.upper()}** registrado exitosamente!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al guardar: {e}")