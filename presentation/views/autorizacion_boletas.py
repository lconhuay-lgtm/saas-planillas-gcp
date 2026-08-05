"""
Compuerta obligatoria de autorización de envío de boletas.

Cuando un periodo queda CERRADO, sus boletas no se envían solas — un usuario con rol
admin/supervisor de la empresa debe entrar, poder revisar la boleta de cualquier
trabajador, y presionar "Autorizar y Enviar" antes de que salgan los correos reales.

Solo aplica a periodos a partir de 07-2026 (no afecta meses anteriores ya procesados).
"""
from datetime import datetime
import streamlit as st

from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import PlanillaMensual
from presentation.views.emision_boletas import (
    _cargar_planilla_periodo,
    generar_pdf_boletas_masivas,
    enviar_boletas_periodo,
    _periodo_legible,
)

# La compuerta solo aplica desde este periodo en adelante (formato interno "AAAAMM")
UMBRAL_PERIODO = 202607  # 07-2026


def _periodo_ordenable(periodo_key: str) -> int:
    """'07-2026' -> 202607, para poder comparar periodos cronológicamente."""
    try:
        mes, anio = periodo_key.split("-")
        return int(anio) * 100 + int(mes)
    except Exception:
        return 0


def _periodos_pendientes(db, empresa_id):
    """Periodos CERRADOS, no autorizados, desde 07-2026 en adelante — el más antiguo primero."""
    planillas = db.query(PlanillaMensual).filter_by(empresa_id=empresa_id, estado='CERRADA').all()
    pendientes = [
        p for p in planillas
        if not getattr(p, 'boletas_autorizado', False)
        and _periodo_ordenable(p.periodo_key) >= UMBRAL_PERIODO
    ]
    pendientes.sort(key=lambda p: _periodo_ordenable(p.periodo_key))
    return pendientes


def periodo_bloqueante(empresa_id):
    """
    Retorna el periodo_key que debe bloquear la navegación ahora mismo (el más antiguo
    pendiente que NO haya sido pospuesto en esta sesión), o None si no hay ninguno.

    Se evalúa ANTES de decidir si se llama a render() — así, posponer un periodo no deja
    la pantalla en blanco: el enrutador simplemente no vuelve a llamar a esta vista.
    """
    if not empresa_id:
        return None
    db = SessionLocal()
    try:
        pendientes = _periodos_pendientes(db, empresa_id)
    finally:
        db.close()

    for p in pendientes:
        postpone_key = f"_boletas_gate_postpone_{empresa_id}_{p.periodo_key}"
        if not st.session_state.get(postpone_key):
            return p.periodo_key
    return None  # todos los pendientes están pospuestos esta sesión


