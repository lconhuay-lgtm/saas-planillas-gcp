"""
Catálogos oficiales SUNAT para PLAME (Tabla 21 y Tabla 22).

Los datos se leen desde archivos CSV en la raíz del proyecto:
  - tabla_ingresos_plame.csv  → CATALOGO_T22_INGRESOS
  - suspensiones_plame.csv    → CATALOGO_T21_SUSPENSIONES

Si los archivos no existen, se usan tablas de fallback con los conceptos
más frecuentes.  Para actualizar el catálogo, edita el CSV y reinicia.
"""
from pathlib import Path
import pandas as pd

# Directorio raíz del proyecto (2 niveles arriba de core/domain/)
_BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _leer_csv(filename: str) -> pd.DataFrame | None:
    """Lee un CSV con encoding UTF-8; intenta latin-1 como fallback para
    preservar tildes y eñes escritas con otros editores."""
    path = _BASE_DIR / filename
    if not path.exists():
        return None
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(path, dtype=str, encoding=enc, sep=",")
            if not df.empty:
                return df
        except (UnicodeDecodeError, Exception):
            continue
    return None


def _cargar_t22() -> dict:
    """Tabla 22 PLAME — Conceptos Remunerativos."""
    df = _leer_csv("tabla_ingresos_plame.csv")
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

    # ── Fallback hardcoded — Tabla 22 PLAME completa ─────────────────────────
    def _s(v): return v == "S"
    _D = [
        # code   desc                                                              tipo         afp    quinta  ess
        ("0101","ALIMENTACION PRINCIPAL EN DINERO",                               "INGRESO",   "S","S","S"),
        ("0102","ALIMENTACION PRINCIPAL EN ESPECIE",                              "INGRESO",   "S","S","S"),
        ("0103","COMISIONES O DESTAJO",                                           "INGRESO",   "S","S","S"),
        ("0104","COMISIONES EVENTUALES A TRABAJADORES",                           "INGRESO",   "S","S","S"),
        ("0105","TRABAJO EN SOBRETIEMPO (HORAS EXTRAS) 25%",                      "INGRESO",   "S","S","S"),
        ("0106","TRABAJO EN SOBRETIEMPO (HORAS EXTRAS) 35%",                      "INGRESO",   "S","S","S"),
        ("0107","TRABAJO EN DIA FERIADO O DIA DE DESCANSO",                       "INGRESO",   "S","S","S"),
        ("0108","INCREMENTO EN SNP 3.3%",                                         "INGRESO",   "S","S","S"),
        ("0109","INCREMENTO POR AFILIACION A AFP 10.23%",                         "INGRESO",   "S","S","S"),
        ("0110","INCREMENTO POR AFILIACION A AFP 3.00%",                          "INGRESO",   "S","N","S"),
        ("0111","PREMIOS POR VENTAS",                                             "INGRESO",   "S","S","S"),
        ("0112","PRESTACIONES ALIMENTARIAS - SUMINISTROS DIRECTOS",               "INGRESO",   "S","S","S"),
        ("0113","PRESTACIONES ALIMENTARIAS - SUMINISTROS INDIRECTOS",             "INGRESO",   "N","S","N"),
        ("0114","VACACIONES TRUNCAS",                                             "INGRESO",   "S","S","S"),
        ("0115","REMUNERACION DIA DE DESCANSO Y FERIADOS",                        "INGRESO",   "S","S","S"),
        ("0116","REMUNERACION EN ESPECIE",                                        "INGRESO",   "S","S","S"),
        ("0117","COMPENSACION VACACIONAL",                                        "INGRESO",   "S","S","S"),
        ("0118","REMUNERACION VACACIONAL",                                        "INGRESO",   "S","S","S"),
        ("0119","REMUNERACIONES DEVENGADAS",                                      "INGRESO",   "S","S","S"),
        ("0120","SUBVENCION ECONOMICA MENSUAL (PRACTICANTE SENATI)",               "INGRESO",   "S","N","S"),
        ("0121","REMUNERACION O JORNAL BASICO",                                   "INGRESO",   "S","S","S"),
        ("0122","REMUNERACION PERMANENTE",                                        "INGRESO",   "S","S","S"),
        ("0123","REMUNERACION DE LOS SOCIOS DE COOPERATIVAS",                     "INGRESO",   "S","S","S"),
        ("0124","REMUNERACION POR LA HORA DE PERMISO POR LACTANCIA",              "INGRESO",   "S","N","S"),
        ("0125","REMUNERACION INTEGRAL ANUAL - CUOTA",                            "INGRESO",   "S","S","S"),
        ("0126","INGRESOS DEL CONDUCTOR DE LA MICROEMPRESA AFILIADO AL SIS",      "INGRESO",   "S","N","N"),
        ("0127","INGRESOS DEL CONDUCTOR DE LA MICROEMPRESA - SEGURO REGULAR",     "INGRESO",   "S","N","S"),
        ("0128","REMUNERACION QUE EXCEDE EL VALOR DE MERCADO (DIVIDENDOS)",       "INGRESO",   "S","N","S"),
        ("0129","ESTIPENDIO MENSUAL INTERNO CIENCIAS DE LA SALUD",                "INGRESO",   "N","N","S"),
        ("0201","ASIGNACION FAMILIAR",                                            "INGRESO",   "S","S","S"),
        ("0202","ASIGNACION O BONIFICACION POR EDUCACION",                        "INGRESO",   "N","S","N"),
        ("0203","ASIGNACION POR CUMPLEANOS",                                      "INGRESO",   "N","S","N"),
        ("0204","ASIGNACION POR MATRIMONIO",                                      "INGRESO",   "N","S","N"),
        ("0205","ASIGNACION POR NACIMIENTO DE HIJOS",                             "INGRESO",   "N","S","N"),
        ("0206","ASIGNACION POR FALLECIMIENTO DE FAMILIARES",                     "INGRESO",   "N","S","N"),
        ("0207","ASIGNACION POR OTROS MOTIVOS PERSONALES",                        "INGRESO",   "S","S","S"),
        ("0208","ASIGNACION POR FESTIVIDAD",                                      "INGRESO",   "N","S","N"),
        ("0209","ASIGNACION PROVISIONAL DEMANDA TRABAJADOR DESPEDIDO",            "INGRESO",   "N","N","N"),
        ("0210","ASIGNACION VACACIONAL",                                          "INGRESO",   "S","S","S"),
        ("0211","ASIGNACION POR ESCOLARIDAD 30 JORNALES BASICOS/ANO",             "INGRESO",   "N","S","N"),
        ("0212","ASIGNACIONES OTORGADAS POR UNICA VEZ POR CONTINGENCIAS",         "INGRESO",   "N","S","N"),
        ("0213","ASIGNACIONES OTORGADAS REGULARMENTE",                            "INGRESO",   "S","S","S"),
        ("0214","ASIGNACION POR FALLECIMIENTO 1 UIT",                             "INGRESO",   "N","N","N"),
        ("0301","BONIFICACION POR 25 Y 30 ANOS DE SERVICIOS",                     "INGRESO",   "S","S","S"),
        ("0302","BONIFICACION POR CIERRE DE PLIEGO",                              "INGRESO",   "N","S","N"),
        ("0303","BONIFICACION POR PRODUCCION, ALTURA, TURNO, ETC.",               "INGRESO",   "S","S","S"),
        ("0304","BONIFICACION POR RIESGO DE CAJA",                                "INGRESO",   "S","S","S"),
        ("0305","BONIFICACIONES POR TIEMPO DE SERVICIOS",                         "INGRESO",   "S","S","S"),
        ("0306","BONIFICACIONES REGULARES",                                       "INGRESO",   "S","S","S"),
        ("0307","BONIFICACIONES CAFAE",                                           "INGRESO",   "N","N","N"),
        ("0308","COMPENSACION POR TRABAJOS EN DIAS DE DESCANSO Y FERIADOS",       "INGRESO",   "S","S","S"),
        ("0309","BONIFICACION POR TURNO NOCTURNO 20% JORNAL BASICO",              "INGRESO",   "S","S","S"),
        ("0310","BONIFICACION CONTACTO DIRECTO CON AGUA 20% JORNAL BASICO",       "INGRESO",   "S","S","S"),
        ("0311","BONIFICACION UNIFICADA DE CONSTRUCCION",                         "INGRESO",   "S","S","S"),
        ("0312","BONIFICACION EXTRAORDINARIA TEMPORAL - LEY 29351 Y 30334",       "INGRESO",   "N","S","N"),
        ("0313","BONIFICACION EXTRAORDINARIA PROPORCIONAL - LEY 29351 Y 30334",   "INGRESO",   "N","S","N"),
        ("0314","BONIFICACION ESPECIAL POR TRABAJO AGRARIO LEY 31110",            "INGRESO",   "N","S","N"),
        ("0401","GRATIFICACIONES DE FIESTAS PATRIAS Y NAVIDAD",                   "INGRESO",   "S","S","S"),
        ("0402","OTRAS GRATIFICACIONES ORDINARIAS",                               "INGRESO",   "S","S","S"),
        ("0403","GRATIFICACIONES EXTRAORDINARIAS",                                "INGRESO",   "N","S","N"),
        ("0404","AGUINALDOS DE JULIO Y DICIEMBRE",                                "INGRESO",   "S","S","S"),
        ("0405","GRATIFICACIONES PROPORCIONAL",                                   "INGRESO",   "S","S","S"),
        ("0406","GRATIFICACIONES FIESTAS PATRIAS Y NAVIDAD - LEY 29351 Y 30334",  "INGRESO",   "N","S","N"),
        ("0407","GRATIFICACIONES PROPORCIONAL - LEY 29351 Y 30334",               "INGRESO",   "N","S","N"),
        ("0408","GRATIF FIESTAS PATRIAS NAVIDAD TRAB PESQ LEY 30334",             "INGRESO",   "N","S","N"),
        ("0409","GRATIFICACIONES PROPORCIONAL/TRUNCA TRAB PESQUEROS LEY 30334",   "INGRESO",   "N","S","N"),
        ("0410","GRATIF FORMA PARTE REMUNER EXCEDE VALOR DE MERCADO (DIVIDENDO)", "INGRESO",   "N","N","N"),
        ("0411","GRATIF PAGADAS INTERNOS SALUD DU 090-2020 NO GRAVADOS ESSALUD",  "INGRESO",   "N","N","N"),
        ("0501","INDEMNIZACION POR DESPIDO INJUSTIFICADO U HOSTILIDAD",           "INGRESO",   "N","N","N"),
        ("0502","INDEMNIZACION POR MUERTE O INCAPACIDAD",                         "INGRESO",   "N","N","N"),
        ("0503","INDEMNIZACION POR RESOLUCION DE CONTRATO SUJETO A MODALIDAD",    "INGRESO",   "N","N","N"),
        ("0504","INDEMNIZACION POR VACACIONES NO GOZADAS",                        "INGRESO",   "N","N","N"),
        ("0505","INDEMNIZACION POR RETENCION INDEBIDA DE CTS ART. 52",            "INGRESO",   "N","N","N"),
        ("0506","INDEMNIZACION POR NO REINCORPORAR TRABAJADOR CESADO",            "INGRESO",   "N","N","N"),
        ("0507","INDEMNIZACION POR HORAS EXTRAS IMPUESTAS POR EMPLEADOR",         "INGRESO",   "N","N","N"),
        ("0700","DESCUENTOS AL TRABAJADOR",                                       "DESCUENTO", "N","N","N"),
        ("0701","ADELANTO SUELDO",                                                "DESCUENTO", "N","N","N"),
        ("0702","CUOTA SINDICAL",                                                 "DESCUENTO", "N","N","N"),
        ("0703","DESCUENTO AUTORIZADO U ORDENADO POR MANDATO JUDICIAL",           "DESCUENTO", "N","N","N"),
        ("0704","TARDANZAS",                                                      "DESCUENTO", "S","S","S"),
        ("0705","INASISTENCIAS",                                                  "DESCUENTO", "S","S","S"),
        ("0706","OTROS DESCUENTOS NO DEDUCIBLES DE LA BASE IMPONIBLE",            "DESCUENTO", "N","N","N"),
        ("0707","OTROS DESCUENTOS DEDUCIBLES DE LA BASE IMPONIBLE",               "DESCUENTO", "S","S","S"),
        ("0901","BIENES DE LA EMPRESA OTORGADOS PARA CONSUMO DEL TRABAJADOR",     "INGRESO",   "N","S","N"),
        ("0902","BONO DE PRODUCTIVIDAD",                                          "INGRESO",   "N","S","N"),
        ("0903","CANASTA DE NAVIDAD O SIMILARES",                                 "INGRESO",   "N","S","N"),
        ("0904","COMPENSACION POR TIEMPO DE SERVICIOS",                           "INGRESO",   "N","N","N"),
        ("0905","GASTOS DE REPRESENTACION - LIBRE DISPONIBILIDAD",                "INGRESO",   "S","S","S"),
        ("0906","INCENTIVO POR CESE DEL TRABAJADOR",                              "INGRESO",   "N","N","N"),
        ("0907","LICENCIA CON GOCE DE HABER",                                     "INGRESO",   "S","S","S"),
        ("0908","MOVILIDAD DE LIBRE DISPOSICION",                                 "INGRESO",   "S","S","S"),
        ("0909","MOVILIDAD SUPEDITADA A ASISTENCIA Y QUE CUBRE SOLO EL TRASLADO", "INGRESO",   "N","S","N"),
        ("0910","PARTICIPACION EN UTILIDADES - PAGADAS ANTES DE DECLARACION IR",  "INGRESO",   "N","S","N"),
        ("0911","PARTICIPACION EN UTILIDADES - PAGADAS DESPUES DE DECLARACION IR","INGRESO",   "N","S","N"),
        ("0912","PENSIONES DE JUBILACION O CESANTIA, MONTEPIO O INVALIDEZ",       "INGRESO",   "N","N","N"),
        ("0913","RECARGO AL CONSUMO",                                             "INGRESO",   "N","S","N"),
        ("0914","REFRIGERIO QUE NO ES ALIMENTACION PRINCIPAL",                    "INGRESO",   "N","S","N"),
        ("0915","SUBSIDIOS POR MATERNIDAD",                                       "INGRESO",   "S","N","N"),
        ("0916","SUBSIDIOS DE INCAPACIDAD POR ENFERMEDAD",                        "INGRESO",   "S","N","N"),
        ("0917","CONDICIONES DE TRABAJO",                                         "INGRESO",   "N","N","N"),
        ("0918","IMPUESTO A LA RENTA DE QUINTA CATEGORIA ASUMIDO",                "INGRESO",   "S","N","S"),
        ("0919","SISTEMA NACIONAL DE PENSIONES ASUMIDO",                          "INGRESO",   "S","S","S"),
        ("0920","SISTEMA PRIVADO DE PENSIONES ASUMIDO",                           "INGRESO",   "S","S","S"),
        ("0921","PENSIONES DE JUBILACION PENDIENTES POR LIQUIDAR",                "INGRESO",   "N","N","N"),
        ("0922","SUMAS O BIENES QUE NO SON DE LIBRE DISPOSICION",                 "INGRESO",   "N","N","N"),
        ("0923","INGRESOS DE CUARTA CATEGORIA CONSIDERADOS DE QUINTA CATEGORIA",  "INGRESO",   "N","S","N"),
        ("0924","INGRESOS CUARTA-QUINTA SIN RELACION DE DEPENDENCIA",             "INGRESO",   "S","S","S"),
        ("0925","INGRESO DEL PESCADOR ARTESANAL INDEPENDIENTE - BASE ESSALUD",    "INGRESO",   "N","N","S"),
        ("0926","TRANSFERENCIA DIRECTA AL EXPESCADOR - LEY 30003",                "INGRESO",   "N","N","N"),
        ("0927","BONIFICACION PRIMA TEXTIL",                                      "INGRESO",   "S","S","S"),
        ("0928","DEVOLUCION RETENCION EXCESO IMP. RENTA 5TA CAT.",                "INGRESO",   "N","N","N"),
        ("0929","OTRAS ASIGNACIONES QUE EXCEDEN VALOR DE MERCADO (DIVIDENDOS)",   "INGRESO",   "N","N","N"),
        ("0930","REMUNERACION QUE EXCEDE VALOR DE MERCADO DE PERIODOS ANTERIORES","INGRESO",   "N","N","N"),
        ("0931","PARTICIPACION PESCA CAPTURADA",                                  "INGRESO",   "S","S","S"),
        ("0932","REMUNERACION TRAB PESQUEROS GRAVADA CON REP ARM Y REP TRAB",     "INGRESO",   "S","S","S"),
    ]
    return {
        cod: {"desc": desc, "tipo": tipo, "afp": _s(a), "quinta": _s(q), "essalud": _s(e)}
        for cod, desc, tipo, a, q, e in _D
    }


def _cargar_t21() -> dict:
    """Tabla 21 PLAME — Tipos de suspensión / inasistencia."""
    df = _leer_csv("suspensiones_plame.csv")
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
