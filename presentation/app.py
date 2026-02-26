import sys
import os

# Forzar a Python a reconocer la carpeta raíz del proyecto
ruta_raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ruta_raiz not in sys.path:
    sys.path.append(ruta_raiz)

import streamlit as st
from presentation.session_state import inicializar_estado
from presentation.components.sidebar import render_sidebar

# Importación de las Vistas
from presentation.views import selector_empresa
from presentation.views import maestro_trabajadores  # ✅ AHORA SÍ IMPORTAMOS EL MAESTRO
from presentation.views import ingreso_asistencias # ✅ NUEVO
from presentation.views import calculo_mensual  # ✅ AGREGAMOS ESTO
from presentation.views import parametros_legales
from presentation.views import maestro_conceptos
from presentation.views import emision_boletas

# 1. Configuración Ejecutiva de la Página
st.set_page_config(
    page_title="Sistema de Planillas SaaS",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. Inyección de CSS Corporativo
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

# 3. Inicializar el cerebro de la app
inicializar_estado()

# 4. Renderizar el Menú Lateral
vista_actual = render_sidebar()

# 5. Enrutador (Router)
if vista_actual == "Selector":
    selector_empresa.render()
    
elif vista_actual == "Dashboard":
    st.title(f"Dashboard: {st.session_state['empresa_activa_nombre']}")
    st.info("Aquí mostraremos los gráficos de costo laboral y alertas de contratos por vencer.")

elif vista_actual == "Maestro de Personal":
    maestro_trabajadores.render()  # ✅ AHORA SÍ LLAMAMOS A LA INTERFAZ REAL

elif vista_actual == "Ingreso de Asistencias":
    ingreso_asistencias.render() # ✅ AHORA LLAMA A LA INTERFAZ REAL

elif vista_actual == "Cálculo de Planilla":
    calculo_mensual.render()  # ✅ LLAMAMOS A LA NUEVA VISTA

# En el enrutador (abajo), agrega esta condición:
elif vista_actual == "Parámetros Legales":
    parametros_legales.render()
    
elif vista_actual == "Maestro de Conceptos":
    maestro_conceptos.render()
    
elif vista_actual == "Emisión de Boletas":
        emision_boletas.render()