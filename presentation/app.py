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
    initial_sidebar_state="auto"
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
from presentation.views import kardex_vacaciones
from presentation.views import login
from presentation.views import prestamos
from presentation.views import gestion_usuarios
from presentation.views import liquidacion_cese
from presentation.views import gratificaciones_cts
from presentation.views import autorizacion_boletas
from presentation.views import configuracion_contable

# ── AUTO-CREAR TABLAS EN NEON (seguro: no borra datos existentes) ──────────────
if not st.session_state.get('_tablas_verificadas'):
    try:
        from infrastructure.database.connection import engine, Base
        from sqlalchemy import text
        import infrastructure.database.models  # noqa: registra todos los modelos en Base.metadata
        Base.metadata.create_all(bind=engine)
        # Migraciones incrementales: añaden columnas nuevas sin borrar datos
        _migraciones = [
            # Usuarios y Accesos (Enterprise Pack)
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS email VARCHAR(100)",
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ultimo_login TIMESTAMP",
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS acceso_total BOOLEAN DEFAULT false",
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS modulos_restringidos TEXT DEFAULT '[]'",
            "ALTER TABLE usuario_empresa ADD COLUMN IF NOT EXISTS fecha_asignacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            # Seguro social (lote anterior)
            "ALTER TABLE trabajadores ADD COLUMN IF NOT EXISTS seguro_social VARCHAR(20) DEFAULT 'ESSALUD'",
            # Cierre de planilla (lote anterior)
            "ALTER TABLE planillas_mensuales ADD COLUMN IF NOT EXISTS estado VARCHAR(10) DEFAULT 'ABIERTA'",
            "ALTER TABLE planillas_mensuales ADD COLUMN IF NOT EXISTS cerrada_por VARCHAR(100)",
            "ALTER TABLE planillas_mensuales ADD COLUMN IF NOT EXISTS fecha_cierre TIMESTAMP",
            # PLAME / AFPnet (lote actual)
            "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS horas_jornada_diaria FLOAT DEFAULT 8.0",
            "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS cuenta_cargo_bcp VARCHAR(20)",
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
            # Límite de edad AFP
            "ALTER TABLE parametros_legales ADD COLUMN IF NOT EXISTS edad_maxima_prima_afp INTEGER DEFAULT 65",
            # Préstamos y Descuentos Programados
            "CREATE TABLE IF NOT EXISTS prestamos (id SERIAL PRIMARY KEY, empresa_id INTEGER NOT NULL REFERENCES empresas(id), trabajador_id INTEGER NOT NULL REFERENCES trabajadores(id), concepto VARCHAR(100) DEFAULT 'Préstamo Personal', monto_total FLOAT NOT NULL, numero_cuotas INTEGER NOT NULL, fecha_otorgamiento DATE, estado VARCHAR(20) DEFAULT 'ACTIVO')",
            "CREATE TABLE IF NOT EXISTS cuotas_prestamo (id SERIAL PRIMARY KEY, prestamo_id INTEGER NOT NULL REFERENCES prestamos(id) ON DELETE CASCADE, numero_cuota INTEGER NOT NULL, periodo_key VARCHAR(10) NOT NULL, monto FLOAT NOT NULL, estado VARCHAR(20) DEFAULT 'PENDIENTE')",
            # Forzar actualización de campos críticos en todas las empresas
            "ALTER TABLE trabajadores ALTER COLUMN tipo_contrato SET DEFAULT 'PLANILLA'",
            "UPDATE trabajadores SET tipo_contrato = 'PLANILLA' WHERE tipo_contrato IS NULL",
            "UPDATE trabajadores SET tipo_contrato = 'PLANILLA' WHERE tipo_contrato IS NULL",
            "ALTER TABLE variables_mes ADD COLUMN IF NOT EXISTS notas_gestion TEXT DEFAULT ''",
            "ALTER TABLE conceptos ADD COLUMN IF NOT EXISTS prorrateable_por_asistencia BOOLEAN DEFAULT false",
            "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS factor_proyeccion_grati FLOAT",
            "ALTER TABLE planillas_mensuales ADD COLUMN IF NOT EXISTS honorarios_json TEXT DEFAULT '[]'",
            "ALTER TABLE trabajadores ADD COLUMN IF NOT EXISTS fecha_cese DATE",
            "ALTER TABLE trabajadores ADD COLUMN IF NOT EXISTS dias_vacaciones_anuales INTEGER DEFAULT 30",
            "CREATE TABLE IF NOT EXISTS registro_vacaciones (id SERIAL PRIMARY KEY, trabajador_id INTEGER NOT NULL REFERENCES trabajadores(id), fecha_inicio DATE NOT NULL, fecha_fin DATE NOT NULL, dias_gozados INTEGER DEFAULT 0, dias_vendidos INTEGER DEFAULT 0, periodo_origen VARCHAR(50), estado VARCHAR(20) DEFAULT 'APROBADO', observaciones TEXT, fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
            "ALTER TABLE trabajadores ADD COLUMN IF NOT EXISTS correo_electronico VARCHAR(100)",
            "CREATE TABLE IF NOT EXISTS log_envio_boletas (id SERIAL PRIMARY KEY, empresa_id INTEGER NOT NULL REFERENCES empresas(id), trabajador_id INTEGER NOT NULL REFERENCES trabajadores(id), periodo_key VARCHAR(10) NOT NULL, correo_destino VARCHAR(100) NOT NULL, estado VARCHAR(20) DEFAULT 'ENVIADO', mensaje_error TEXT, fecha_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS modulos_restringidos TEXT DEFAULT '[]'",
            "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS smtp_host VARCHAR(100)",
            "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS smtp_port INTEGER DEFAULT 587",
            "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS smtp_user VARCHAR(100)",
            "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS smtp_pass VARCHAR(100)",
            "ALTER TABLE trabajadores ADD COLUMN IF NOT EXISTS tipo_documento VARCHAR(2) DEFAULT '01'",
            "UPDATE trabajadores SET num_doc = REPLACE(num_doc, ' ', '') WHERE num_doc LIKE '% %'",
            # Depósitos CTS (Beneficios Sociales)
            """CREATE TABLE IF NOT EXISTS depositos_cts (
                id SERIAL PRIMARY KEY,
                empresa_id INTEGER NOT NULL REFERENCES empresas(id),
                trabajador_id INTEGER NOT NULL REFERENCES trabajadores(id),
                periodo_label VARCHAR(30),
                periodo_key_deposito VARCHAR(10),
                base_computable FLOAT DEFAULT 0.0,
                sexto_grati FLOAT DEFAULT 0.0,
                meses_computados FLOAT DEFAULT 0.0,
                factor FLOAT DEFAULT 1.0,
                monto FLOAT DEFAULT 0.0,
                estado VARCHAR(20) DEFAULT 'PENDIENTE',
                fecha_deposito DATE,
                banco_cts VARCHAR(100),
                cuenta_cts VARCHAR(100),
                fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(empresa_id, trabajador_id, periodo_key_deposito)
            )""",
            # Formato de Reporte de Tesorería (Clásico / Detallado) — solo presentación
            "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS formato_reporte_tesoreria VARCHAR(20) DEFAULT 'CLASICO'",
            # Etiqueta "No Remunerativo" para conceptos (Movilidad, Alimentación, etc.) —
            # solo identifica en reportes, no altera afecto_afp/afecto_5ta/afecto_essalud/etc.
            "ALTER TABLE conceptos ADD COLUMN IF NOT EXISTS no_remunerativo BOOLEAN DEFAULT false",
            # Clasificación Recurrente/No Recurrente para la PROYECCIÓN de 5ta categoría.
            # Todos los conceptos ya creados quedan como Recurrente (true) por defecto —
            # editable luego desde Maestro de Conceptos.
            "ALTER TABLE conceptos ADD COLUMN IF NOT EXISTS es_recurrente BOOLEAN DEFAULT true",
            # Autorización obligatoria de envío de boletas (compuerta antes de enviar por correo)
            "ALTER TABLE planillas_mensuales ADD COLUMN IF NOT EXISTS boletas_autorizado BOOLEAN DEFAULT false",
            "ALTER TABLE planillas_mensuales ADD COLUMN IF NOT EXISTS boletas_autorizado_por VARCHAR(100)",
            "ALTER TABLE planillas_mensuales ADD COLUMN IF NOT EXISTS boletas_fecha_autorizacion TIMESTAMP",
            # Asiento Contable — cuenta por concepto (Sueldo Base, Asig. Familiar, dinámicos)
            "ALTER TABLE conceptos ADD COLUMN IF NOT EXISTS cuenta_contable VARCHAR(20)",
            # Asiento Contable — cuentas fijas de sistema (una fila por empresa)
            """CREATE TABLE IF NOT EXISTS configuracion_contable (
                id SERIAL PRIMARY KEY,
                empresa_id INTEGER NOT NULL UNIQUE REFERENCES empresas(id),
                cuenta_horas_extra_25 VARCHAR(20),
                cuenta_horas_extra_35 VARCHAR(20),
                cuenta_descanso_vacacional VARCHAR(20),
                cuenta_descanso_medico VARCHAR(20),
                cuenta_licencia_goce VARCHAR(20),
                cuenta_essalud_gasto VARCHAR(20),
                cuenta_essalud_pasivo VARCHAR(20),
                cuenta_onp VARCHAR(20),
                cuenta_afp_habitat VARCHAR(20),
                cuenta_afp_integra VARCHAR(20),
                cuenta_afp_prima VARCHAR(20),
                cuenta_afp_profuturo VARCHAR(20),
                cuenta_retencion_5ta VARCHAR(20),
                cuenta_remuneraciones_por_pagar VARCHAR(20),
                cuenta_prestamos_personal VARCHAR(20),
                fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
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
        header[data-testid="stHeader"] { height: 0px; background: transparent; }
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

# ── COMPUERTA DE AUTORIZACIÓN DE BOLETAS ────────────────────────────────────────
# Bloquea la navegación a cualquier módulo operativo si la empresa activa tiene
# boletas de un periodo cerrado (desde 07-2026) pendientes de autorizar. No aplica
# al Selector de Empresa ni a Gestión de Usuarios, para no dejar a nadie sin salida.
# periodo_bloqueante() ya descarta los periodos pospuestos esta sesión — si devuelve
# None, no se llama a render() ni a st.stop(), y el enrutador sigue con normalidad.
_empresa_activa_gate = st.session_state.get('empresa_activa_id')
if _empresa_activa_gate and vista_actual not in ("Selector de Empresa", "Gestión de Usuarios", None):
    _periodo_bloqueante = autorizacion_boletas.periodo_bloqueante(_empresa_activa_gate)
    if _periodo_bloqueante:
        autorizacion_boletas.render(_periodo_bloqueante)
        st.stop()
# ─────────────────────────────────────────────────────────────────────────────────

# 5. Enrutador Principal
if vista_actual == "Selector de Empresa" or vista_actual is None:
    selector_empresa.render()

elif vista_actual == "Dashboard Principal":
    dashboard.render()

elif vista_actual == "Maestro de Personal":
    maestro_trabajadores.render()

elif vista_actual == "Parámetros Legales":
    parametros_legales.render()

elif vista_actual == "Configuración Contable":
    configuracion_contable.render()

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

elif vista_actual == "Kardex de Vacaciones":
    kardex_vacaciones.render()

elif vista_actual == "Préstamos y Descuentos":
    prestamos.render()

elif vista_actual == "Gestión de Usuarios":
    gestion_usuarios.render()

elif vista_actual == "Liquidación por Cese":
    liquidacion_cese.render()

elif vista_actual == "Gratificaciones y CTS":
    gratificaciones_cts.render()
