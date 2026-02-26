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
from presentation.views import maestro_trabajadores
from presentation.views import ingreso_asistencias
from presentation.views import calculo_mensual
from presentation.views import parametros_legales
from presentation.views import maestro_conceptos
from presentation.views import emision_boletas

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

# 4. Renderizar el Menú Lateral y obtener qué vista quiere ver el usuario
vista_actual = render_sidebar()

# 5. Enrutador Principal (Router)
if vista_actual == "Selector de Empresa" or vista_actual is None:
    selector_empresa.render()
    
elif vista_actual == "Dashboard Principal":
    st.title("📊 Dashboard Analítico")
    st.info("Aquí construiremos el panel de gráficos estadísticos de la empresa en la próxima fase.")

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