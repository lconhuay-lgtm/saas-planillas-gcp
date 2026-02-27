import json
import streamlit as st
import pandas as pd
import io
from datetime import datetime

# Librerías para Excel Corporativo
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

# Librerías para PDF Corporativo
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, portrait, letter, legal
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

# Base de Datos Neon
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Trabajador, Concepto, ParametroLegal, VariablesMes, PlanillaMensual


# ─── HELPERS DE BASE DE DATOS ───────────────────────────────────────────────

def _cargar_parametros(db, empresa_id, periodo_key) -> dict | None:
    """Lee los ParametroLegal de Neon y los devuelve como dict con claves compatibles."""
    p_db = db.query(ParametroLegal).filter_by(
        empresa_id=empresa_id, periodo_key=periodo_key
    ).first()
    if not p_db:
        return None
    return {
        'rmv': p_db.rmv, 'uit': p_db.uit,
        'tasa_onp': p_db.tasa_onp, 'tasa_essalud': p_db.tasa_essalud,
        'tasa_eps': p_db.tasa_eps, 'tope_afp': p_db.tope_afp,
        'afp_habitat_aporte': p_db.h_ap, 'afp_habitat_prima': p_db.h_pr,
        'afp_habitat_flujo': p_db.h_fl, 'afp_habitat_mixta': p_db.h_mx,
        'afp_integra_aporte': p_db.i_ap, 'afp_integra_prima': p_db.i_pr,
        'afp_integra_flujo': p_db.i_fl, 'afp_integra_mixta': p_db.i_mx,
        'afp_prima_aporte': p_db.p_ap, 'afp_prima_prima': p_db.p_pr,
        'afp_prima_flujo': p_db.p_fl, 'afp_prima_mixta': p_db.p_mx,
        'afp_profuturo_aporte': p_db.pr_ap, 'afp_profuturo_prima': p_db.pr_pr,
        'afp_profuturo_flujo': p_db.pr_fl, 'afp_profuturo_mixta': p_db.pr_mx,
    }


def _cargar_trabajadores_df(db, empresa_id) -> pd.DataFrame:
    """Lee trabajadores activos de Neon y los devuelve como DataFrame compatible."""
    trabajadores = (
        db.query(Trabajador)
        .filter_by(empresa_id=empresa_id, situacion="ACTIVO")
        .all()
    )
    rows = []
    for t in trabajadores:
        rows.append({
            "Num. Doc.": t.num_doc,
            "Nombres y Apellidos": t.nombres,
            "Fecha Ingreso": t.fecha_ingreso,
            "Sueldo Base": t.sueldo_base,
            "Sistema Pensión": t.sistema_pension or "NO AFECTO",
            "Comisión AFP": t.comision_afp or "FLUJO",
            "Asig. Fam.": "Sí" if t.asig_fam else "No",
            "EPS": "Sí" if t.eps else "No",
            "CUSPP": t.cuspp or "",
            "Cargo": t.cargo or "",
            "Seguro Social": getattr(t, 'seguro_social', None) or "ESSALUD",
        })
    return pd.DataFrame(rows)


def _cargar_variables_df(db, empresa_id, periodo_key, conceptos) -> pd.DataFrame:
    """Lee VariablesMes de Neon y los devuelve como DataFrame compatible."""
    variables = (
        db.query(VariablesMes)
        .filter_by(empresa_id=empresa_id, periodo_key=periodo_key)
        .all()
    )
    concepto_nombres = [c.nombre for c in conceptos]
    rows = []
    for v in variables:
        row = {
            "Num. Doc.": v.trabajador.num_doc,
            "Nombres y Apellidos": v.trabajador.nombres,
            "Días Faltados": v.dias_faltados or 0,
            "Min. Tardanza": v.min_tardanza or 0,
            "Hrs Extras 25%": v.hrs_extras_25 or 0.0,
            "Hrs Extras 35%": v.hrs_extras_35 or 0.0,
        }
        conceptos_data = json.loads(v.conceptos_json or '{}')
        for nombre in concepto_nombres:
            row[nombre] = conceptos_data.get(nombre, 0.0)
        rows.append(row)
    return pd.DataFrame(rows).fillna(0.0)


