import streamlit as st
from datetime import date

# Diccionario de meses para el selector
MESES = ["01 - Enero", "02 - Febrero", "03 - Marzo", "04 - Abril", "05 - Mayo", "06 - Junio", 
         "07 - Julio", "08 - Agosto", "09 - Septiembre", "10 - Octubre", "11 - Noviembre", "12 - Diciembre"]

def render():
    st.title("⚙️ Parámetros Legales y Tributarios (Globales)")
    st.markdown("""
    Configure las tasas macroeconómicas y tributarias por **Periodo (Mes/Año)**. 
    **Importante:** Al guardar un periodo, el motor de cálculo lo utilizará para procesar las planillas exactas de ese mes, garantizando la inmutabilidad histórica.
    """)
    st.markdown("---")

    # 1. Inicialización de la memoria global para Parámetros (Ahora es un Diccionario Histórico)
    if 'parametros_globales' not in st.session_state:
        st.session_state['parametros_globales'] = {}
        st.session_state['periodos_configurados'] = [] # Lista para saber qué meses ya están listos
        
    # Valores por defecto (Fallback) en caso sea el primer mes que se configura en el sistema
    default_p = {
        "rmv": 1025.0, "uit": 5350.0, "tope_afp": 13583.51, "tasa_onp": 13.0, "tasa_essalud": 9.0, "tasa_eps": 6.75,
        "afp_habitat_aporte": 10.0, "afp_habitat_prima": 1.84, "afp_habitat_flujo": 1.47, "afp_habitat_mixta": 0.23,
        "afp_integra_aporte": 10.0, "afp_integra_prima": 1.84, "afp_integra_flujo": 1.55, "afp_integra_mixta": 0.0,
        "afp_prima_aporte": 10.0, "afp_prima_prima": 1.84, "afp_prima_flujo": 1.60, "afp_prima_mixta": 0.18,
        "afp_profuturo_aporte": 10.0, "afp_profuturo_prima": 1.84, "afp_profuturo_flujo": 1.69, "afp_profuturo_mixta": 0.67
    }

    # 2. SELECTOR DE PERIODO Y COPIA RÁPIDA
    st.subheader("Selección de Periodo a Configurar")
    col_m, col_a, col_btn = st.columns([2, 1, 2])
    
    # Por defecto, seleccionamos el mes y año actual
    mes_actual_idx = date.today().month - 1
    mes_seleccionado = col_m.selectbox("Mes", MESES, index=mes_actual_idx)
    anio_seleccionado = col_a.selectbox("Año", [2025, 2026, 2027, 2028], index=1) # Por defecto 2026
    
    periodo_key = f"{mes_seleccionado[:2]}-{anio_seleccionado}" # Genera la llave: Ej. "01-2026"
    
    # Lógica para identificar el mes anterior matemáticamente
    idx_sel = MESES.index(mes_seleccionado)
    if idx_sel == 0:
        mes_ant_key = f"12-{anio_seleccionado - 1}"
    else:
        mes_ant_key = f"{MESES[idx_sel - 1][:2]}-{anio_seleccionado}"

    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("📋 Copiar tasas del mes anterior", use_container_width=True, help=f"Copia las tasas de {mes_ant_key}"):
            if mes_ant_key in st.session_state['parametros_globales']:
                # Copiamos los datos del mes anterior al mes actual
                st.session_state['parametros_globales'][periodo_key] = st.session_state['parametros_globales'][mes_ant_key].copy()
                st.success(f"✅ Datos de {mes_ant_key} copiados con éxito. Revise y guarde el formulario abajo.")
            else:
                st.warning(f"⚠️ No hay parámetros guardados previamente para el periodo {mes_ant_key}.")

    # Cargamos los datos del periodo seleccionado (o los valores por defecto si no existe)
    p = st.session_state['parametros_globales'].get(periodo_key, default_p)

    # Indicador visual de estado
    if periodo_key in st.session_state['parametros_globales']:
        st.success(f"📌 Los parámetros para **{periodo_key}** ya están configurados y activos. Puede editarlos si hubo cambios en la ley.")
    else:
        st.info(f"📝 Configurando nuevos parámetros para el periodo **{periodo_key}**.")

    st.markdown("---")

    # 3. FORMULARIO CORPORATIVO DE TASAS
    with st.form("form_parametros_globales"):
        
        st.subheader("1. Indicadores Económicos y de Salud")
        col1, col2, col3, col4 = st.columns(4)
        rmv = col1.number_input("RMV (S/)", value=float(p.get('rmv', 1025.0)), step=10.0)
        uit = col2.number_input("UIT (S/)", value=float(p.get('uit', 5350.0)), step=50.0)
        tasa_essalud = col3.number_input("Tasa EsSalud (%)", value=float(p.get('tasa_essalud', 9.0)), step=0.1)
        tasa_eps = col4.number_input("Tasa EPS (%)", value=float(p.get('tasa_eps', 6.75)), step=0.1)

        col5, col6, col7, col8 = st.columns(4)
        tasa_onp = col5.number_input("Tasa ONP (%)", value=float(p.get('tasa_onp', 13.0)), step=0.1)
        tope_afp = col6.number_input("Rem. Máx. Asegurable AFP (S/)", value=float(p.get('tope_afp', 13583.51)), step=100.0)
        
        st.markdown("<br>---", unsafe_allow_html=True)

        st.subheader("2. Tasas del Sistema Privado de Pensiones (AFP)")
        # Enlace corporativo a SBS
        st.markdown(
            "<div style='margin-top: -10px; margin-bottom: 20px;'>"
            "<a href='https://www.sbs.gob.pe/app/spp/empleadores/comisiones_spp/paginas/comision_prima.aspx' "
            "target='_blank' style='font-size: 13px; color: #1f77b4; text-decoration: none; font-weight: 600;'>"
            "🔗 Consultar Cuadro de Comisiones y Primas Vigentes (Portal Oficial SBS)</a></div>", 
            unsafe_allow_html=True
        )
        
        # Cuadrícula compacta
        c_nom, c_ap, c_pr, c_fl, c_mx = st.columns([1.5, 1, 1, 1, 1])
        c_nom.markdown("<span style='font-size: 13px; color: #666; font-weight: bold;'>Entidad</span>", unsafe_allow_html=True)
        c_ap.markdown("<span style='font-size: 13px; color: #666; font-weight: bold;'>Aporte (%)</span>", unsafe_allow_html=True)
        c_pr.markdown("<span style='font-size: 13px; color: #666; font-weight: bold;'>Prima Seg. (%)</span>", unsafe_allow_html=True)
        c_fl.markdown("<span style='font-size: 13px; color: #666; font-weight: bold;'>Comis. Flujo (%)</span>", unsafe_allow_html=True)
        c_mx.markdown("<span style='font-size: 13px; color: #666; font-weight: bold;'>Comis. Mixta (%)</span>", unsafe_allow_html=True)

        # HABITAT
        c_nom, c_ap, c_pr, c_fl, c_mx = st.columns([1.5, 1, 1, 1, 1])
        c_nom.markdown("<br><span style='font-size: 14px; font-weight: 500;'>HABITAT</span>", unsafe_allow_html=True)
        hab_ap = c_ap.number_input("A", value=float(p.get('afp_habitat_aporte', 10.0)), key="h1", label_visibility="collapsed")
        hab_pr = c_pr.number_input("P", value=float(p.get('afp_habitat_prima', 1.84)), key="h2", label_visibility="collapsed")
        hab_fl = c_fl.number_input("F", value=float(p.get('afp_habitat_flujo', 1.47)), key="h3", label_visibility="collapsed")
        hab_mx = c_mx.number_input("M", value=float(p.get('afp_habitat_mixta', 0.23)), key="h4", label_visibility="collapsed")

        # INTEGRA
        c_nom, c_ap, c_pr, c_fl, c_mx = st.columns([1.5, 1, 1, 1, 1])
        c_nom.markdown("<br><span style='font-size: 14px; font-weight: 500;'>INTEGRA</span>", unsafe_allow_html=True)
        int_ap = c_ap.number_input("A", value=float(p.get('afp_integra_aporte', 10.0)), key="i1", label_visibility="collapsed")
        int_pr = c_pr.number_input("P", value=float(p.get('afp_integra_prima', 1.84)), key="i2", label_visibility="collapsed")
        int_fl = c_fl.number_input("F", value=float(p.get('afp_integra_flujo', 1.55)), key="i3", label_visibility="collapsed")
        int_mx = c_mx.number_input("M", value=float(p.get('afp_integra_mixta', 0.0)), key="i4", label_visibility="collapsed")

        # PRIMA
        c_nom, c_ap, c_pr, c_fl, c_mx = st.columns([1.5, 1, 1, 1, 1])
        c_nom.markdown("<br><span style='font-size: 14px; font-weight: 500;'>PRIMA</span>", unsafe_allow_html=True)
        pri_ap = c_ap.number_input("A", value=float(p.get('afp_prima_aporte', 10.0)), key="p1", label_visibility="collapsed")
        pri_pr = c_pr.number_input("P", value=float(p.get('afp_prima_prima', 1.84)), key="p2", label_visibility="collapsed")
        pri_fl = c_fl.number_input("F", value=float(p.get('afp_prima_flujo', 1.60)), key="p3", label_visibility="collapsed")
        pri_mx = c_mx.number_input("M", value=float(p.get('afp_prima_mixta', 0.18)), key="p4", label_visibility="collapsed")

        # PROFUTURO
        c_nom, c_ap, c_pr, c_fl, c_mx = st.columns([1.5, 1, 1, 1, 1])
        c_nom.markdown("<br><span style='font-size: 14px; font-weight: 500;'>PROFUTURO</span>", unsafe_allow_html=True)
        pro_ap = c_ap.number_input("A", value=float(p.get('afp_profuturo_aporte', 10.0)), key="pr1", label_visibility="collapsed")
        pro_pr = c_pr.number_input("P", value=float(p.get('afp_profuturo_prima', 1.84)), key="pr2", label_visibility="collapsed")
        pro_fl = c_fl.number_input("F", value=float(p.get('afp_profuturo_flujo', 1.69)), key="pr3", label_visibility="collapsed")
        pro_mx = c_mx.number_input("M", value=float(p.get('afp_profuturo_mixta', 0.67)), key="pr4", label_visibility="collapsed")

        st.markdown("---")
        submit_btn = st.form_submit_button(f"💾 Guardar Parámetros para {periodo_key}", type="primary", use_container_width=True)
        
        if submit_btn:
            # Guardamos la data ESPECÍFICAMENTE bajo la llave del periodo seleccionado
            st.session_state['parametros_globales'][periodo_key] = {
                "rmv": rmv, "uit": uit, "tope_afp": tope_afp, "tasa_onp": tasa_onp,
                "tasa_essalud": tasa_essalud, "tasa_eps": tasa_eps,
                "afp_habitat_aporte": hab_ap, "afp_habitat_prima": hab_pr, "afp_habitat_flujo": hab_fl, "afp_habitat_mixta": hab_mx,
                "afp_integra_aporte": int_ap, "afp_integra_prima": int_pr, "afp_integra_flujo": int_fl, "afp_integra_mixta": int_mx,
                "afp_prima_aporte": pri_ap, "afp_prima_prima": pri_pr, "afp_prima_flujo": pri_fl, "afp_prima_mixta": pri_mx,
                "afp_profuturo_aporte": pro_ap, "afp_profuturo_prima": pro_pr, "afp_profuturo_flujo": pro_fl, "afp_profuturo_mixta": pro_mx
            }
            
            # Registramos este periodo como configurado y recargamos para mostrar el mensaje de éxito
            if periodo_key not in st.session_state['periodos_configurados']:
                st.session_state['periodos_configurados'].append(periodo_key)
            
            st.rerun()