"""
Generador de interfaces oficiales SUNAT/AFPnet.

  generar_archivos_plame()  → ZIP con .REM, .JOR, .SNL
  generar_excel_afpnet()    → XLSX con 18 columnas estrictas AFPnet
"""
import io
import zipfile
from datetime import date

import pandas as pd


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tipo_doc_sunat(tipo_doc_str: str) -> str:
    """Convierte el texto del tipo doc al código SUNAT (01/04/07)."""
    t = str(tipo_doc_str).upper()
    if t in ("DNI", "01"): return "01"
    if t in ("CE", "04"):  return "04"
    if t in ("PTP", "07", "PASAPORTE"): return "07"
    return "01"


def _tipo_doc_afpnet(tipo_doc_str: str) -> str:
    """AFPnet usa 0=DNI, 1=CE."""
    t = str(tipo_doc_str).upper()
    return "1" if t in ("CE", "04") else "0"


def _mes_str(mes: int) -> str:
    return str(mes).zfill(2)


# ── PLAME ─────────────────────────────────────────────────────────────────────

def generar_archivos_plame(
    empresa_ruc: str,
    anio: int,
    mes: int,
    df_planilla: pd.DataFrame,
    auditoria_data: dict,
    df_trabajadores: pd.DataFrame,
    df_conceptos: pd.DataFrame,
) -> io.BytesIO:
    """
    Genera los 3 archivos de interfaz PLAME (T-REGISTRO):
      .REM  — Remuneraciones por concepto SUNAT
      .JOR  — Jornada laboral (horas ordinarias y extras)
      .SNL  — Suspensiones / inasistencias

    Retorna un io.BytesIO con los 3 archivos en un ZIP cuyo nombre sigue
    el formato oficial: 0601YYYYMMRRRRRRRRRRR.zip
    """
    # Validar que cada concepto pagado tenga código SUNAT
    cols_concep = [c for c in df_planilla.columns
                   if c not in ("N°", "DNI", "Apellidos y Nombres", "Sist. Pensión",
                                "Seg. Social", "TOTAL BRUTO", "NETO A PAGAR",
                                "Dsctos/Faltas", "Aporte Seg. Social", "EsSalud Patronal",
                                "ONP (13%)", "AFP Aporte", "AFP Seguro", "AFP Comis.",
                                "Ret. 5ta Cat.", "Sueldo Base", "Asig. Fam.", "Otros Ingresos")]
    conceptos_sin_codigo = []
    if not df_conceptos.empty and "Nombre del Concepto" in df_conceptos.columns:
        for _, cc in df_conceptos.iterrows():
            nombre = cc["Nombre del Concepto"]
            codigo = str(cc.get("Cód. SUNAT", "") or "").strip()
            if nombre in cols_concep and not codigo:
                if df_planilla[nombre].sum() > 0:
                    conceptos_sin_codigo.append(nombre)
    if conceptos_sin_codigo:
        raise ValueError(
            f"Los siguientes conceptos no tienen código SUNAT oficial y no pueden "
            f"exportarse al PLAME: {', '.join(conceptos_sin_codigo)}. "
            f"Asígnelos en el Maestro de Conceptos."
        )

    # Mapa concepto → código SUNAT
    cod_map: dict = {}
    if not df_conceptos.empty:
        for _, cc in df_conceptos.iterrows():
            cod = str(cc.get("Cód. SUNAT", "") or "").strip()
            if cod:
                cod_map[cc["Nombre del Concepto"]] = cod

    # Conceptos de sistema con códigos fijos (Tabla 22 SUNAT oficial)
    cod_map.update({
        "Asignación Familiar": "0201",
        "Gratificación":       "0406",
        "Bono Ext. 9%":        "0312",
        "Horas Extras 25%":    "0105",
        "Horas Extras 35%":    "0106",
        # Alias legacy (por si existen en auditoria antigua)
        "Horas Extras":        "0105",
    })

    # Mapa doc → trabajador
    trab_map: dict = {}
    if not df_trabajadores.empty and "Num. Doc." in df_trabajadores.columns:
        for _, tr in df_trabajadores.iterrows():
            trab_map[str(tr["Num. Doc."])] = tr

    df_data = df_planilla[df_planilla["Apellidos y Nombres"] != "TOTALES"]

    lines_rem: list[str] = []
    lines_jor: list[str] = []
    lines_snl: list[str] = []

    for _, row in df_data.iterrows():
        dni      = str(row["DNI"])
        trab     = trab_map.get(dni, {})
        tipo_doc = _tipo_doc_sunat(trab.get("Tipo Doc.", "DNI") if isinstance(trab, dict) else trab.get("Tipo Doc.", "DNI"))
        aud      = auditoria_data.get(dni, {})

        # ── .REM — líneas por cada concepto devengado (Ingresos y Descuentos) ──
        # 1. Procesar Ingresos
        for concepto, monto in aud.get("ingresos", {}).items():
            if monto and float(monto) > 0:
                # Interceptar nombre dinámico del Sueldo Base ("Sueldo Base (N días)")
                if concepto.startswith("Sueldo Base"):
                    cod_sunat = "0121"
                else:
                    cod_sunat = cod_map.get(concepto, "0903")  # fallback "Otros Ingresos"
                lines_rem.append(
                    f"{tipo_doc}|{dni}|{cod_sunat}|{float(monto):.2f}|{float(monto):.2f}|"
                )

        # 2. Procesar Descuentos aplicables al PLAME (Tardanzas → 0704)
        for concepto, monto in aud.get("descuentos", {}).items():
            if monto and float(monto) > 0:
                if concepto == "Tardanzas":
                    cod_sunat = "0704"
                    lines_rem.append(
                        f"{tipo_doc}|{dni}|{cod_sunat}|{float(monto):.2f}|{float(monto):.2f}|"
                    )

        # ── .JOR — jornada ─────────────────────────────────────────────────
        horas_ord  = int(aud.get("horas_ordinarias", 0))
        min_ord    = 0
        # Horas extras: suma desde ingresos (si existe)
        horas_ext  = 0
        min_ext    = 0
        if "Horas Extras" in aud.get("ingresos", {}):
            # Solo registramos horas físicas; el monto ya está en .REM
            horas_ext = 0
        lines_jor.append(
            f"{tipo_doc}|{dni}|{horas_ord}|{min_ord}|{horas_ext}|{min_ext}|"
        )

        # ── .SNL — suspensiones ─────────────────────────────────────────────
        for cod_susp, dias in aud.get("suspensiones", {}).items():
            if int(dias) > 0:
                lines_snl.append(
                    f"{tipo_doc}|{dni}|{cod_susp}|{int(dias)}|"
                )

    # Nombre del ZIP según formato oficial PLAME
    zip_name = f"0601{anio}{_mes_str(mes)}{empresa_ruc.zfill(11)}.zip"
    base_name = f"0601{anio}{_mes_str(mes)}{empresa_ruc.zfill(11)}"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{base_name}.REM", "\n".join(lines_rem))
        zf.writestr(f"{base_name}.JOR", "\n".join(lines_jor))
        zf.writestr(f"{base_name}.SNL", "\n".join(lines_snl) if lines_snl else "")
    buffer.seek(0)
    return buffer


