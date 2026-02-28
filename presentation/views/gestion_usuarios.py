import streamlit as st
import hashlib
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Usuario, Empresa, UsuarioEmpresa

def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def render():
    if st.session_state.get('usuario_rol') != 'admin':
        st.error("🚫 Acceso restringido. Solo el Administrador del Sistema puede gestionar usuarios y permisos.")
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
                        st.session_state['_msg_usuario'] = f"✅ Usuario **{new_user}** creado exitosamente."
                        st.rerun()

        if st.session_state.get('_msg_usuario'):
            st.success(st.session_state.pop('_msg_usuario'))

        with tab_lista:
            users = db.query(Usuario).all()
            todas_empresas = db.query(Empresa).all()
            emp_options = {e.razon_social: e.id for e in todas_empresas}

            for u in users:
                with st.container(border=True):
                    col_info, col_btn = st.columns([3, 1])
                    col_info.markdown(f"**{u.nombre_completo or u.username}** (`{u.username}`)")
                    
                    # Formulario de edición por cada usuario
                    with st.expander(f"⚙️ Editar Permisos: {u.username}"):
                        edit_rol = st.selectbox("Rol", ["analista", "supervisor", "admin"], 
                                               index=["analista", "supervisor", "admin"].index(u.rol),
                                               key=f"edit_rol_{u.id}")
                        edit_total = st.checkbox("Acceso Total", value=u.acceso_total, key=f"edit_tot_{u.id}")
                        
                        asignadas_nombres = [e.razon_social for e in u.empresas_asignadas]
                        edit_emp = st.multiselect("Empresas Asignadas", list(emp_options.keys()),
                                                 default=asignadas_nombres if not edit_total else [],
                                                 disabled=edit_total,
                                                 key=f"edit_emp_{u.id}")
                        
                        if st.button("Actualizar Usuario", key=f"btn_upd_{u.id}"):
                            u.rol = edit_rol
                            u.acceso_total = edit_total
                            # Limpiar y reasignar empresas
                            u.empresas_asignadas = []
                            if not edit_total:
                                for emp_nom in edit_emp:
                                    emp_obj = db.query(Empresa).get(emp_options[emp_nom])
                                    u.empresas_asignadas.append(emp_obj)
                            db.commit()
                            st.success(f"Usuario {u.username} actualizado.")
                            st.rerun()

                    if col_btn.button("🗑️ Eliminar", key=f"del_u_{u.id}", use_container_width=True):
                        if u.username == st.session_state.get('usuario_logueado'):
                            st.error("No puedes eliminarte a ti mismo.")
                        else:
                            db.delete(u)
                            db.commit()
                            st.rerun()
    finally:
        db.close()
