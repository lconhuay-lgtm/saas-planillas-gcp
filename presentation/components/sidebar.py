import streamlit as st

_ROL_LABEL = {
    "analista":   "Analista de Planillas",
    "supervisor": "Supervisor",
    "asistente":  "Asistente de Planta",
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

        # Si no hay empresa activa, mostramos Selector y Gestión de Usuarios si aplica
        if not empresa_id:
            opciones_inicio = ["Selector de Empresa"]
            if usuario_rol == 'admin':
                opciones_inicio.append("Gestión de Usuarios")
            
            st.warning("⚠️ Seleccione una empresa para habilitar los módulos operativos.")
            menu = st.radio(
                "Navegación",
                opciones_inicio,
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

        import json as _json
        restringidos = []
        try:
            # Recuperar restricciones del usuario desde la sesión o DB
            from infrastructure.database.connection import SessionLocal
            from infrastructure.database.models import Usuario
            _db_s = SessionLocal()
            _u_s = _db_s.query(Usuario).filter_by(username=st.session_state.get('usuario_logueado')).first()
            if _u_s:
                restringidos = _json.loads(_u_s.modulos_restringidos or '[]')
            _db_s.close()
        except:
            restringidos = []

        if usuario_rol == 'asistente':
            opciones_base = ["Maestro de Personal"]
        else:
            opciones_base = [
                "Dashboard Principal",
                "Parámetros Legales",
                "Maestro de Personal",
                "Maestro de Conceptos",
                "Ingreso de Asistencias",
                "Kardex de Vacaciones",
                "Cálculo de Planilla",
                "Préstamos y Descuentos",
                "Emisión de Boletas",
                "Reportería",
                "Liquidación por Cese",
            ]
        
        # Filtrar módulos restringidos
        opciones = [o for o in opciones_base if o not in restringidos]

        # Solo el rol 'admin' puede gestionar usuarios y permisos
        if usuario_rol == 'admin':
            opciones.append("Gestión de Usuarios")

        menu = st.radio(
            "Navegación",
            opciones,
            label_visibility="collapsed"
        )
        return menu
