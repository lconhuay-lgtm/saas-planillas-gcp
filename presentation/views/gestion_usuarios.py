import streamlit as st
import hashlib
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Usuario, Empresa, UsuarioEmpresa

def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def render():
    """Administración de Identidades y Accesos (IAM) - Enterprise Grade."""
    if st.session_state.get('usuario_rol') != 'admin':
        st.error("🚫 **Acceso Denegado:** Se requieren privilegios de Administrador de Sistemas para gestionar perfiles de seguridad.")
        return

    st.title("🛡️ Central de Seguridad y Usuarios")
    st.markdown("Gestión jerárquica de accesos, roles y perímetros de visibilidad multi-empresa.")
    st.markdown("---")
    
    db = SessionLocal()
    try:
        tab_crear, tab_maestro = st.tabs(["➕ Alta de Usuario", "👤 Directorio y Perfiles"])

        # ── TAB: ALTA DE USUARIO (Provisioning) ────────────────────────────────
        with tab_crear:
            st.subheader("Aprovisionamiento de Nueva Identidad")
            with st.container(border=True):
                col_id1, col_id2 = st.columns(2)
                u_username = col_id1.text_input("ID de Usuario (Logon)*", help="Nombre único de acceso al sistema.").lower().strip()
                u_pass     = col_id2.text_input("Clave Inicial*", type="password", help="Se recomienda una clave alfanumérica compleja.")
                
                u_nombre   = st.text_input("Nombre y Apellidos del Responsable")
                u_email    = st.text_input("Correo Corporativo")

                st.markdown("---")
                st.markdown("##### Configuración de Autorizaciones")
                col_acc1, col_acc2 = st.columns(2)
                
                # Roles SAP Style
                u_rol = col_acc1.selectbox("Rol Funcional", [
                    ("admin", "Administrador (Control Total)"),
                    ("supervisor", "Supervisor (Gestión y Cierre)"),
                    ("analista", "Analista (Operación de Nómina)"),
                    ("asistente", "Asistente (Lectura y Maestro)"),
                    ("consulta", "Auditor (Solo Lectura)")
                ], format_func=lambda x: x[1])

                u_total = col_acc2.toggle("Acceso Global (All Companies)", value=False, 
                                        help="Si se activa, el usuario verá todas las empresas actuales y futuras sin restricción.")

                # Selección de perímetro si no es acceso total
                todas_empresas = db.query(Empresa).order_by(Empresa.razon_social).all()
                emp_options = {f"{e.ruc} - {e.razon_social}": e.id for e in todas_empresas}
                
                u_seleccionadas = st.multiselect(
                    "Asignación de Perímetros (Sociedades / Empresas)*", 
                    options=list(emp_options.keys()),
                    disabled=u_total,
                    help="Defina qué empresas específicas podrá gestionar este usuario."
                )

                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🚀 Confirmar Alta y Provisionar", type="primary", use_container_width=True):
                    if not u_username or not u_pass:
                        st.error("Error: Los campos marcados con (*) son mandatorios.")
                    elif not u_total and not u_seleccionadas:
                        st.error("Error: Debe asignar al menos una empresa o habilitar el Acceso Global.")
                    else:
                        # Verificar duplicados
                        existe = db.query(Usuario).filter_by(username=u_username).first()
                        if existe:
                            st.error(f"El ID de usuario '{u_username}' ya se encuentra registrado.")
                        else:
                            nuevo = Usuario(
                                username=u_username, 
                                password_hash=_hash(u_pass),
                                rol=u_rol[0],
                                nombre_completo=u_nombre,
                                email=u_email,
                                acceso_total=u_total,
                                activo=True
                            )
                            db.add(nuevo)
                            db.flush()
                            
                            if not u_total:
                                for emp_lbl in u_seleccionadas:
                                    db.add(UsuarioEmpresa(usuario_id=nuevo.id, empresa_id=emp_options[emp_lbl]))
                            
                            db.commit()
                            st.success(f"✅ Identidad **{u_username}** provisionada correctamente.")
                            st.rerun()

        # ── TAB: DIRECTORIO (Governance) ──────────────────────────────────────
        with tab_maestro:
            st.subheader("Maestro de Identidades")
            usuarios_db = db.query(Usuario).all()
            
            for u in usuarios_db:
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([2, 1.5, 2, 1])
                    
                    status_icon = "🟢" if u.activo else "🔴"
                    c1.markdown(f"**{u.nombre_completo or u.username}**")
                    c1.caption(f"{status_icon} ID: `{u.username}` | Rol: `{u.rol.upper()}`")
                    
                    if u.acceso_total:
                        c2.info("🌐 Acceso Global")
                    else:
                        n_emp = len(u.empresas_asignadas)
                        c2.warning(f"🏢 {n_emp} Empresa(s)")

                    # Gestión de Perfil
                    with c3.expander("⚙️ Modificar Permisos"):
                        e_rol = st.selectbox("Cambiar Rol", ["admin", "supervisor", "analista", "asistente", "consulta"], 
                                           index=["admin", "supervisor", "analista", "asistente", "consulta"].index(u.rol),
                                           key=f"e_rol_{u.id}")
                        e_total = st.toggle("Acceso Global", value=u.acceso_total, key=f"e_tot_{u.id}")
                        e_activo = st.toggle("Cuenta Activa", value=u.activo, key=f"e_act_{u.id}")
                        
                        asignadas_ids = [e.id for e in u.empresas_asignadas]
                        todas_emp = db.query(Empresa).all()
                        
                        e_emp = st.multiselect(
                            "Empresas Autorizadas", 
                            options=[e.id for e in todas_emp],
                            default=asignadas_ids,
                            format_func=lambda x: next((emp.razon_social for emp in todas_emp if emp.id == x), str(x)),
                            disabled=e_total,
                            key=f"e_emp_{u.id}"
                        )
                        
                        if st.button("💾 Guardar Cambios", key=f"btn_upd_{u.id}", use_container_width=True):
                            u.rol = e_rol
                            u.acceso_total = e_total
                            u.activo = e_activo
                            # Reset y Reasignación
                            if not e_total:
                                # Eliminar asignaciones actuales
                                db.query(UsuarioEmpresa).filter_by(usuario_id=u.id).delete()
                                # Crear nuevas
                                for eid in e_emp:
                                    db.add(UsuarioEmpresa(usuario_id=u.id, empresa_id=eid))
                            else:
                                db.query(UsuarioEmpresa).filter_by(usuario_id=u.id).delete()
                            
                            db.commit()
                            st.toast("Perfil actualizado", icon="🛡️")
                            st.rerun()

                    # Eliminar (Solo si no es el usuario actual)
                    if u.username != st.session_state.get('usuario_logueado'):
                        if c4.button("🗑️", key=f"btn_del_{u.id}", help="Eliminar permanentemente"):
                            db.delete(u)
                            db.commit()
                            st.rerun()
                    else:
                        c4.button("👤", disabled=True, key=f"me_{u.id}")

    finally:
        db.close()
