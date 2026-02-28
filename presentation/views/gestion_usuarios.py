import streamlit as st
import hashlib
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Usuario, Empresa, UsuarioEmpresa

def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def render():
    if st.session_state.get('usuario_rol') != 'admin' and not st.session_state.get('usuario_rol') == 'supervisor':
        st.error("🚫 Acceso restringido. Solo administradores pueden gestionar usuarios.")
        return

    st.title("👥 Gestión de Usuarios y Permisos")
    db = SessionLocal()
    
    try:
        tab_lista, tab_crear = st.tabs(["📋 Lista de Usuarios", "➕ Crear Usuario"])

        with tab_crear:
            with st.form("nuevo_usuario"):
                new_user = st.text_input("Username*")
                new_pass = st.text_input("Password*", type="password")
                nombre = st.text_input("Nombre Completo")
                rol = st.selectbox("Rol", ["analista", "supervisor", "admin"])
                acceso_total = st.checkbox("Acceso Total (Ver todas las empresas)")
                
                todas_empresas = db.query(Empresa).all()
                emp_options = {e.razon_social: e.id for e in todas_empresas}
                seleccionadas = st.multiselect("Asignar Empresas (si no tiene acceso total)", list(emp_options.keys()))
                
                if st.form_submit_button("Registrar Usuario"):
                    if not new_user or not new_pass:
                        st.error("Campos obligatorios faltantes.")
                    else:
                        h = _hash(new_pass)
                        user_obj = Usuario(
                            username=new_user.lower(), password_hash=h, 
                            rol=rol, nombre_completo=nombre, acceso_total=acceso_total
                        )
                        db.add(user_obj)
                        db.flush()
                        
                        if not acceso_total:
                            for emp_nom in seleccionadas:
                                db.add(UsuarioEmpresa(usuario_id=user_obj.id, empresa_id=emp_options[emp_nom]))
                        
                        db.commit()
                        st.success("Usuario creado exitosamente.")
                        st.rerun()

        with tab_lista:
            users = db.query(Usuario).all()
            for u in users:
                with st.container(border=True):
                    col1, col2 = st.columns([3, 1])
                    col1.markdown(f"**{u.nombre_completo or u.username}** ({u.rol})")
                    if u.acceso_total:
                        col1.caption("✅ Acceso Global")
                    else:
                        nombres_emp = [e.razon_social for e in u.empresas_asignadas]
                        col1.caption(f"Empresas: {', '.join(nombres_emp) if nombres_emp else 'Ninguna'}")
                    
                    if col2.button("🗑️", key=f"del_u_{u.id}"):
                        db.delete(u)
                        db.commit()
                        st.rerun()
    finally:
        db.close()
