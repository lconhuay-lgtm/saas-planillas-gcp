"""
Catálogos oficiales SUNAT para PLAME (Tabla 21 y Tabla 22).

Los datos se leen desde archivos Excel en la raíz del proyecto:
  - tabla_ingresos_Plame.xlsx  → CATALOGO_T22_INGRESOS
  - suspensiones_plame.xlsx    → CATALOGO_T21_SUSPENSIONES

Si los archivos no existen, se usan tablas de fallback con los conceptos
más frecuentes.  Para actualizar el catálogo, edita el Excel y reinicia.
"""
from pathlib import Path
import pandas as pd

# Directorio raíz del proyecto (2 niveles arriba de core/domain/)
_BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _leer_excel(filename: str) -> pd.DataFrame | None:
    path = _BASE_DIR / filename
    if path.exists():
        try:
            return pd.read_excel(path, dtype=str)
        except Exception:
            pass
    return None


def _cargar_t22() -> dict:
    """Tabla 22 PLAME — Conceptos Remunerativos."""
    df = _leer_excel("tabla_ingresos_Plame.xlsx")
    if df is not None and not df.empty:
        result: dict = {}
        for _, row in df.iterrows():
            codigo = str(row.get("codigo", "")).strip().zfill(4)
            if not codigo or codigo == "0000":
                continue
            result[codigo] = {
                "desc":     str(row.get("descripcion", "")).strip(),
                "tipo":     str(row.get("tipo", "INGRESO")).strip().upper(),
                "afp":      str(row.get("afecto_afp",     "S")).strip().upper() == "S",
                "quinta":   str(row.get("afecto_quinta",  "S")).strip().upper() == "S",
                "essalud":  str(row.get("afecto_essalud", "S")).strip().upper() == "S",
            }
        if result:
            return result

    # ── Fallback hardcoded ────────────────────────────────────────────────────
    return {
        "0121": {"desc": "Sueldo o Salario Básico",            "tipo": "INGRESO",   "afp": True,  "quinta": True,  "essalud": True},
        "0122": {"desc": "Salario por hora",                   "tipo": "INGRESO",   "afp": True,  "quinta": True,  "essalud": True},
        "0201": {"desc": "Asignación Familiar",                "tipo": "INGRESO",   "afp": True,  "quinta": True,  "essalud": True},
        "0301": {"desc": "Bonificación por Producción",        "tipo": "INGRESO",   "afp": True,  "quinta": True,  "essalud": True},
        "0302": {"desc": "Bonificación por Turno",             "tipo": "INGRESO",   "afp": True,  "quinta": True,  "essalud": True},
        "0303": {"desc": "Bonificación por Cumpleaños",        "tipo": "INGRESO",   "afp": False, "quinta": True,  "essalud": False},
        "0305": {"desc": "Bonificación Extraordinaria 9%",     "tipo": "INGRESO",   "afp": False, "quinta": True,  "essalud": False},
        "0401": {"desc": "Gratificación Ordinaria (Jul/Dic)",  "tipo": "INGRESO",   "afp": False, "quinta": True,  "essalud": False},
        "0402": {"desc": "Gratificación Extraordinaria",       "tipo": "INGRESO",   "afp": False, "quinta": True,  "essalud": False},
        "0601": {"desc": "Participación en Utilidades",        "tipo": "INGRESO",   "afp": True,  "quinta": True,  "essalud": False},
        "0701": {"desc": "Movilidad / Condición de Trabajo",   "tipo": "INGRESO",   "afp": False, "quinta": False, "essalud": False},
        "0702": {"desc": "Refrigerio (no remunerativo)",       "tipo": "INGRESO",   "afp": False, "quinta": False, "essalud": False},
        "0801": {"desc": "Horas Extras 25%",                   "tipo": "INGRESO",   "afp": True,  "quinta": True,  "essalud": True},
        "0802": {"desc": "Horas Extras 35%",                   "tipo": "INGRESO",   "afp": True,  "quinta": True,  "essalud": True},
        "0901": {"desc": "Comisiones",                         "tipo": "INGRESO",   "afp": True,  "quinta": True,  "essalud": True},
        "0903": {"desc": "Otros Ingresos Gravados",            "tipo": "INGRESO",   "afp": True,  "quinta": True,  "essalud": True},
        "0904": {"desc": "Adelanto de Remuneraciones",         "tipo": "DESCUENTO", "afp": False, "quinta": False, "essalud": False},
        "0905": {"desc": "Descuento Judicial (Alimentos)",     "tipo": "DESCUENTO", "afp": False, "quinta": False, "essalud": False},
        "0906": {"desc": "Préstamo del Empleador",             "tipo": "DESCUENTO", "afp": False, "quinta": False, "essalud": False},
    }


def _cargar_t21() -> dict:
    """Tabla 21 PLAME — Tipos de suspensión / inasistencia."""
    df = _leer_excel("suspensiones_plame.xlsx")
    if df is not None and not df.empty:
        result: dict = {}
        for _, row in df.iterrows():
            codigo = str(row.get("codigo", "")).strip().zfill(2)
            if not codigo or codigo == "00":
                continue
            result[codigo] = str(row.get("descripcion", "")).strip()
        if result:
            return result

    # ── Fallback hardcoded ────────────────────────────────────────────────────
    return {
        "07": "Inasistencia Injustificada",
        "08": "Huelga",
        "09": "Sanción Disciplinaria",
        "16": "Licencia sin goce de haber",
        "17": "Permiso o Licencia particular",
        "20": "Descanso Médico (ESSALUD)",
        "21": "Descanso Médico (EPS)",
        "22": "Accidente de Trabajo / Enfermedad Profesional",
        "23": "Vacaciones",
        "24": "Descanso por Maternidad / Paternidad",
        "25": "Licencia con goce de haber",
        "26": "Licencia por Maternidad (pre/post natal)",
        "27": "Licencia por Paternidad",
        "28": "Comisión Sindical",
    }


# ── Módulo-level constants ────────────────────────────────────────────────────
CATALOGO_T22_INGRESOS: dict     = _cargar_t22()
CATALOGO_T21_SUSPENSIONES: dict = _cargar_t21()
