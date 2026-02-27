import hashlib
import streamlit as st
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Usuario


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _seed_usuarios(db):
    """Crea los usuarios por defecto si la tabla está vacía."""
    if db.query(Usuario).count() == 0:
        db.add_all([
            Usuario(username="analista",   password_hash=_hash("analista123"),
                    rol="analista",   nombre_completo="Analista de Planillas", activo=True),
            Usuario(username="supervisor", password_hash=_hash("supervisor123"),
                    rol="supervisor", nombre_completo="Supervisor de Planillas", activo=True),
        ])
        db.commit()


def render():
    """Pantalla de inicio de sesión — diseño corporativo BI."""

    st.markdown("""
    <style>
    /* ── Fondo degradado corporativo ──────────────────────────────── */
    .stApp {
        background: linear-gradient(160deg, #03080F 0%, #071526 45%, #0A2040 100%) !important;
    }
    /* Ocultar elementos de Streamlit durante el login */
    [data-testid="stSidebar"]          { display: none !important; }
    header[data-testid="stHeader"]     { background: transparent !important; box-shadow: none !important; }
    [data-testid="stToolbar"]          { display: none !important; }
    #MainMenu, footer                  { visibility: hidden !important; }
    /* Ocultar decoración de barra superior */
    [data-testid="stDecoration"]       { display: none !important; }

    /* ── Centrar y acotar el contenido ────────────────────────────── */
    .main .block-container {
        max-width: 360px !important;
        padding-top: 7vh   !important;
        padding-bottom: 2vh !important;
        padding-left:  1rem !important;
        padding-right: 1rem !important;
        margin: 0 auto  !important;
    }

    /* ── Tarjeta del formulario ───────────────────────────────────── */
    [data-testid="stForm"] {
        background    : rgba(8, 22, 42, 0.92)       !important;
        border        : 1px solid rgba(30,136,229,.22) !important;
        border-radius : 10px                         !important;
        padding       : 28px 30px 24px 30px          !important;
        box-shadow    : 0 24px 64px rgba(0,0,0,.55)  !important;
        backdrop-filter: blur(14px)                  !important;
    }

    /* ── Etiquetas de campo ──────────────────────────────────────── */
    .stTextInput label p {
        color          : #7EB8F7           !important;
        font-size      : 0.70rem           !important;
        font-weight    : 600               !important;
        letter-spacing : 0.10em           !important;
        text-transform : uppercase         !important;
        margin-bottom  : 4px              !important;
    }

    /* ── Inputs ──────────────────────────────────────────────────── */
    .stTextInput > div > div > input {
        background-color : rgba(255,255,255,0.04) !important;
        border           : 1px solid rgba(30,136,229,.30) !important;
        border-radius    : 5px     !important;
        color            : #E3F2FD !important;
        font-size        : 0.85rem !important;
        padding          : 7px 11px !important;
        height           : 36px    !important;
        transition       : border-color .18s, box-shadow .18s !important;
    }
    .stTextInput > div > div > input:focus {
        border-color     : #1E88E5 !important;
        box-shadow       : 0 0 0 3px rgba(30,136,229,.18) !important;
        background-color : rgba(255,255,255,.07) !important;
        outline          : none !important;
    }
    .stTextInput > div > div > input::placeholder {
        color: rgba(144,202,249,.40) !important;
        font-size: 0.82rem !important;
    }

    /* ── Botón de envío ──────────────────────────────────────────── */
    [data-testid="stFormSubmitButton"] button {
        background    : linear-gradient(90deg, #1249A0 0%, #1976D2 100%) !important;
        border        : none                             !important;
        border-radius : 5px                              !important;
        color         : #FFFFFF                          !important;
        font-size     : 0.75rem                          !important;
        font-weight   : 700                              !important;
        letter-spacing: 0.14em                           !important;
        text-transform: uppercase                        !important;
        height        : 38px                             !important;
        box-shadow    : 0 4px 16px rgba(25,118,210,.35)  !important;
        transition    : all .18s                         !important;
        margin-top    : 6px                              !important;
    }
    [data-testid="stFormSubmitButton"] button:hover {
        background    : linear-gradient(90deg, #1565C0 0%, #1E88E5 100%) !important;
        box-shadow    : 0 6px 22px rgba(30,136,229,.50)  !important;
        transform     : translateY(-1px)                 !important;
    }
    [data-testid="stFormSubmitButton"] button:active {
        transform: translateY(0) !important;
        box-shadow: 0 2px 8px rgba(30,136,229,.30) !important;
    }

    /* ── Mensajes de alerta (error/success) ──────────────────────── */
    [data-testid="stAlert"] {
        border-radius : 6px      !important;
        font-size     : 0.80rem  !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Logo y marca ───────────────────────────────────────────────────────────
    st.markdown("""
    <div style="text-align:center; padding: 4px 0 18px 0;">
        <div style="
            display:inline-flex; align-items:center; justify-content:center;
            width:50px; height:50px;
            background:linear-gradient(135deg,#1249A0,#1976D2);
            border-radius:11px;
            margin-bottom:13px;
            box-shadow:0 6px 22px rgba(25,118,210,.45);
        ">
            <span style="font-size:1.45rem; line-height:1;">📊</span>
        </div>
        <div style="
            color:#FFFFFF;
            font-size:1.10rem;
            font-weight:700;
            letter-spacing:0.14em;
            margin-bottom:3px;
            font-family: 'Segoe UI', system-ui, sans-serif;
        ">PLANILLAS PRO</div>
        <div style="
            color:rgba(126,184,247,.55);
            font-size:0.62rem;
            letter-spacing:0.20em;
            text-transform:uppercase;
        ">Sistema de Gestión de Nóminas</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Formulario ─────────────────────────────────────────────────────────────
    with st.form("form_login", clear_on_submit=False):
        st.markdown(
            "<p style='color:rgba(255,255,255,.38); font-size:0.70rem; "
            "letter-spacing:0.08em; text-align:center; margin:0 0 18px 0; "
            "text-transform:uppercase;'>Acceso Restringido — Identifíquese</p>",
            unsafe_allow_html=True,
        )
        username  = st.text_input("Usuario",     placeholder="usuario")
        password  = st.text_input("Contraseña",  type="password", placeholder="contraseña")
        submitted = st.form_submit_button("Ingresar al Sistema",
                                          use_container_width=True, type="primary")

    # ── Procesamiento ──────────────────────────────────────────────────────────
    if submitted:
        if not username or not password:
            st.error("Complete usuario y contraseña.")
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
            st.session_state['usuario_logueado'] = usuario.username
            st.session_state['usuario_rol']       = usuario.rol
            st.session_state['usuario_nombre']    = usuario.nombre_completo or usuario.username
            st.rerun()
            return True
        else:
            st.error("Usuario o contraseña incorrectos.")
            return False

    # ── Pie de página ──────────────────────────────────────────────────────────
    st.markdown(
        "<p style='color:rgba(126,184,247,.22); font-size:0.60rem; "
        "text-align:center; margin-top:16px; letter-spacing:0.06em;'>"
        "© 2025 Planillas Pro &nbsp;·&nbsp; Acceso Autorizado</p>",
        unsafe_allow_html=True,
    )
    return False