def _cargar_conceptos_df(db, empresa_id) -> pd.DataFrame:
    """Lee conceptos de la empresa de Neon como DataFrame compatible con el motor."""
    conceptos = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
    rows = []
    for c in conceptos:
        rows.append({
            "Empresa_ID": empresa_id,
            "Nombre del Concepto": c.nombre,
            "Tipo": c.tipo,
            "Afecto AFP/ONP": c.afecto_afp,
            "Afecto 5ta Cat.": c.afecto_5ta,
            "Afecto EsSalud": c.afecto_essalud,
            "Computable CTS": c.computable_cts,
            "Computable Grati": c.computable_grati,
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _guardar_planilla(db, empresa_id, periodo_key, df_resultados, auditoria_data):
    """Guarda (upsert) el resultado de planilla en la tabla PlanillaMensual de Neon."""
    resultado_json = df_resultados.to_json(orient='records', date_format='iso')
    auditoria_json = json.dumps(auditoria_data, default=str)

    existente = db.query(PlanillaMensual).filter_by(
        empresa_id=empresa_id, periodo_key=periodo_key
    ).first()
    if existente:
        existente.resultado_json = resultado_json
        existente.auditoria_json = auditoria_json
        existente.fecha_calculo = datetime.now()
    else:
        nueva = PlanillaMensual(
            empresa_id=empresa_id,
            periodo_key=periodo_key,
            resultado_json=resultado_json,
            auditoria_json=auditoria_json,
        )
        db.add(nueva)
    db.commit()


def _cargar_planilla_guardada(db, empresa_id, periodo_key):
    """Recupera una planilla previamente guardada de Neon. Retorna (df, auditoria) o (None, None)."""
    p = db.query(PlanillaMensual).filter_by(
        empresa_id=empresa_id, periodo_key=periodo_key
    ).first()
    if not p:
        return None, None
    df = pd.read_json(io.StringIO(p.resultado_json), orient='records')
    auditoria = json.loads(p.auditoria_json)
    return df, auditoria

MESES = ["01 - Enero", "02 - Febrero", "03 - Marzo", "04 - Abril", "05 - Mayo", "06 - Junio", 
         "07 - Julio", "08 - Agosto", "09 - Septiembre", "10 - Octubre", "11 - Noviembre", "12 - Diciembre"]

# --- 1. GENERADORES DE EXPORTACIÓN ---

_MESES_ES_CALC = {
    "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
    "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
    "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre"
}

def _periodo_legible_calc(periodo_key: str) -> str:
    """'02-2026' → 'Febrero - 2026'"""
    partes = periodo_key.split("-")
    if len(partes) == 2:
        return f"{_MESES_ES_CALC.get(partes[0], partes[0])} - {partes[1]}"
    return periodo_key

# Columnas internas que NO deben aparecer en los reportes (aliases/duplicados)
_COLS_OCULTAS_SABANA = {"EsSalud Patronal"}


def generar_excel_sabana(df, empresa_nombre, periodo, empresa_ruc=""):
    """Genera un archivo Excel nativo (.xlsx) profesional con colores corporativos"""
    periodo_texto = _periodo_legible_calc(periodo)
    # Excluir columna duplicada
    cols_mostrar = [c for c in df.columns if c not in _COLS_OCULTAS_SABANA]
    df_export = df[cols_mostrar]

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_export.to_excel(writer, sheet_name=f'Planilla_{periodo[:2]}', index=False, startrow=5)
        ws = writer.sheets[f'Planilla_{periodo[:2]}']

        # 1. Títulos de Cabecera
        ws['A1'] = empresa_nombre
        ws['A1'].font = Font(size=16, bold=True, color="0F2744")
        ws['A2'] = empresa_ruc and f"RUC: {empresa_ruc}" or ""
        ws['A2'].font = Font(size=10, color="64748B")
        ws['A3'] = f"PLANILLA DE REMUNERACIONES — PERIODO: {periodo_texto}"
        ws['A3'].font = Font(size=11, bold=True, color="1E4D8C")
        ws['A4'] = f"Fecha de Cálculo: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        ws['A4'].font = Font(size=10, italic=True, color="7F8C8D")
        
        # 2. Estilos Corporativos
        fill_header = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")
        font_header = Font(color="FFFFFF", bold=True)
        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        border_thin = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        fill_total = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
        
        # 3. Aplicar formato a las celdas de la tabla (datos desde fila 6)
        for row in ws.iter_rows(min_row=6, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
            for cell in row:
                cell.border = border_thin
                if cell.row == 6:  # Fila de nombres de columnas
                    cell.fill = fill_header
                    cell.font = font_header
                    cell.alignment = align_center
                elif cell.row == ws.max_row:  # Última fila (Totales)
                    cell.fill = fill_total
                    cell.font = Font(bold=True)
                    
        # 4. Auto-ajustar ancho de columnas (máximo 25 caracteres para no hacerlo gigante)
        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length: max_length = len(str(cell.value))
                except: pass
            ws.column_dimensions[column].width = min(max_length + 2, 25)
            
    buffer.seek(0)
    return buffer

def generar_pdf_sabana(df, empresa_nombre, periodo, empresa_ruc="", empresa_regimen=""):
    """Genera la sábana principal de planilla — ajustada a hoja, sin overflow."""
    periodo_texto = _periodo_legible_calc(periodo)

    # Excluir columna duplicada antes de renderizar
    cols_mostrar = [c for c in df.columns if c not in _COLS_OCULTAS_SABANA]
    df = df[cols_mostrar]

    # ── Página landscape legal (1008 × 612 pt), márgenes 12 ──
    W_PAGE = 1008 - 24   # 984 pt disponibles
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(legal),
        rightMargin=12, leftMargin=12, topMargin=15, bottomMargin=15
    )
    elements = []
    styles = getSampleStyleSheet()

    C_NAVY  = colors.HexColor("#0F2744")
    C_STEEL = colors.HexColor("#1E4D8C")
    C_GOLD  = colors.HexColor("#C9A84C")
    C_LIGHT = colors.HexColor("#F0F4F9")
    C_GRAY  = colors.HexColor("#64748B")

    st_title = ParagraphStyle('T', fontName="Helvetica-Bold", fontSize=14, textColor=C_NAVY, spaceAfter=6)
    st_sub   = ParagraphStyle('S', fontName="Helvetica",      fontSize=9,  textColor=C_GRAY, spaceAfter=1)
    st_head  = ParagraphStyle('H', fontName="Helvetica-Bold", fontSize=10, textColor=C_STEEL, spaceAfter=8, spaceBefore=4)

    fecha_calc = datetime.now().strftime("%d/%m/%Y %H:%M")
    ruc_line = f"  |  RUC: {empresa_ruc}" if empresa_ruc else ""
    reg_line = f"  |  {empresa_regimen}" if empresa_regimen else ""
    elements.append(Paragraph(empresa_nombre + ruc_line, st_title))
    elements.append(Paragraph(
        f"PLANILLA DE REMUNERACIONES  ·  PERIODO: {periodo_texto}{reg_line}", st_head
    ))
    elements.append(Paragraph(f"Fecha de cálculo: {fecha_calc}", st_sub))
    elements.append(Spacer(1, 8))

    # ── Anchos de columna proporcionales (suman W_PAGE) ──
    # Orden de columnas esperado tras excluir EsSalud Patronal:
    col_widths_map = {
        "N°": 18, "DNI": 52, "Apellidos y Nombres": 108,
        "Sist. Pensión": 58, "Seg. Social": 50,
        "Sueldo Base": 52, "Asig. Fam.": 38, "Otros Ingresos": 52,
        "TOTAL BRUTO": 52, "ONP (13%)": 44, "AFP Aporte": 44,
        "AFP Seguro": 44, "AFP Comis.": 44, "Ret. 5ta Cat.": 46,
        "Dsctos/Faltas": 46, "NETO A PAGAR": 55, "Aporte Seg. Social": 58,
    }
    col_w = [col_widths_map.get(c, 48) for c in cols_mostrar]
    # Escalar para ocupar exactamente W_PAGE
    total_w = sum(col_w)
    col_w = [w * W_PAGE / total_w for w in col_w]

    # ── Construir datos de la tabla ──
    # Cabeceras más cortas para encabezado (wrapeadas con Paragraph)
    hdr_style = ParagraphStyle('HDR', fontName="Helvetica-Bold", fontSize=6.5,
                               textColor=colors.white, alignment=1, leading=8)
    data_rows = [[Paragraph(c, hdr_style) for c in cols_mostrar]]

    for _, row in df.iterrows():
        fila = []
        for val in row:
            if isinstance(val, float): fila.append(f"{val:,.2f}")
            else:                       fila.append(str(val) if str(val) != "nan" else "")
        data_rows.append(fila)

    t = Table(data_rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),  (-1,0),  C_STEEL),
        ('TEXTCOLOR',     (0,0),  (-1,0),  colors.white),
        ('ALIGN',         (0,0),  (-1,-1), 'CENTER'),
        ('VALIGN',        (0,0),  (-1,-1), 'MIDDLE'),
        ('ALIGN',         (2,1),  (2,-1),  'LEFT'),    # Nombres a la izquierda
        ('FONTNAME',      (0,1),  (-1,-2), 'Helvetica'),
        ('FONTSIZE',      (0,1),  (-1,-2), 6.5),
        ('TOPPADDING',    (0,0),  (-1,-1), 4),
        ('BOTTOMPADDING', (0,0),  (-1,-1), 4),
        ('ROWBACKGROUNDS',(0,1),  (-1,-2), [colors.white, C_LIGHT]),
        ('BACKGROUND',    (0,-1), (-1,-1), colors.HexColor("#CBD5E1")),
        ('FONTNAME',      (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE',      (0,-1), (-1,-1), 6.5),
        ('GRID',          (0,0),  (-1,-1), 0.3, colors.HexColor("#CBD5E1")),
        ('LINEABOVE',     (0,-1), (-1,-1), 0.8, C_NAVY),
        ('LINEBELOW',     (0,0),  (-1,0),  0.8, C_GOLD),
    ]))
    elements.append(t)
    
    # --- CUADRO RESUMEN DE PREVISIONES (AFP/ONP/SEGURIDAD SOCIAL/5TA) ---
    elements.append(Spacer(1, 30))
    elements.append(Paragraph("<b>RESUMEN GENERAL DE OBLIGACIONES DEL EMPLEADOR Y RETENCIONES</b>", st_sub))
    elements.append(Spacer(1, 10))

    df_data = df.iloc[:-1]  # Sin fila de totales
    resumen_data = [["CONCEPTO", "DETALLE", "MONTO (S/)  "]]
    total_general = 0.0

    # ONP
    if 'ONP (13%)' in df_data.columns:
        onp_total = df_data['ONP (13%)'].sum()
        if onp_total > 0:
            n_onp = len(df_data[df_data['ONP (13%)'] > 0])
            resumen_data.append(["RETENCIÓN ONP (13%)", f"{n_onp} trabajador(es)", f"{onp_total:,.2f}"])
            total_general += onp_total

    # AFP por entidad
    if 'Sist. Pensión' in df_data.columns:
        for afp in df_data['Sist. Pensión'].unique():
            if "AFP" in str(afp):
                df_afp = df_data[df_data['Sist. Pensión'] == afp]
                tot = df_afp['AFP Aporte'].sum() + df_afp['AFP Seguro'].sum() + df_afp['AFP Comis.'].sum()
                if tot > 0:
                    resumen_data.append([f"RETENCIÓN {afp}", f"{len(df_afp)} trabajador(es)", f"{tot:,.2f}"])
                    total_general += tot

    # Renta 5ta Categoría
    if 'Ret. 5ta Cat.' in df_data.columns:
        quinta_total = df_data['Ret. 5ta Cat.'].sum()
        if quinta_total > 0:
            n_quinta = len(df_data[df_data['Ret. 5ta Cat.'] > 0])
            resumen_data.append(["RETENCIÓN RENTA 5TA CAT.", f"{n_quinta} trabajador(es)", f"{quinta_total:,.2f}"])
            total_general += quinta_total

    resumen_data.append(["TOTAL RETENCIONES (A DECLARAR PDT)", "", f"S/ {total_general:,.2f}"])

    # Seguridad Social (ESSALUD + SIS) — a cargo del empleador
    resumen_data.append(["", "", ""])
    aporte_seg_total = 0.0
    col_seg = 'Aporte Seg. Social' if 'Aporte Seg. Social' in df_data.columns else 'EsSalud Patronal'
    if col_seg in df_data.columns and 'Seg. Social' in df_data.columns:
        for tipo_seg in df_data['Seg. Social'].unique():
            df_seg = df_data[df_data['Seg. Social'] == tipo_seg]
            monto_seg = df_seg[col_seg].sum()
            if monto_seg > 0:
                resumen_data.append([f"APORTE {tipo_seg} (EMPLEADOR)", f"{len(df_seg)} trabajador(es)", f"{monto_seg:,.2f}"])
                aporte_seg_total += monto_seg
    elif col_seg in df_data.columns:
        aporte_seg_total = df_data[col_seg].sum()
        resumen_data.append(["APORTE ESSALUD (EMPLEADOR)", f"{len(df_data)} trabajador(es)", f"{aporte_seg_total:,.2f}"])

    if aporte_seg_total > 0:
        resumen_data.append(["TOTAL SEGURIDAD SOCIAL (A PAGAR SUNAT)", "", f"S/ {aporte_seg_total:,.2f}"])

    t_res = Table(resumen_data, colWidths=[250, 150, 150])
    estilos_res = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#34495E")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
    ]
    # Filas de subtotal en negrita con fondo
    for i, row_data in enumerate(resumen_data):
        if row_data[0].startswith("TOTAL"):
            estilos_res.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor("#E5E7E9")))
            estilos_res.append(('FONTNAME', (0, i), (-1, i), 'Helvetica-Bold'))
    t_res.setStyle(TableStyle(estilos_res))

    if len(resumen_data) > 2:
        elements.append(t_res)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generar_pdf_quinta(data_q, empresa_nombre, periodo, nombre_trabajador):
    """Genera el Certificado Corporativo de Retención de 5ta Categoría"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=portrait(letter), rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Title'], fontSize=16, textColor=colors.HexColor("#2C3E50"), spaceAfter=5)
    subtitle_style = ParagraphStyle('CustomSub', parent=styles['Normal'], fontSize=11, textColor=colors.HexColor("#7F8C8D"), alignment=TA_CENTER, spaceAfter=20)
    header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontSize=10, textColor=colors.black, spaceAfter=5)

    elements.append(Paragraph(f"<b>{empresa_nombre}</b>", title_style))
    elements.append(Paragraph(f"LIQUIDACIÓN Y DETALLE DE RETENCIÓN DE 5TA CATEGORÍA", subtitle_style))
    elements.append(Paragraph(f"<b>Trabajador:</b> {nombre_trabajador}", header_style))
    elements.append(Paragraph(f"<b>Periodo de Cálculo:</b> {periodo}", header_style))
    elements.append(Spacer(1, 15))

    datos_tabla = [
        ["CONCEPTO / PASO DE CÁLCULO (SUNAT)", "IMPORTES (S/)"],
        ["1. Remuneraciones Previas Percibidas (Ene - Mes Anterior)", f"{int(data_q['rem_previa']):,}"],
        ["2. Remuneración Computable del Mes Actual", f"{data_q['base_mes']:,.2f}"],
        [f"3. Proyección de Meses Restantes ({data_q['meses_restantes']} meses)", f"{data_q['proy_sueldo']:,.2f}"],
        ["4. Proyección de Gratificaciones + Bono Extraordinario 9%", f"{data_q['proy_grati']:,.2f}"],
        ["A. RENTA BRUTA ANUAL PROYECTADA (REDONDEADA)", f"{int(data_q['bruta_anual']):,}"],
        [f"B. Deducción de Ley (7 UIT de S/ {data_q['uit_valor']:,.2f})", f"- {int(data_q['uit_7']):,}"],
        ["C. RENTA NETA IMPONIBLE ANUAL (A - B)", f"{int(data_q['neta_anual']):,}"]
    ]

    t_calc = Table(datos_tabla, colWidths=[380, 100])
    t_calc.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1f77b4")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTNAME', (0,5), (-1,5), 'Helvetica-Bold'), 
        ('FONTNAME', (0,7), (-1,7), 'Helvetica-Bold'), 
        ('BACKGROUND', (0,7), (-1,7), colors.HexColor("#ECF0F1")),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#BDC3C7"))
    ]))
    elements.append(t_calc)
    elements.append(Spacer(1, 15))

    if data_q['neta_anual'] > 0:
        elements.append(Paragraph("<b>D. APLICACIÓN DE ESCALAS Y TRAMOS DEL IMPUESTO:</b>", header_style))
        elements.append(Spacer(1, 5))
        
        datos_tramos = [["TRAMO (UIT)", "TASA", "BASE APLICABLE", "IMPUESTO ANUAL"]]
        for tramo in data_q['detalle_tramos']:
            datos_tramos.append([tramo['rango'], tramo['tasa'], f"{int(tramo['base']):,}", f"{int(tramo['impuesto']):,}"])
        
        datos_tramos.append(["", "", "IMPUESTO ANUAL TOTAL:", f"{int(data_q['imp_anual']):,}"])
        
        t_tramos = Table(datos_tramos, colWidths=[150, 60, 130, 140])
        t_tramos.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#7F8C8D")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
            ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#BDC3C7"))
        ]))
        elements.append(t_tramos)
        elements.append(Spacer(1, 15))

        datos_final = [
            ["E. Impuesto Anual Calculado", f"{int(data_q['imp_anual']):,}"],
            ["F. Retenciones de Meses Anteriores Efectuadas", f"- {int(data_q['ret_previa']):,}"],
            [f"G. Divisor Aplicable al Mes ({data_q['divisor']})", f"÷ {data_q['divisor']}"],
            ["H. RETENCIÓN EXACTA A EFECTUAR EN EL MES (REDONDEADA)", f"S/ {int(data_q['retencion']):,}"]
        ]
        t_final = Table(datos_final, colWidths=[380, 100])
        t_final.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('ALIGN', (1,0), (1,-1), 'RIGHT'),
            ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
            ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#F9E79F")), 
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#BDC3C7"))
        ]))
        elements.append(t_final)
    else:
        elements.append(Paragraph("<i>El trabajador no supera las 7 UIT, por lo tanto, la Renta Neta es S/ 0.00 y no aplica retención en este periodo.</i>", header_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer
# --- 2. MOTOR DE RENDERIZADO Y CÁLCULO ---

def render():
    st.title("⚙️ Ejecución de Planilla Mensual")
    st.markdown("---")

    empresa_id = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')

    col_m, col_a = st.columns([2, 1])
    mes_seleccionado = col_m.selectbox("Mes de Cálculo", MESES, key="calc_mes")
    anio_seleccionado = col_a.selectbox("Año de Cálculo", [2025, 2026, 2027, 2028], index=1, key="calc_anio")
    periodo_key = f"{mes_seleccionado[:2]}-{anio_seleccionado}"
    mes_idx = MESES.index(mes_seleccionado) + 1

    # ─── LEER DATOS DESDE NEON ────────────────────────────────────────────────
    db = SessionLocal()
    try:
        # 1. Parámetros Legales
        p = _cargar_parametros(db, empresa_id, periodo_key)
        if not p:
            st.error(f"🛑 ALTO: No se han configurado los Parámetros Legales para el periodo **{periodo_key}**.")
            st.info("Vaya al módulo 'Parámetros Legales' y configure las tasas para este periodo.")
            return

        # 2. Trabajadores activos
        df_trab = _cargar_trabajadores_df(db, empresa_id)
        if df_trab.empty:
            st.warning("⚠️ No hay trabajadores activos registrados en el Maestro de Personal.")
            return

        # 3. Conceptos de la empresa
        conceptos_list = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
        conceptos_empresa = _cargar_conceptos_df(db, empresa_id)

        # 4. Variables del periodo
        df_var = _cargar_variables_df(db, empresa_id, periodo_key, conceptos_list)
        if df_var.empty:
            st.warning(f"⚠️ No se han ingresado Asistencias para **{periodo_key}**.")
            st.info("Vaya al módulo 'Ingreso de Asistencias' y guarde las variables del mes.")
            return

        # Merge principal (igual que antes)
        df_planilla = pd.merge(df_trab, df_var, on="Num. Doc.", how="inner")

        # Compatibilidad con emision_boletas.py (lee de session_state)
        st.session_state['trabajadores_mock'] = df_trab
        if 'variables_por_periodo' not in st.session_state:
            st.session_state['variables_por_periodo'] = {}
        st.session_state['variables_por_periodo'][periodo_key] = df_var

    finally:
        db.close()

    if st.button(f"🚀 Ejecutar Motor de Planilla - {periodo_key}", type="primary", use_container_width=True):
        st.session_state['ultima_planilla_calculada'] = True 
        resultados = []
        auditoria_data = {} 

        for index, row in df_planilla.iterrows():
            dni_trabajador = row['Num. Doc.']
            nombres = row['Nombres y Apellidos_x']
            sistema = str(row.get('Sistema Pensión', 'NO AFECTO')).upper()
            
            # --- TIEMPOS Y BASES FIJAS (Proporcionalidad Segura) ---
            try:
                fecha_ingreso = pd.to_datetime(row['Fecha Ingreso'])
                mes_calc = int(mes_seleccionado[:2])
                anio_calc = int(anio_seleccionado)
                
                dias_computables = 30
                if fecha_ingreso.year == anio_calc and fecha_ingreso.month == mes_calc:
                    dias_computables = max(0, min(30, 30 - fecha_ingreso.day + 1))
                elif fecha_ingreso.year > anio_calc or (fecha_ingreso.year == anio_calc and fecha_ingreso.month > mes_calc):
                    dias_computables = 0
            except Exception:
                dias_computables = 30 # Si falla la fecha, asume mes completo por seguridad
                
            sueldo_base_nominal = float(row['Sueldo Base'])
            sueldo_base_proporcional = (sueldo_base_nominal / 30) * dias_computables
            valor_dia = sueldo_base_nominal / 30
            valor_hora = valor_dia / 8

            dscto_faltas = float(row['Días Faltados']) * valor_dia
            dscto_tardanzas = float(row['Min. Tardanza']) * (valor_hora / 60)
            sueldo_computable = max(0.0, sueldo_base_proporcional - dscto_faltas - dscto_tardanzas)

            monto_asig_fam = (p['rmv'] * 0.10) if row.get('Asig. Fam.', "No") == "Sí" else 0.0
            pago_he_25 = float(row.get('Hrs Extras 25%', 0.0)) * (valor_hora * 1.25)
            pago_he_35 = float(row.get('Hrs Extras 35%', 0.0)) * (valor_hora * 1.35)

            ingresos_totales = sueldo_computable + monto_asig_fam + pago_he_25 + pago_he_35
            descuentos_manuales = dscto_faltas + dscto_tardanzas 
            base_afp_onp = ingresos_totales
            base_essalud = ingresos_totales
            base_quinta_mes = ingresos_totales
            
            desglose_ingresos = {
                f"Sueldo Base ({int(dias_computables)} días)": round(sueldo_computable, 2),
                "Asignación Familiar": round(monto_asig_fam, 2),
                "Horas Extras": round(pago_he_25 + pago_he_35, 2)
            }
            desglose_descuentos = {
                "Inasistencias/Tardanzas": round(descuentos_manuales, 2)
            }

            # --- CONCEPTOS DINÁMICOS Y GRATIFICACIONES ---
            monto_grati = float(row.get('GRATIFICACION (JUL/DIC)', 0.0))
            if monto_grati > 0:
                monto_bono_9 = monto_grati * 0.09
                desglose_ingresos['Gratificación'] = round(monto_grati, 2)
                desglose_ingresos['Bono Ext. 9%'] = round(monto_bono_9, 2)
                ingresos_totales += (monto_grati + monto_bono_9)
                base_quinta_mes += (monto_grati + monto_bono_9)

            conceptos_omitidos = ["SUELDO BASICO", "ASIGNACION FAMILIAR", "GRATIFICACION (JUL/DIC)", "BONIFICACION EXTRAORDINARIA LEY 29351 (9%)"]
            otros_ingresos = 0.0
            for _, concepto in conceptos_empresa.iterrows():
                nombre_c = concepto['Nombre del Concepto']
                if nombre_c in conceptos_omitidos: continue
                if nombre_c in row and float(row[nombre_c]) > 0:
                    monto_concepto = float(row[nombre_c])
                    if concepto['Tipo'] == "INGRESO":
                        desglose_ingresos[nombre_c] = round(monto_concepto, 2)
                        otros_ingresos += monto_concepto
                        ingresos_totales += monto_concepto
                        if concepto['Afecto AFP/ONP']: base_afp_onp += monto_concepto
                        if concepto['Afecto EsSalud']: base_essalud += monto_concepto
                        if concepto['Afecto 5ta Cat.']: base_quinta_mes += monto_concepto
                    elif concepto['Tipo'] == "DESCUENTO":
                        desglose_descuentos[nombre_c] = round(monto_concepto, 2)
                        descuentos_manuales += monto_concepto
                        if concepto['Afecto AFP/ONP']: base_afp_onp -= monto_concepto
                        if concepto['Afecto EsSalud']: base_essalud -= monto_concepto
                        if concepto['Afecto 5ta Cat.']: base_quinta_mes -= monto_concepto

            base_afp_onp = max(0.0, base_afp_onp)
            base_essalud = max(0.0, base_essalud)
            base_quinta_mes = max(0.0, base_quinta_mes)
            
            # --- CÁLCULO DE PENSIONES ---
            aporte_afp = 0.0
            prima_afp = 0.0
            comis_afp = 0.0
            dscto_onp = 0.0
            
            if sistema == "ONP":
                dscto_onp = base_afp_onp * (p['tasa_onp'] / 100)
                if dscto_onp > 0: desglose_descuentos['Aporte ONP'] = round(dscto_onp, 2)
            elif sistema != "NO AFECTO":
                prefijo = ""
                if "HABITAT" in sistema: prefijo = "afp_habitat_"
                elif "INTEGRA" in sistema: prefijo = "afp_integra_"
                elif "PRIMA" in sistema: prefijo = "afp_prima_"
                elif "PROFUTURO" in sistema: prefijo = "afp_profuturo_"

                if prefijo:
                    tasa_aporte = p[prefijo + "aporte"] / 100
                    tasa_prima = p[prefijo + "prima"] / 100
                    tasa_comision = p[prefijo + "mixta"]/100 if row['Comisión AFP'] == "MIXTA" else p[prefijo + "flujo"]/100

                    aporte_afp = base_afp_onp * tasa_aporte
                    prima_afp = min(base_afp_onp, p['tope_afp']) * tasa_prima
                    comis_afp = base_afp_onp * tasa_comision
                    total_afp_ind = aporte_afp + prima_afp + comis_afp
                    if total_afp_ind > 0: desglose_descuentos[f'Aporte {sistema}'] = round(total_afp_ind, 2)

            total_pension = dscto_onp + aporte_afp + prima_afp + comis_afp

            # --- RENTA 5TA CATEGORÍA (Redondeo Entero PLAME) ---
            uit = p['uit']
            meses_restantes = 12 - mes_idx
            rem_previa_historica = 0.0
            retencion_previa_historica = 0.0
            proyeccion_gratis = 0.0
            if mes_idx <= 6: proyeccion_gratis = base_quinta_mes * 2 * 1.09 
            elif mes_idx <= 11: proyeccion_gratis = base_quinta_mes * 1 * 1.09 
            proyeccion_sueldos_restantes = base_quinta_mes * meses_restantes
            
            renta_bruta_anual = int(round(rem_previa_historica + base_quinta_mes + proyeccion_sueldos_restantes + proyeccion_gratis))
            renta_neta_anual = int(round(renta_bruta_anual - (7 * uit)))
            
            impuesto_anual = 0.0
            retencion_quinta = 0.0
            detalle_tramos = []
            divisor = 1
            if mes_idx in [1, 2, 3]: divisor = 12
            elif mes_idx == 4: divisor = 9
            elif mes_idx in [5, 6, 7]: divisor = 8
            elif mes_idx == 8: divisor = 5
            elif mes_idx in [9, 10, 11]: divisor = 4

            if renta_neta_anual > 0:
                renta_restante = renta_neta_anual
                tramos = [(5 * uit, 0.08), (15 * uit, 0.14), (15 * uit, 0.17), (10 * uit, 0.20), (float('inf'), 0.30)]
                for limite, tasa in tramos:
                    if renta_restante > 0:
                        monto_tramo = min(renta_restante, limite)
                        imp_tramo = monto_tramo * tasa
                        impuesto_anual += imp_tramo
                        detalle_tramos.append({"rango": f"Hasta {limite/uit} UIT", "tasa": f"{int(tasa*100)}%", "base": monto_tramo, "impuesto": imp_tramo})
                        renta_restante -= monto_tramo
                retencion_quinta = int(round(max(0.0, (impuesto_anual - retencion_previa_historica) / divisor)))
                if retencion_quinta > 0: desglose_descuentos['Retención 5ta Cat.'] = float(retencion_quinta)

            # --- SEGURO SOCIAL (ESSALUD o SIS) Y NETO ---
            seguro_social = str(row.get('Seguro Social', 'ESSALUD')).upper()
            if seguro_social == "SIS":
                aporte_essalud = 15.0  # Monto fijo SIS - Solo Micro Empresa
                etiqueta_seguro = "SIS"
            elif row.get('EPS', 'No') == "Sí":
                aporte_essalud = max(base_essalud, p['rmv']) * (p['tasa_eps'] / 100)
                etiqueta_seguro = "ESSALUD-EPS"
            else:
                aporte_essalud = max(base_essalud, p['rmv']) * (p['tasa_essalud'] / 100)
                etiqueta_seguro = "ESSALUD"
            
            neto_pagar = ingresos_totales - total_pension - retencion_quinta - descuentos_manuales

            # --- FILA DE LA SÁBANA CORPORATIVA ---
            resultados.append({
                "N°": index + 1,
                "DNI": dni_trabajador,
                "Apellidos y Nombres": nombres,
                "Sist. Pensión": sistema,
                "Seg. Social": etiqueta_seguro,
                "Sueldo Base": round(sueldo_computable, 2),
                "Asig. Fam.": round(monto_asig_fam, 2),
                "Otros Ingresos": round((pago_he_25 + pago_he_35 + monto_grati + otros_ingresos), 2),
                "TOTAL BRUTO": round(ingresos_totales, 2),
                "ONP (13%)": round(dscto_onp, 2),
                "AFP Aporte": round(aporte_afp, 2),
                "AFP Seguro": round(prima_afp, 2),
                "AFP Comis.": round(comis_afp, 2),
                "Ret. 5ta Cat.": float(retencion_quinta),
                "Dsctos/Faltas": round(descuentos_manuales, 2),
                "NETO A PAGAR": round(neto_pagar, 2),
                "Aporte Seg. Social": round(aporte_essalud, 2),
                # Alias para compatibilidad con boletas (leen 'EsSalud Patronal')
                "EsSalud Patronal": round(aporte_essalud, 2),
            })

            auditoria_data[dni_trabajador] = {
                "nombres": nombres, "periodo": periodo_key, "dias": dias_computables,
                "seguro_social": etiqueta_seguro,
                "aporte_seg_social": round(aporte_essalud, 2),
                "ingresos": desglose_ingresos, "descuentos": desglose_descuentos,
                "totales": {"ingreso": ingresos_totales, "descuento": (total_pension + retencion_quinta + descuentos_manuales), "neto": neto_pagar},
                "quinta": {
                    "rem_previa": rem_previa_historica, "ret_previa": retencion_previa_historica,
                    "base_mes": base_quinta_mes, "meses_restantes": meses_restantes,
                    "proy_sueldo": proyeccion_sueldos_restantes, "proy_grati": proyeccion_gratis, 
                    "bruta_anual": renta_bruta_anual, "uit_valor": uit, "uit_7": 7 * uit, 
                    "neta_anual": renta_neta_anual, "detalle_tramos": detalle_tramos,
                    "imp_anual": impuesto_anual, "divisor": divisor, "retencion": retencion_quinta
                }
            }

        df_resultados = pd.DataFrame(resultados).fillna(0.0)
        
        # --- FILA DE TOTALES DINÁMICA ---
        cols_texto = {"N°", "DNI", "Apellidos y Nombres", "Sist. Pensión", "Seg. Social"}
        totales = {"N°": "", "DNI": "", "Apellidos y Nombres": "TOTALES", "Sist. Pensión": "", "Seg. Social": ""}
        for col in df_resultados.columns:
            if col not in cols_texto:
                totales[col] = df_resultados[col].sum()
            
        df_resultados = pd.concat([df_resultados, pd.DataFrame([totales])], ignore_index=True)
        st.session_state['res_planilla'] = df_resultados
        st.session_state['auditoria_data'] = auditoria_data

        # --- GUARDAR PLANILLA EN NEON (persistencia real) ---
        try:
            db2 = SessionLocal()
            _guardar_planilla(db2, empresa_id, periodo_key, df_resultados, auditoria_data)
            db2.close()
        except Exception as e:
            st.warning(f"Planilla calculada pero no se pudo guardar en la nube: {e}")

    # --- INTENTAR RECUPERAR PLANILLA GUARDADA EN NEON SI NO HAY EN SESSION ---
    if not st.session_state.get('ultima_planilla_calculada', False):
        try:
            db3 = SessionLocal()
            df_rec, aud_rec = _cargar_planilla_guardada(db3, empresa_id, periodo_key)
            db3.close()
            if df_rec is not None and not df_rec.empty:
                st.session_state['res_planilla'] = df_rec
                st.session_state['auditoria_data'] = aud_rec
                st.session_state['ultima_planilla_calculada'] = True
                st.info(f"📂 Planilla de **{periodo_key}** recuperada desde la nube.")
        except Exception:
            pass

    # --- RENDERIZADO VISUAL ---
    if st.session_state.get('ultima_planilla_calculada', False):
        df_resultados = st.session_state['res_planilla']
        auditoria_data = st.session_state.get('auditoria_data', {})

        st.success("✅ Planilla generada con éxito.")
        
        st.markdown("### 📊 Matriz de Nómina")
        # Mostramos la tabla en pantalla (Ocultando el DNI visualmente solo aquí si lo deseas, o dejándolo)
        st.dataframe(df_resultados.iloc[:-1], use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("#### 📥 Exportación Corporativa")
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            try:
                empresa_ruc_s = st.session_state.get('empresa_activa_ruc', '')
                empresa_reg_s = st.session_state.get('empresa_activa_regimen', '')
                excel_file = generar_excel_sabana(df_resultados, empresa_nombre, periodo_key, empresa_ruc=empresa_ruc_s)
                st.download_button("📊 Descargar Sábana (.xlsx)", data=excel_file, file_name=f"PLANILLA_{periodo_key}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            except Exception:
                csv = df_resultados.to_csv(index=False).encode('utf-8')
                st.download_button("📊 Descargar Sábana (CSV)", data=csv, file_name=f"PLANILLA_{periodo_key}.csv", mime="text/csv", use_container_width=True)
        with col_btn2:
            empresa_ruc_s = st.session_state.get('empresa_activa_ruc', '')
            empresa_reg_s = st.session_state.get('empresa_activa_regimen', '')
            pdf_buffer = generar_pdf_sabana(df_resultados, empresa_nombre, periodo_key, empresa_ruc=empresa_ruc_s, empresa_regimen=empresa_reg_s)
            st.download_button("📄 Descargar Sábana y Resumen (PDF)", data=pdf_buffer, file_name=f"SABANA_{periodo_key}.pdf", mime="application/pdf", use_container_width=True)

        st.markdown("---")
        st.markdown("### 🔍 Panel de Auditoría Tributaria y Liquidaciones")
        
        opciones_trab = [f"{dni} - {info['nombres']}" for dni, info in auditoria_data.items()]
        trabajador_sel = st.selectbox("Seleccione un trabajador para ver su detalle legal:", opciones_trab, label_visibility="collapsed")

        if trabajador_sel:
            dni_sel = trabajador_sel.split(" - ")[0]
            data = auditoria_data[dni_sel]
            q = data['quinta']

            t1, t2 = st.tabs(["💰 Boleta Mensual", "🏛️ Certificado de 5ta Categoría"])

            with t1:
                c1, c2 = st.columns(2)
                with c1:
                    for k, v in data['ingresos'].items(): st.markdown(f"- **{k}:** S/ {v:,.2f}")
                    st.success(f"**Total Ingresos: S/ {data['totales']['ingreso']:,.2f}**")
                with c2:
                    for k, v in data['descuentos'].items(): st.markdown(f"- **{k}:** S/ {v:,.2f}")
                    st.error(f"**Total Descuentos: S/ {data['totales']['descuento']:,.2f}**")

            with t2:
                if q['neta_anual'] <= 0:
                    st.success("Este trabajador **NO supera las 7 UIT** anuales. Retención: S/ 0.00.")
                else:
                    st.markdown("##### Paso a Paso - Proyección Oficial SUNAT")
                    st.markdown(f"**1. Remuneraciones Previas Históricas:** S/ {int(q['rem_previa']):,}")
                    st.markdown(f"**2. Remuneración Base del Mes:** S/ {q['base_mes']:,.2f}")
                    st.markdown(f"**3. Proyección Sueldos Restantes ({q['meses_restantes']} meses):** S/ {q['proy_sueldo']:,.2f}")
                    st.markdown(f"**4. Proyección Gratificaciones + Bono 9%:** S/ {q['proy_grati']:,.2f}")
                    st.markdown(f"**5. Renta Bruta Anual:** S/ {int(q['bruta_anual']):,}")
                    st.markdown(f"**6. Deducción de Ley (7 UIT):** - S/ {int(q['uit_7']):,}")
                    st.markdown(f"**7. Renta Neta Imponible:** S/ {int(q['neta_anual']):,}")
                    
                    st.markdown("---")
                    st.markdown("**Aplicación de Tramos (Escalas):**")
                    for t in q['detalle_tramos']:
                        st.write(f"- Tramo {t['rango']} al {t['tasa']}: **S/ {int(t['impuesto']):,}**")
                    
                    st.markdown("---")
                    st.markdown(f"**Impuesto Anual Calculado:** S/ {int(q['imp_anual']):,}")
                    st.markdown(f"**Retenciones Previas Efectuadas:** - S/ {int(q['ret_previa']):,}")
                    st.markdown(f"**Factor de División:** Entre {q['divisor']}")
                    st.error(f"**RETENCIÓN EXACTA A EFECTUAR (Entero):** S/ {int(q['retencion']):,}")

                    pdf_5ta = generar_pdf_quinta(q, empresa_nombre, periodo_key, data['nombres'])
                    st.download_button(
                        label="📄 Descargar Certificado de 5ta Categoría (PDF)",
                        data=pdf_5ta,
                        file_name=f"QUINTA_CAT_{dni_sel}_{periodo_key}.pdf",
                        mime="application/pdf",
                        type="primary"
                    )

        # ── CIERRE DE PLANILLA ────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 🔒 Cierre de Planilla")

        rol_usuario = st.session_state.get('usuario_rol', 'analista')
        nombre_usuario = st.session_state.get('usuario_nombre', '')

        estado_actual = "ABIERTA"
        planilla_db_cierre = None
        try:
            db_c = SessionLocal()
            planilla_db_cierre = db_c.query(PlanillaMensual).filter_by(
                empresa_id=empresa_id, periodo_key=periodo_key
            ).first()
            db_c.close()
            if planilla_db_cierre:
                estado_actual = getattr(planilla_db_cierre, 'estado', 'ABIERTA') or 'ABIERTA'
        except Exception:
            pass

        if estado_actual == "CERRADA":
            cerrada_por  = getattr(planilla_db_cierre, 'cerrada_por', '') or ''
            fecha_cierre = getattr(planilla_db_cierre, 'fecha_cierre', None)
            fecha_str    = fecha_cierre.strftime("%d/%m/%Y %H:%M") if fecha_cierre else ''
            st.error(f"**PLANILLA CERRADA** — Responsable: {cerrada_por}  |  Fecha: {fecha_str}")
            if rol_usuario == "supervisor":
                st.info("Como supervisor puede reabrir esta planilla para modificarla.")
                if st.button("🔓 Reabrir Planilla", use_container_width=False):
                    try:
                        db_up = SessionLocal()
                        p = db_up.query(PlanillaMensual).filter_by(
                            empresa_id=empresa_id, periodo_key=periodo_key
                        ).first()
                        p.estado = "ABIERTA"
                        p.cerrada_por = None
                        p.fecha_cierre = None
                        db_up.commit()
                        db_up.close()
                        st.success("Planilla reabierta correctamente.")
                        st.rerun()
                    except Exception as e_re:
                        st.error(f"Error al reabrir: {e_re}")
            else:
                st.warning("Solo un **Supervisor** puede reabrir esta planilla.")
        else:
            st.info("La planilla está **ABIERTA**. Puede recalcularse hasta que sea cerrada.")
            if rol_usuario == "supervisor":
                with st.expander("Cerrar Planilla"):
                    st.warning("Al cerrar la planilla quedará bloqueada para el analista.")
                    if st.button("Confirmar Cierre de Planilla", type="primary"):
                        try:
                            db_up = SessionLocal()
                            p = db_up.query(PlanillaMensual).filter_by(
                                empresa_id=empresa_id, periodo_key=periodo_key
                            ).first()
                            p.estado = "CERRADA"
                            p.cerrada_por = nombre_usuario
                            p.fecha_cierre = datetime.now()
                            db_up.commit()
                            db_up.close()
                            st.success(f"Planilla {periodo_key} cerrada por {nombre_usuario}.")
                            st.rerun()
                        except Exception as e_cl:
                            st.error(f"Error al cerrar: {e_cl}")
            else:
                st.info("Solo un **Supervisor** puede cerrar la planilla.")