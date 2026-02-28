import sys
import os

# Forzar a Python a reconocer la carpeta raíz del proyecto
ruta_raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ruta_raiz not in sys.path:
    sys.path.append(ruta_raiz)

import streamlit as st

# 1. Configuración Ejecutiva de la Página (Debe ir siempre primero)
st.set_page_config(
    page_title="Sistema de Planillas SaaS",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

from presentation.session_state import inicializar_estado
from presentation.components.sidebar import render_sidebar

# Importación de las Vistas
from presentation.views import selector_empresa
from presentation.views import dashboard
from presentation.views import maestro_trabajadores
from presentation.views import ingreso_asistencias
from presentation.views import calculo_mensual
from presentation.views import parametros_legales
from presentation.views import maestro_conceptos
from presentation.views import emision_boletas
from presentation.views import reporteria
from presentation.views import login
from presentation.views import prestamos
from presentation.views import gestion_usuarios

# ── AUTO-CREAR TABLAS EN NEON (seguro: no borra datos existentes) ──────────────
if not st.session_state.get('_tablas_verificadas'):
    try:
        from infrastructure.database.connection import engine, Base
        from sqlalchemy import text
        import infrastructure.database.models  # noqa: registra todos los modelos en Base.metadata
        Base.metadata.create_all(bind=engine)
        # Migraciones incrementales: añaden columnas nuevas sin borrar datos
        _migraciones = [
            # Usuarios y Accesos
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS acceso_total BOOLEAN DEFAULT false",
            # Seguro social (lote anterior)
            "ALTER TABLE trabajadores ADD COLUMN IF NOT EXISTS seguro_social VARCHAR(20) DEFAULT 'ESSALUD'",
            # Cierre de planilla (lote anterior)
            "ALTER TABLE planillas_mensuales ADD COLUMN IF NOT EXISTS estado VARCHAR(10) DEFAULT 'ABIERTA'",
            "ALTER TABLE planillas_mensuales ADD COLUMN IF NOT EXISTS cerrada_por VARCHAR(100)",
            "ALTER TABLE planillas_mensuales ADD COLUMN IF NOT EXISTS fecha_cierre TIMESTAMP",
            # PLAME / AFPnet (lote actual)
            "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS horas_jornada_diaria FLOAT DEFAULT 8.0",
            "ALTER TABLE conceptos ADD COLUMN IF NOT EXISTS codigo_sunat VARCHAR(4)",
            "ALTER TABLE trabajadores ADD COLUMN IF NOT EXISTS apellido_paterno VARCHAR(100)",
            "ALTER TABLE trabajadores ADD COLUMN IF NOT EXISTS apellido_materno VARCHAR(100)",
            "ALTER TABLE variables_mes ADD COLUMN IF NOT EXISTS suspensiones_json TEXT DEFAULT '{}'",
            # Locadores de Servicio (4ta Categoría) — lote actual
            "ALTER TABLE trabajadores ADD COLUMN IF NOT EXISTS tipo_contrato VARCHAR(20) DEFAULT 'PLANILLA'",
            "ALTER TABLE variables_mes ADD COLUMN IF NOT EXISTS dias_descuento_locador INTEGER DEFAULT 0",
            "ALTER TABLE parametros_legales ADD COLUMN IF NOT EXISTS tasa_4ta FLOAT DEFAULT 8.0",
            "ALTER TABLE parametros_legales ADD COLUMN IF NOT EXISTS tope_4ta FLOAT DEFAULT 1500.0",
            # Suspensión de retenciones 4ta Cat. para locadores con constancia SUNAT
            "ALTER TABLE trabajadores ADD COLUMN IF NOT EXISTS tiene_suspension_4ta BOOLEAN DEFAULT false",
            # Préstamos y Descuentos Programados
            "CREATE TABLE IF NOT EXISTS prestamos (id SERIAL PRIMARY KEY, empresa_id INTEGER NOT NULL REFERENCES empresas(id), trabajador_id INTEGER NOT NULL REFERENCES trabajadores(id), concepto VARCHAR(100) DEFAULT 'Préstamo Personal', monto_total FLOAT NOT NULL, numero_cuotas INTEGER NOT NULL, fecha_otorgamiento DATE, estado VARCHAR(20) DEFAULT 'ACTIVO')",
            "CREATE TABLE IF NOT EXISTS cuotas_prestamo (id SERIAL PRIMARY KEY, prestamo_id INTEGER NOT NULL REFERENCES prestamos(id) ON DELETE CASCADE, numero_cuota INTEGER NOT NULL, periodo_key VARCHAR(10) NOT NULL, monto FLOAT NOT NULL, estado VARCHAR(20) DEFAULT 'PENDIENTE')",
            # Forzar actualización de campos críticos en todas las empresas
            "ALTER TABLE trabajadores ALTER COLUMN tipo_contrato SET DEFAULT 'PLANILLA'",
            "UPDATE trabajadores SET tipo_contrato = 'PLANILLA' WHERE tipo_contrato IS NULL",
        ]
        with engine.connect() as _conn:
            for _sql in _migraciones:
                _conn.execute(text(_sql))
            _conn.commit()
            _conn.execute(text("COMMIT")) # Asegurar persistencia física en Neon
        st.session_state['_tablas_verificadas'] = True
    except Exception as _err_tablas:
        st.error(f"❌ No se pudo conectar a la base de datos: {_err_tablas}")
        st.stop()
# ───────────────────────────────────────────────────────────────────────────────

# 2. CSS Corporativo
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        .stButton>button {
            border-radius: 5px;
            font-weight: bold;
            transition: all 0.3s ease;
        }
        .stButton>button:hover {
            border-color: #1f77b4;
            color: #1f77b4;
        }
    </style>
""", unsafe_allow_html=True)

# 3. Inicializar estado
inicializar_estado()

# ── GUARDA DE AUTENTICACIÓN ───────────────────────────────────────────────────
# Si el usuario no ha iniciado sesión, mostramos solo la pantalla de login.
if not st.session_state.get('usuario_logueado'):
    login.render()
    st.stop()
# ─────────────────────────────────────────────────────────────────────────────

# 4. Sidebar y enrutador (solo si está autenticado)
vista_actual = render_sidebar()

# 5. Enrutador Principal
if vista_actual == "Selector de Empresa" or vista_actual is None:
    selector_empresa.render()

elif vista_actual == "Dashboard Principal":
    dashboard.render()

elif vista_actual == "Maestro de Personal":
    maestro_trabajadores.render()

elif vista_actual == "Parámetros Legales":
    parametros_legales.render()

elif vista_actual == "Ingreso de Asistencias":
    ingreso_asistencias.render()

elif vista_actual == "Cálculo de Planilla":
    calculo_mensual.render()

elif vista_actual == "Maestro de Conceptos":
    maestro_conceptos.render()

elif vista_actual == "Emisión de Boletas":
    emision_boletas.render()

elif vista_actual == "Reportería":
    reporteria.render()

elif vista_actual == "Préstamos y Descuentos":
    prestamos.render()

elif vista_actual == "Gestión de Usuarios":
    gestion_usuarios.render()
