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
            Usuario(username="admin",   password_hash=_hash("admin123"),
                    rol="admin",   nombre_completo="Administrador del Sistema", 
                    activo=True, acceso_total=True),
            Usuario(username="analista",   password_hash=_hash("analista123"),
                    rol="analista",   nombre_completo="Analista de Planillas", activo=True),
            Usuario(username="supervisor", password_hash=_hash("supervisor123"),
                    rol="supervisor", nombre_completo="Supervisor de Planillas", 
                    activo=True, acceso_total=True),
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
    /* Ocultar chrome de Streamlit durante el login */
    [data-testid="stSidebar"]        { display: none !important; }
    header[data-testid="stHeader"]   { background: transparent !important; box-shadow: none !important; }
    [data-testid="stToolbar"]        { display: none !important; }
    [data-testid="stDecoration"]     { display: none !important; }
    #MainMenu, footer                { visibility: hidden !important; }

    /* ── Columna principal muy angosta y centrada ─────────────────── */
    .main .block-container {
        max-width      : 300px  !important;
        padding-top    : 6vh    !important;
        padding-bottom : 2vh    !important;
        padding-left   : 0.5rem !important;
        padding-right  : 0.5rem !important;
        margin         : 0 auto !important;
    }

    /* ── Tarjeta del formulario ───────────────────────────────────── */
    [data-testid="stForm"] {
        background     : rgba(7, 18, 36, 0.96)          !important;
        border         : 1px solid rgba(30,136,229,.28)  !important;
        border-radius  : 10px                            !important;
        padding        : 24px 22px 20px 22px             !important;
        box-shadow     : 0 20px 56px rgba(0,0,0,.65)     !important;
    }

    /* ── Labels ─────────────────────────────────────────────────── */
    .stTextInput label p {
        color          : #7EB8F7  !important;
        font-size      : 0.68rem  !important;
        font-weight    : 700      !important;
        letter-spacing : 0.10em   !important;
        text-transform : uppercase !important;
        margin-bottom  : 2px      !important;
    }

    /* ── Inputs — fondo claro + texto oscuro para legibilidad ─────── */
    .stTextInput > div > div > input,
    .stTextInput > div > div > input[type="password"] {
        background-color      : #E8F0FE                     !important;
        border                : 1.5px solid #1565C0          !important;
        border-radius         : 5px                          !important;
        color                 : #0D1B3E                      !important;
        -webkit-text-fill-color: #0D1B3E                     !important;
        caret-color           : #0D1B3E                      !important;
        font-size             : 0.84rem                      !important;
        padding               : 6px 10px                     !important;
        height                : 34px                         !important;
        transition            : border-color .15s, box-shadow .15s !important;
    }
    .stTextInput > div > div > input:focus {
        border-color          : #1E88E5                      !important;
        box-shadow            : 0 0 0 3px rgba(30,136,229,.22) !important;
        background-color      : #FFFFFF                      !important;
        -webkit-text-fill-color: #0D1B3E                     !important;
        outline               : none                         !important;
    }
    .stTextInput > div > div > input::placeholder {
        color        : rgba(13,27,62,.40) !important;
        font-size    : 0.80rem            !important;
    }

    /* ── Botón enviar ─────────────────────────────────────────────── */
    [data-testid="stFormSubmitButton"] button {
        background    : linear-gradient(90deg,#1249A0,#1976D2) !important;
        border        : none                              !important;
        border-radius : 5px                               !important;
        color         : #FFFFFF                           !important;
        font-size     : 0.72rem                           !important;
        font-weight   : 700                               !important;
        letter-spacing: 0.12em                            !important;
        text-transform: uppercase                         !important;
        height        : 36px                              !important;
        box-shadow    : 0 4px 14px rgba(25,118,210,.40)   !important;
        transition    : all .15s                          !important;
        margin-top    : 4px                               !important;
    }
    [data-testid="stFormSubmitButton"] button:hover {
        background    : linear-gradient(90deg,#1565C0,#1E88E5) !important;
        box-shadow    : 0 6px 20px rgba(30,136,229,.55)   !important;
        transform     : translateY(-1px)                  !important;
    }

    /* ── Alertas ─────────────────────────────────────────────────── */
    [data-testid="stAlert"] {
        border-radius : 6px     !important;
        font-size     : 0.78rem !important;
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
