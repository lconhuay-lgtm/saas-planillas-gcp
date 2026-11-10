import os
from datetime import datetime

import streamlit as st
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Usuario
from infrastructure.services.seguridad import (
    hash_password, verificar_password, verificar_contra_señuelo, necesita_rehash,
    validar_politica, esta_bloqueado, registrar_intento_fallido,
    CLAVES_POR_DEFECTO, MINUTOS_BLOQUEO,
)


def _crear_admin_inicial(db) -> bool:
    """
    Solo si la tabla de usuarios está VACÍA: crea el usuario 'admin' con la clave de
    la variable de entorno ADMIN_INITIAL_PASSWORD (Secret Manager en Cloud Run) y lo
    obliga a cambiarla en el primer ingreso. Ya no existen claves fijas en el código.
    """
    if db.query(Usuario).count() > 0:
        return False
    clave_inicial = (os.getenv("ADMIN_INITIAL_PASSWORD") or "").strip()
    if not clave_inicial:
        return False
    db.add(Usuario(
        username="admin", password_hash=hash_password(clave_inicial), rol="admin",
        nombre_completo="Administrador del Sistema", activo=True, acceso_total=True,
        debe_cambiar_password=True,
    ))
    db.commit()
    return True


def _autenticar(db, username: str, password: str) -> tuple:
    """Devuelve (usuario | None, mensaje_error | None)."""
    usuario = db.query(Usuario).filter_by(username=username, activo=True).first()
    if not usuario:
        verificar_contra_señuelo(password)
        return None, "Usuario o contraseña incorrectos."

    if esta_bloqueado(usuario.bloqueado_hasta):
        return None, (f"Cuenta bloqueada temporalmente por intentos fallidos. "
                      f"Intente nuevamente en unos minutos (bloqueo de {MINUTOS_BLOQUEO} min).")

    if not verificar_password(password, usuario.password_hash):
        intentos, bloqueo = registrar_intento_fallido(usuario.intentos_fallidos)
        usuario.intentos_fallidos = intentos
        usuario.bloqueado_hasta = bloqueo
        db.commit()
        if bloqueo:
            return None, (f"Demasiados intentos fallidos: la cuenta quedó bloqueada "
                          f"{MINUTOS_BLOQUEO} minutos.")
        return None, "Usuario o contraseña incorrectos."

    # Login correcto: limpiar contadores, migrar hash antiguo y forzar cambio si
    # todavía usa una de las claves que el sistema sembraba por defecto.
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    usuario.ultimo_login = datetime.now()
    if password.lower() in CLAVES_POR_DEFECTO:
        usuario.debe_cambiar_password = True
    if necesita_rehash(usuario.password_hash):
        usuario.password_hash = hash_password(password)
    db.commit()
    return usuario, None


def render_cambio_password(obligatorio: bool = False, key: str = "cambio_pw") -> None:
    """Formulario para que el usuario conectado cambie su propia contraseña."""
    username = st.session_state.get('usuario_logueado')
    if not username:
        return
    if obligatorio:
        st.title("🔑 Cambio de contraseña obligatorio")
        st.warning("Por seguridad debe definir una contraseña nueva antes de continuar.")

    with st.form(f"form_{key}", clear_on_submit=True):
        actual = st.text_input("Contraseña actual", type="password")
        nueva = st.text_input("Contraseña nueva", type="password",
                              help="Mínimo 10 caracteres, con letras y números.")
        confirmar = st.text_input("Confirmar contraseña nueva", type="password")
        enviado = st.form_submit_button("Guardar contraseña", type="primary",
                                        use_container_width=True)
    if not enviado:
        return

    if nueva != confirmar:
        st.error("La confirmación no coincide con la contraseña nueva.")
        return
    error_politica = validar_politica(nueva, username)
    if error_politica:
        st.error(error_politica)
        return
    if nueva == actual:
        st.error("La contraseña nueva debe ser distinta de la actual.")
        return

    db = SessionLocal()
    try:
        usuario = db.query(Usuario).filter_by(username=username, activo=True).first()
        if not usuario or not verificar_password(actual, usuario.password_hash):
            st.error("La contraseña actual no es correcta.")
            return
        usuario.password_hash = hash_password(nueva)
        usuario.debe_cambiar_password = False
        usuario.intentos_fallidos = 0
        usuario.bloqueado_hasta = None
        db.commit()
    finally:
        db.close()

    st.session_state['debe_cambiar_password'] = False
    st.success("✅ Contraseña actualizada.")
    if obligatorio:
        st.rerun()


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

        db = SessionLocal()
        try:
            _crear_admin_inicial(db)
            usuario, error_login = _autenticar(db, username.strip().lower(), password)
            if usuario:
                datos_sesion = {
                    'usuario_logueado':      usuario.username,
                    'usuario_rol':           usuario.rol,
                    'usuario_nombre':        usuario.nombre_completo or usuario.username,
                    'debe_cambiar_password': bool(usuario.debe_cambiar_password),
                }
        except Exception:
            db.rollback()
            st.error("No se pudo validar el acceso. Intente nuevamente en unos minutos.")
            return False
        finally:
            db.close()

        if usuario:
            st.session_state.update(datos_sesion)
            st.rerun()
            return True
        st.error(error_login)
        return False

    # ── Pie de página ──────────────────────────────────────────────────────────
    st.markdown(
        "<p style='color:rgba(126,184,247,.22); font-size:0.60rem; "
        "text-align:center; margin-top:16px; letter-spacing:0.06em;'>"
        "© 2025 Planillas Pro &nbsp;·&nbsp; Acceso Autorizado</p>",
        unsafe_allow_html=True,
    )
    return False
