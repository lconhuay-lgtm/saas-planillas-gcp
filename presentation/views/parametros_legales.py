import streamlit as st
from datetime import date, datetime
from infrastructure.database.connection import get_db
from infrastructure.database.models import ParametroLegal

# Diccionario de meses para el selector (Mantenemos tu estándar)
MESES = ["01 - Enero", "02 - Febrero", "03 - Marzo", "04 - Abril", "05 - Mayo", "06 - Junio", 
         "07 - Julio", "08 - Agosto", "09 - Septiembre", "10 - Octubre", "11 - Noviembre", "12 - Diciembre"]

def render():
    st.title("⚙️ Parámetros Legales y Tributarios (Globales)")
    st.markdown("""
    Configure las tasas macroeconómicas y tributarias por **Periodo (Mes/Año)**. 
    **Importante:** Los datos se sincronizan con la nube para garantizar la inmutabilidad histórica.
    """)
    st.markdown("---")

    db = next(get_db())
    empresa_id = st.session_state.get('empresa_activa_id')

    if not empresa_id:
        st.error("⚠️ Por favor, seleccione una empresa primero.")
        return

    # 1. SELECTOR DE PERIODO
    st.subheader("Selección de Periodo a Configurar")
    col_m, col_a = st.columns([2, 1])
    
    mes_actual_idx = date.today().month - 1
    mes_seleccionado = col_m.selectbox("Mes", MESES, index=mes_actual_idx)
    anio_seleccionado = col_a.selectbox("Año", [2025, 2026, 2027, 2028], index=1)
    
    periodo_key = f"{mes_seleccionado[:2]}-{anio_seleccionado}"
    
    # Identificar mes anterior para la herencia automática
    idx_sel = MESES.index(mes_seleccionado)
    mes_ant_key = f"12-{anio_seleccionado-1}" if idx_sel == 0 else f"{MESES[idx_sel-1][:2]}-{anio_seleccionado}"

    # 2. CONSULTA A BASE DE DATOS (Sustituye al session_state antiguo)
    p_db = db.query(ParametroLegal).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first()
    
    p_data = None
    if p_db:
        p_data = p_db
        st.success(f"📌 Parámetros para **{periodo_key}** activos en la nube.")
    else:
        # Intentar heredar del mes anterior si el actual está vacío
        p_heredado = db.query(ParametroLegal).filter_by(empresa_id=empresa_id, periodo_key=mes_ant_key).first()
        if p_heredado:
            p_data = p_heredado
            st.info(f"💡 Valores sugeridos heredados de {mes_ant_key}. Guarde para confirmar.")
        else:
            st.warning(f"📝 Configurando nuevos parámetros para el periodo **{periodo_key}**.")

    # 3. FORMULARIO CORPORATIVO (Tu diseño original intacto)
    with st.form("form_parametros_globales"):
        
        st.subheader("1. Indicadores Económicos y de Salud")
        col1, col2, col3, col4 = st.columns(4)
        rmv = col1.number_input("RMV (S/)", value=float(p_data.rmv if p_data else 1025.0), step=10.0)
        uit = col2.number_input("UIT (S/)", value=float(p_data.uit if p_data else 5350.0), step=50.0)
        t_essalud = col3.number_input("Tasa EsSalud (%)", value=float(p_data.tasa_essalud if p_data else 9.0), step=0.1)
        t_eps = col4.number_input("Tasa EPS (%)", value=float(p_data.tasa_eps if p_data else 6.75), step=0.1)

        col5, col6 = st.columns(2)
        t_onp = col5.number_input("Tasa ONP (%)", value=float(p_data.tasa_onp if p_data else 13.0), step=0.1)
        t_afp_tope = col6.number_input("Rem. Máx. Asegurable AFP (S/)", value=float(p_data.tope_afp if p_data else 13583.51), step=100.0)

        st.markdown("<br>---", unsafe_allow_html=True)
        st.subheader("1b. Retención de 4ta Categoría (Locadores de Servicio)")
        st.caption("Aplica al pago de honorarios a locadores. La retención solo se efectúa si el pago bruto supera el tope.")
        col_4a, col_4b = st.columns(2)
        t_4ta  = col_4a.number_input("Tasa Retención 4ta Cat. (%)", value=float(getattr(p_data, 'tasa_4ta', 8.0) if p_data else 8.0), step=0.5, min_value=0.0, max_value=100.0)
        tope_4ta = col_4b.number_input("Tope mínimo para retener (S/)", value=float(getattr(p_data, 'tope_4ta', 1500.0) if p_data else 1500.0), step=50.0, min_value=0.0)

        st.markdown("<br>---", unsafe_allow_html=True)
        st.subheader("2. Tasas del Sistema Privado de Pensiones (AFP)")
        st.markdown(
            "<div style='margin-top: -10px; margin-bottom: 20px;'>"
            "<a href='https://www.sbs.gob.pe/app/spp/empleadores/comisiones_spp/paginas/comision_prima.aspx' "
            "target='_blank' style='font-size: 13px; color: #1f77b4; text-decoration: none; font-weight: 600;'>"
            "🔗 Consultar Cuadro de Comisiones y Primas Vigentes (Portal Oficial SBS)</a></div>", 
            unsafe_allow_html=True
        )
        
        # Encabezados de tabla (Tu diseño original)
        c_nom, c_ap, c_pr, c_fl, c_mx = st.columns([1.5, 1, 1, 1, 1])
        c_nom.markdown("<span style='font-size: 13px; color: #666; font-weight: bold;'>Entidad</span>", unsafe_allow_html=True)
        c_ap.markdown("<span style='font-size: 13px; color: #666; font-weight: bold;'>Aporte (%)</span>", unsafe_allow_html=True)
        c_pr.markdown("<span style='font-size: 13px; color: #666; font-weight: bold;'>Prima Seg. (%)</span>", unsafe_allow_html=True)
        c_fl.markdown("<span style='font-size: 13px; color: #666; font-weight: bold;'>Comis. Flujo (%)</span>", unsafe_allow_html=True)
        c_mx.markdown("<span style='font-size: 13px; color: #666; font-weight: bold;'>Comis. Mixta (%)</span>", unsafe_allow_html=True)

        # --- HABITAT ---
        c_nom, c_ap, c_pr, c_fl, c_mx = st.columns([1.5, 1, 1, 1, 1])
        c_nom.markdown("<br><span style='font-size: 14px; font-weight: 500;'>HABITAT</span>", unsafe_allow_html=True)
        h_ap = c_ap.number_input("A", value=float(p_data.h_ap if p_data else 10.0), key="h1", label_visibility="collapsed")
        h_pr = c_pr.number_input("P", value=float(p_data.h_pr if p_data else 1.84), key="h2", label_visibility="collapsed")
        h_fl = c_fl.number_input("F", value=float(p_data.h_fl if p_data else 1.47), key="h3", label_visibility="collapsed")
        h_mx = c_mx.number_input("M", value=float(p_data.h_mx if p_data else 0.23), key="h4", label_visibility="collapsed")

        # --- INTEGRA ---
        c_nom, c_ap, c_pr, c_fl, c_mx = st.columns([1.5, 1, 1, 1, 1])
        c_nom.markdown("<br><span style='font-size: 14px; font-weight: 500;'>INTEGRA</span>", unsafe_allow_html=True)
        i_ap = c_ap.number_input("A", value=float(p_data.i_ap if p_data else 10.0), key="i1", label_visibility="collapsed")
        i_pr = c_pr.number_input("P", value=float(p_data.i_pr if p_data else 1.84), key="i2", label_visibility="collapsed")
        i_fl = c_fl.number_input("F", value=float(p_data.i_fl if p_data else 1.55), key="i3", label_visibility="collapsed")
        i_mx = c_mx.number_input("M", value=float(p_data.i_mx if p_data else 0.0), key="i4", label_visibility="collapsed")

        # --- PRIMA ---
        c_nom, c_ap, c_pr, c_fl, c_mx = st.columns([1.5, 1, 1, 1, 1])
        c_nom.markdown("<br><span style='font-size: 14px; font-weight: 500;'>PRIMA</span>", unsafe_allow_html=True)
        p_ap = c_ap.number_input("A", value=float(p_data.p_ap if p_data else 10.0), key="p1", label_visibility="collapsed")
        p_pr = c_pr.number_input("P", value=float(p_data.p_pr if p_data else 1.84), key="p2", label_visibility="collapsed")
        p_fl = c_fl.number_input("F", value=float(p_data.p_fl if p_data else 1.60), key="p3", label_visibility="collapsed")
        p_mx = c_mx.number_input("M", value=float(p_data.p_mx if p_data else 0.18), key="p4", label_visibility="collapsed")

        # --- PROFUTURO ---
        c_nom, c_ap, c_pr, c_fl, c_mx = st.columns([1.5, 1, 1, 1, 1])
        c_nom.markdown("<br><span style='font-size: 14px; font-weight: 500;'>PROFUTURO</span>", unsafe_allow_html=True)
        pr_ap = c_ap.number_input("A", value=float(p_data.pr_ap if p_data else 10.0), key="pr1", label_visibility="collapsed")
        pr_pr = c_pr.number_input("P", value=float(p_data.pr_pr if p_data else 1.84), key="pr2", label_visibility="collapsed")
        pr_fl = c_fl.number_input("F", value=float(p_data.pr_fl if p_data else 1.69), key="pr3", label_visibility="collapsed")
        pr_mx = c_mx.number_input("M", value=float(p_data.pr_mx if p_data else 0.67), key="pr4", label_visibility="collapsed")

        st.markdown("---")
        submit_btn = st.form_submit_button(f"💾 Guardar Parámetros para {periodo_key}", type="primary", use_container_width=True)
        
        if submit_btn:
            # Lógica de Guardado en Neon
            if p_db: # ACTUALIZAR
                p_db.rmv = rmv; p_db.uit = uit; p_db.tasa_essalud = t_essalud; p_db.tasa_eps = t_eps
                p_db.tasa_onp = t_onp; p_db.tope_afp = t_afp_tope
                p_db.h_ap = h_ap; p_db.h_pr = h_pr; p_db.h_fl = h_fl; p_db.h_mx = h_mx
                p_db.i_ap = i_ap; p_db.i_pr = i_pr; p_db.i_fl = i_fl; p_db.i_mx = i_mx
                p_db.p_ap = p_ap; p_db.p_pr = p_pr; p_db.p_fl = p_fl; p_db.p_mx = p_mx
                p_db.pr_ap = pr_ap; p_db.pr_pr = pr_pr; p_db.pr_fl = pr_fl; p_db.pr_mx = pr_mx
                p_db.tasa_4ta = t_4ta; p_db.tope_4ta = tope_4ta
            else: # CREAR NUEVO
                nuevo = ParametroLegal(
                    empresa_id=empresa_id, periodo_key=periodo_key,
                    rmv=rmv, uit=uit, tasa_essalud=t_essalud, tasa_eps=t_eps,
                    tasa_onp=t_onp, tope_afp=t_afp_tope,
                    h_ap=h_ap, h_pr=h_pr, h_fl=h_fl, h_mx=h_mx,
                    i_ap=i_ap, i_pr=i_pr, i_fl=i_fl, i_mx=i_mx,
                    p_ap=p_ap, p_pr=p_pr, p_fl=p_fl, p_mx=p_mx,
                    pr_ap=pr_ap, pr_pr=pr_pr, pr_fl=pr_fl, pr_mx=pr_mx,
                    tasa_4ta=t_4ta, tope_4ta=tope_4ta,
                )
                db.add(nuevo)
            
            db.commit()
            st.success(f"✅ Sincronizado con éxito para el periodo {periodo_key}.")
            st.rerun()