# ── AFPnet ────────────────────────────────────────────────────────────────────

def generar_excel_afpnet(
    anio: int,
    mes: int,
    df_planilla: pd.DataFrame,
    auditoria_data: dict,
    df_trabajadores: pd.DataFrame,
) -> io.BytesIO:
    """
    Genera el archivo Excel con las 18 columnas estrictas del formato AFPnet.
    Solo incluye trabajadores con sistema AFP (excluye ONP y NO AFECTO).
    """
    if df_trabajadores.empty:
        raise ValueError("No hay datos de trabajadores para generar el archivo AFPnet.")

    # Mapa doc → trabajador
    trab_map: dict = {}
    for _, tr in df_trabajadores.iterrows():
        trab_map[str(tr.get("Num. Doc.", ""))] = tr

    df_data = df_planilla[df_planilla["Apellidos y Nombres"] != "TOTALES"]

    rows: list[dict] = []
    seq = 1
    for _, row in df_data.iterrows():
        sistema = str(row.get("Sist. Pensión", "")).upper()
        if "AFP" not in sistema:
            continue  # Ignorar ONP y NO AFECTO

        dni  = str(row["DNI"])
        trab = trab_map.get(dni, pd.Series(dtype=object))
        aud  = auditoria_data.get(dni, {})

        # Apellidos y nombres separados
        ap_pat  = str(trab.get("Apellido Paterno", trab.get("apellido_paterno", "")) or "").upper().strip()
        ap_mat  = str(trab.get("Apellido Materno", trab.get("apellido_materno", "")) or "").upper().strip()
        nombres = str(trab.get("Nombres y Apellidos", trab.get("nombres", "")) or "").upper().strip()

        # Si los apellidos están vacíos, intentamos parsear el nombre completo
        if not ap_pat and nombres:
            partes = nombres.split()
            if len(partes) >= 2:
                ap_pat  = partes[0]
                ap_mat  = partes[1] if len(partes) > 2 else ""
                nombres = " ".join(partes[2:]) if len(partes) > 2 else partes[-1]

        cuspp = str(trab.get("CUSPP", "") or "").strip().ljust(12)[:12]
        if not cuspp.strip():
            raise ValueError(
                f"El trabajador DNI {dni} ({nombres}) tiene AFP pero no tiene CUSPP registrado. "
                f"Actualice el dato en el Maestro de Personal."
            )

        tipo_doc_afpnet = _tipo_doc_afpnet(str(trab.get("Tipo Doc.", "DNI") or "DNI"))

        # Fecha de ingreso
        fi = trab.get("Fecha Ingreso", None)
        if hasattr(fi, 'strftime'):
            fecha_inicio_str = fi.strftime("%d/%m/%Y")
        elif fi:
            fecha_inicio_str = str(fi)[:10]
        else:
            fecha_inicio_str = ""

        # Inicio_Lab (S si ingresó en este mes)
        inicio_lab = "S"
        try:
            fi_date = pd.to_datetime(fi)
            inicio_lab = "S" if (fi_date.year == anio and fi_date.month == mes) else "N"
        except Exception:
            inicio_lab = "N"

        base_afp = float(aud.get("base_afp", 0.0))

        rows.append({
            "Secuencia":              seq,
            "CUSPP":                  cuspp,
            "Tipo Documento":         tipo_doc_afpnet,
            "Numero Documento":       dni,
            "Apellido Paterno":       ap_pat,
            "Apellido Materno":       ap_mat,
            "Nombres":                nombres,
            "Relacion Laboral":       "S",
            "Inicio Laboral (S/N)":   inicio_lab,
            "Fecha Inicio":           fecha_inicio_str,
            "Cese (S/N)":             "N",
            "Fecha Cese":             "",
            "Excepcion":              "N",
            "Remuneracion Asegurable": round(base_afp, 2),
            "Aporte Vol Emp":         "0.00",
            "Aporte Vol Trab Fin":    "0.00",
            "Aporte Vol Trab Sin Fin":"0.00",
            "Tipo Trabajo":           "N",
        })
        seq += 1

    if not rows:
        raise ValueError("No hay trabajadores con AFP activo en esta planilla.")

    df_out = pd.DataFrame(rows)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_out.to_excel(writer, index=False, sheet_name="AFPnet")
        ws = writer.sheets["AFPnet"]
        # Ajustar anchos
        for col in ws.columns:
            max_len = max((len(str(c.value or "")) for c in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 30)
    buffer.seek(0)
    return buffer
