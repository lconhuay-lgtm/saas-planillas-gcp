import hashlib
import streamlit as st
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Usuario


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _seed_usuarios(db):
    """Crea los usuarios por defecto si la tabla está vacía."""
    if db.query(Usuario).count() == 0:
        usuarios_default = [
            Usuario(
                username="analista",
                password_hash=_hash("analista123"),
                rol="analista",
                nombre_completo="Analista de Planillas",
                activo=True,
            ),
            Usuario(
                username="supervisor",
                password_hash=_hash("supervisor123"),
                rol="supervisor",
                nombre_completo="Supervisor de Planillas",
                activo=True,
            ),
        ]
        db.add_all(usuarios_default)
        db.commit()


def render():
    """Pantalla de inicio de sesión. Retorna True si el login fue exitoso."""
    st.markdown("""
    <style>
        .login-box {
            max-width: 420px;
            margin: 60px auto;
            padding: 40px 36px;
            background: #0F2744;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.28);
        }
        .login-title {
            color: #FFFFFF;
            font-size: 1.55rem;
            font-weight: 700;
            margin-bottom: 4px;
        }
        .login-sub {
            color: #90CAF9;
            font-size: 0.85rem;
            margin-bottom: 28px;
        }
    </style>
    <div class="login-box">
        <div class="login-title">💼 ERP Planillas SaaS</div>
        <div class="login-sub">Sistema de Gestión de Nóminas — Acceso Restringido</div>
    </div>
    """, unsafe_allow_html=True)

    with st.form("form_login", clear_on_submit=False):
        st.markdown("#### Iniciar Sesión")
        username = st.text_input("Usuario", placeholder="Ingrese su usuario")
        password = st.text_input("Contraseña", type="password", placeholder="Ingrese su contraseña")
        submitted = st.form_submit_button("Ingresar", use_container_width=True, type="primary")

    if submitted:
        if not username or not password:
            st.error("Complete todos los campos.")
            return False

        try:
            db = SessionLocal()
            _seed_usuarios(db)
            usuario = db.query(Usuario).filter_by(
                username=username.strip().lower(),
                password_hash=_hash(password),
                activo=True,
            ).first()
            db.close()
        except Exception as e:
            st.error(f"Error de conexión: {e}")
            return False

        if usuario:
            st.session_state['usuario_logueado']  = usuario.username
            st.session_state['usuario_rol']        = usuario.rol
            st.session_state['usuario_nombre']     = usuario.nombre_completo or usuario.username
            st.rerun()
            return True
        else:
            st.error("Usuario o contraseña incorrectos.")
            return False

    return False