def render(periodo_key):
    st.title("🔒 Autorización de Envío de Boletas")
    st.markdown("---")

    empresa_id = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')
    usuario_rol = st.session_state.get('usuario_rol')
    puede_autorizar = usuario_rol in ('admin', 'supervisor')

    db = SessionLocal()
    try:
        planilla_sel = db.query(PlanillaMensual).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first()
        pendientes = _periodos_pendientes(db, empresa_id)
    finally:
        db.close()

    if not planilla_sel:
        return  # no debería pasar — el llamador ya validó que este periodo existe y está pendiente

    periodo_legible = _periodo_legible(periodo_key)
    postpone_key = f"_boletas_gate_postpone_{empresa_id}_{periodo_key}"

    if len(pendientes) > 1:
        st.info(
            f"ℹ️ Hay {len(pendientes)} periodo(s) con boletas pendientes de autorizar en "
            f"**{empresa_nombre}**. Mostrando: **{periodo_legible}**."
        )

    st.warning(
        f"⚠️ La planilla del periodo **{periodo_legible}** está cerrada y sus boletas "
        f"todavía no han sido autorizadas para envío. Revise al menos una boleta antes "
        f"de continuar — este paso existe para evitar enviar boletas con errores."
    )

    db2 = SessionLocal()
    try:
        df_resultados, auditoria_data, df_trab, df_var = _cargar_planilla_periodo(db2, empresa_id, periodo_key)
    finally:
        db2.close()

    if df_resultados is None:
        st.error("No se pudo cargar la planilla de este periodo.")
        return

    empresa_info = {
        'nombre': empresa_nombre,
        'ruc': st.session_state.get('empresa_activa_ruc', ''),
        'domicilio': st.session_state.get('empresa_activa_domicilio', ''),
        'representante': st.session_state.get('empresa_activa_representante', ''),
    }

    df_sin_totales = df_resultados[df_resultados['Apellidos y Nombres'] != 'TOTALES']
    df_emails = df_trab[df_trab['Num. Doc.'].isin(df_sin_totales['DNI'])].copy()
    if 'correo_electronico' not in df_emails.columns:
        df_emails['correo_electronico'] = ""
    sin_correo = df_emails[df_emails['correo_electronico'].isna() | (df_emails['correo_electronico'] == '')]
    con_correo = df_emails[~df_emails['Num. Doc.'].isin(sin_correo['Num. Doc.'])]

    col_a, col_b = st.columns(2)
    col_a.metric("Trabajadores a notificar", len(con_correo))
    col_b.metric("Sin correo registrado", len(sin_correo))
    if not sin_correo.empty:
        with st.expander("Ver trabajadores sin correo (no recibirán boleta)"):
            st.write(sin_correo[['Num. Doc.', 'Nombres y Apellidos']])

    st.markdown("### 👁️ Verificar boletas antes de autorizar")
    st.caption("Revise la boleta de cualquier trabajador — confirme que los montos, ingresos y descuentos se vean correctos.")

    opciones_trab = df_sin_totales['DNI'].astype(str) + " - " + df_sin_totales['Apellidos y Nombres']
    trabajador_sel = st.selectbox("Seleccione un trabajador para verificar su boleta:", opciones_trab, key="sel_verif_boleta")

    if trabajador_sel:
        dni_sel = trabajador_sel.split(" - ")[0]
        nombre_sel = trabajador_sel.split(" - ", 1)[1]
        if st.button(f"📄 Generar boleta de {nombre_sel}", key="btn_ver_boleta_gate"):
            df_individual = df_sin_totales[df_sin_totales['DNI'] == dni_sel]
            with st.spinner("Generando boleta..."):
                pdf_buffer = generar_pdf_boletas_masivas(empresa_info, periodo_key, df_individual, df_trab, df_var, auditoria_data)
                st.download_button(
                    label=f"📥 Descargar BOLETA_{dni_sel}.pdf",
                    data=pdf_buffer, file_name=f"BOLETA_{dni_sel}_{periodo_key}.pdf",
                    mime="application/pdf", key="dl_verif_boleta",
                )

    st.markdown("---")

    if puede_autorizar:
        st.markdown("### ✅ Decisión")
        col_auth, col_post = st.columns(2)
        if col_auth.button("✅ Autorizar y Enviar Ahora", type="primary", use_container_width=True, key="btn_autorizar_envio"):
            with st.spinner("Enviando boletas..."):
                exitos, errores = enviar_boletas_periodo(
                    empresa_id, empresa_nombre, empresa_info, periodo_key, periodo_legible,
                    df_resultados, df_trab, df_var, auditoria_data, con_correo, sin_correo,
                )
            db3 = SessionLocal()
            try:
                p = db3.query(PlanillaMensual).filter_by(id=planilla_sel.id).first()
                if p:
                    p.boletas_autorizado = True
                    p.boletas_autorizado_por = st.session_state.get('usuario_logueado')
                    p.boletas_fecha_autorizacion = datetime.now()
                    db3.commit()
            finally:
                db3.close()
            st.session_state.pop(postpone_key, None)
            st.success(f"🎊 Autorizado y enviado. Éxitos: {exitos} | Errores: {errores}")
            st.rerun()

        if col_post.button("⏭️ Revisar más tarde", use_container_width=True, key="btn_posponer_envio"):
            st.session_state[postpone_key] = True
            st.rerun()
    else:
        st.info("🔒 Solo un Administrador o Supervisor puede autorizar el envío de boletas. Contacte a su supervisor.")
        if st.button("Entendido, continuar navegando", use_container_width=True, key="btn_continuar_sin_autorizar"):
            st.session_state[postpone_key] = True
            st.rerun()
