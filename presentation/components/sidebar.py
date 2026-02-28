import streamlit as st

_ROL_LABEL = {
    "analista":   "Analista de Planillas",
    "supervisor": "Supervisor",
}

def render_sidebar():
    with st.sidebar:
        st.markdown("### 💼 ERP Planillas SaaS")
        st.markdown("---")

        # ── Info del usuario autenticado ──────────────────────────────────────
        usuario_nombre = st.session_state.get('usuario_nombre', '')
        usuario_rol    = st.session_state.get('usuario_rol', '')
        rol_label      = _ROL_LABEL.get(usuario_rol, usuario_rol.capitalize())
        icono_rol      = "🛡️" if usuario_rol == "supervisor" else "👤"

        st.markdown(
            f"<div style='background:#1E4D8C;border-radius:8px;padding:10px 12px;margin-bottom:8px'>"
            f"<span style='color:#90CAF9;font-size:0.75rem;font-weight:600;letter-spacing:0.05em'>{icono_rol} {rol_label.upper()}</span><br>"
            f"<span style='color:#FFFFFF;font-size:0.92rem;font-weight:700'>{usuario_nombre}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if st.button("🚪 Cerrar Sesión", use_container_width=True):
            for key in ['usuario_logueado', 'usuario_rol', 'usuario_nombre',
                        'empresa_activa_id', 'empresa_activa_nombre',
                        'empresa_activa_ruc', 'empresa_activa_domicilio',
                        'empresa_activa_representante', 'empresa_activa_regimen',
                        'res_planilla', 'auditoria_data', 'ultima_planilla_calculada']:
                st.session_state.pop(key, None)
            st.rerun()

        st.markdown("---")

        empresa_id     = st.session_state.get('empresa_activa_id')
        empresa_nombre = st.session_state.get('empresa_activa_nombre')

        # Si no hay empresa activa, solo mostramos el Selector
        if not empresa_id:
            st.warning("⚠️ Seleccione una empresa para habilitar los módulos.")
            menu = st.radio(
                "Navegación",
                ["Selector de Empresa"],
                label_visibility="collapsed"
            )
            return menu

        # Con empresa activa
        st.success(f"🏢 **{empresa_nombre}**")
        if st.button("🔄 Cambiar Empresa", use_container_width=True):
            for key in ['empresa_activa_id', 'empresa_activa_nombre',
                        'empresa_activa_ruc', 'empresa_activa_domicilio',
                        'empresa_activa_representante', 'empresa_activa_regimen',
                        'res_planilla', 'auditoria_data', 'ultima_planilla_calculada']:
                st.session_state.pop(key, None)
            st.rerun()

        st.markdown("---")

        opciones = [
            "Dashboard Principal",
            "Parámetros Legales",
            "Maestro de Personal",
            "Maestro de Conceptos",
            "Ingreso de Asistencias",
            "Cálculo de Planilla",
            "Préstamos y Descuentos",
            "Emisión de Boletas",
            "Reportería",
        ]

        menu = st.radio(
            "Navegación",
            opciones,
            label_visibility="collapsed"
        )
        return menu
