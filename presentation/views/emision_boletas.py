import json
import streamlit as st
import pandas as pd
import io
import zipfile
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Trabajador, Concepto, VariablesMes, PlanillaMensual


def _recuperar_datos_desde_neon(db, empresa_id):
    """
    Intenta recuperar la planilla, trabajadores y variables de Neon.
    Retorna (df_resultados, auditoria_data, df_trab, df_var, periodo_key) o None si no hay nada.
    """
    # 1. Planillas disponibles para esta empresa (más reciente primero)
    planillas = (
        db.query(PlanillaMensual)
        .filter_by(empresa_id=empresa_id)
        .order_by(PlanillaMensual.fecha_calculo.desc())
        .all()
    )
    if not planillas:
        return None

    return planillas  # retornamos la lista para que el usuario elija el periodo


def _cargar_planilla_periodo(db, empresa_id, periodo_key):
    """Carga una planilla específica de Neon y los datos de soporte."""
    planilla = db.query(PlanillaMensual).filter_by(
        empresa_id=empresa_id, periodo_key=periodo_key
    ).first()
    if not planilla:
        return None, None, None, None

    df_res = pd.read_json(io.StringIO(planilla.resultado_json), orient='records')
    aud = json.loads(planilla.auditoria_json)

    # Trabajadores con los campos que necesita generar_pdf_boletas_masivas
    trabajadores = db.query(Trabajador).filter_by(empresa_id=empresa_id).all()
    df_trab = pd.DataFrame([{
        'Num. Doc.': t.num_doc,
        'Nombres y Apellidos': t.nombres,
        'Cargo': t.cargo or 'No especificado',
        'Fecha Ingreso': t.fecha_ingreso,
        'Sistema Pensión': t.sistema_pension or 'NO AFECTO',
        'CUSPP': t.cuspp or '',
        'Seguro Social': getattr(t, 'seguro_social', None) or 'ESSALUD',
        'correo_electronico': getattr(t, 'correo_electronico', '') or '',
    } for t in trabajadores])

    # Variables del periodo (solo necesitamos horas extras para las boletas)
    conceptos = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
    variables = db.query(VariablesMes).filter_by(
        empresa_id=empresa_id, periodo_key=periodo_key
    ).all()
    rows_var = []
    for v in variables:
        conceptos_data = json.loads(v.conceptos_json or '{}')
        row = {
            'Num. Doc.': v.trabajador.num_doc,
            'Nombres y Apellidos': v.trabajador.nombres,
            'Días Faltados': v.dias_faltados or 0,
            'Min. Tardanza': v.min_tardanza or 0,
            'Hrs Extras 25%': v.hrs_extras_25 or 0.0,
            'Hrs Extras 35%': v.hrs_extras_35 or 0.0,
        }
        row.update(conceptos_data)
        rows_var.append(row)
    df_var = pd.DataFrame(rows_var).fillna(0.0) if rows_var else pd.DataFrame()

    return df_res, aud, df_trab, df_var


# ── Mapeo de meses al español ────────────────────────────────────────────────
_MESES_ES = {
    "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
    "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
    "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre"
}

def _periodo_legible(periodo_key: str) -> str:
    """'02-2026' → 'Febrero - 2026'"""
    partes = periodo_key.split("-")
    if len(partes) == 2:
        return f"{_MESES_ES.get(partes[0], partes[0])} - {partes[1]}"
    return periodo_key


def generar_pdf_boletas_masivas(empresa_info, periodo, df_resultados, df_trabajadores, df_variables, auditoria_data):
    """
    Genera un PDF con boletas a página completa — Diseño corporativo elegante.
    empresa_info: dict con claves: nombre, ruc, domicilio, representante
    """
    # ── Paleta corporativa ────────────────────────────────────────────────────
    C_NAVY   = colors.HexColor("#0F2744")   # azul marino oscuro — cabeceras
    C_STEEL  = colors.HexColor("#1E4D8C")   # azul medio — sub-cabeceras
    C_LIGHT  = colors.HexColor("#F0F4F9")   # celeste muy suave — filas alternas
    C_WHITE  = colors.white
    C_BORDER = colors.HexColor("#CBD5E1")
    C_TOTAL  = colors.HexColor("#1E4D8C")   # fondo fila totales
    C_NETO   = colors.HexColor("#0D2B5E")   # azul BI profundo — neto a pagar
    C_NETO_ACC = colors.HexColor("#90CAF9") # acento celeste BI — cifra neto
    C_GRAY   = colors.HexColor("#64748B")

    empresa_nombre   = empresa_info.get('nombre', '')
    empresa_ruc      = empresa_info.get('ruc', '')
    empresa_domicilio = empresa_info.get('domicilio', '')
    empresa_rep      = empresa_info.get('representante', '')

    periodo_texto = _periodo_legible(periodo)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=36, leftMargin=36, topMargin=30, bottomMargin=30
    )
    elements = []
    styles = getSampleStyleSheet()

    # Estilos tipográficos
    st_emp  = ParagraphStyle('Emp',  fontName="Helvetica-Bold",   fontSize=15, textColor=C_WHITE, spaceAfter=1, leading=18)
    st_sub  = ParagraphStyle('Sub',  fontName="Helvetica",        fontSize=8,  textColor=C_GRAY,  spaceAfter=0, leading=11)
    st_tit  = ParagraphStyle('Tit',  fontName="Helvetica-Bold",   fontSize=12, textColor=C_NAVY,  alignment=TA_CENTER, spaceAfter=2)
    st_per  = ParagraphStyle('Per',  fontName="Helvetica",        fontSize=10, textColor=C_STEEL, alignment=TA_CENTER, spaceAfter=0)

    # Ancho útil de la página
    W = 595 - 72  # A4 ancho - márgenes izq+der = 523 pt

    df_data = df_resultados[df_resultados['Apellidos y Nombres'] != 'TOTALES']

    for _, row in df_data.iterrows():
        dni = str(row['DNI'])
        trab_rows = df_trabajadores[df_trabajadores['Num. Doc.'] == dni]
        trabajador = trab_rows.iloc[0] if not trab_rows.empty else pd.Series(dtype=object)
        var_rows = df_variables[df_variables['Num. Doc.'] == dni] if not df_variables.empty and 'Num. Doc.' in df_variables.columns else pd.DataFrame()
        variables = var_rows.iloc[0] if not var_rows.empty else pd.Series(dtype=object)
        data_aud   = auditoria_data.get(dni, {})

        nombre        = row['Apellidos y Nombres']
        cargo         = trabajador.get('Cargo', '—')
        fi_raw        = trabajador.get('Fecha Ingreso', '')
        fecha_ingreso = fi_raw.strftime('%d/%m/%Y') if hasattr(fi_raw, 'strftime') else str(fi_raw)
        sistema_pension = trabajador.get('Sistema Pensión', 'NO AFECTO')
        cuspp = trabajador.get('CUSPP', '') or '—'
        if pd.isna(cuspp) or cuspp in ("N/A", "", "nan"): cuspp = "—"

        seg_label  = data_aud.get('seguro_social', row.get('Seg. Social', 'ESSALUD'))
        aporte_seg = data_aud.get('aporte_seg_social', row.get('Aporte Seg. Social', row.get('EsSalud Patronal', 0.0)))
        if seg_label == "SIS":        et_seg = "SIS  (S/ 15.00 fijo)"
        elif seg_label == "ESSALUD-EPS": et_seg = "ESSALUD-EPS"
        else:                            et_seg = "ESSALUD  (9%)"

        dias_lab = data_aud.get('dias', 30)
        hrs_ext  = float(variables.get('Hrs Extras 25%', 0)) + float(variables.get('Hrs Extras 35%', 0))

        ingresos_dict  = data_aud.get('ingresos', {})
        descuentos_dict = data_aud.get('descuentos', {})
        ing_list  = [(k, v) for k, v in ingresos_dict.items()  if v > 0]
        desc_list = [(k, v) for k, v in descuentos_dict.items() if v > 0]

        tot_ing  = float(row.get('TOTAL BRUTO', 0.0))
        tot_desc = tot_ing - float(row.get('NETO A PAGAR', 0.0))
        neto     = float(row.get('NETO A PAGAR', 0.0))

        # ── A. CABECERA DE EMPRESA ──────────────────────────────────────────
        elements.append(Spacer(1, 4))

        # Cuerpo cabecera empresa
        ruc_line  = f"RUC: {empresa_ruc}" if empresa_ruc else ""
        dom_line  = empresa_domicilio[:80] if empresa_domicilio else ""
        rep_line  = f"Rep. Legal: {empresa_rep}" if empresa_rep else ""
        sub_parts = [p for p in [ruc_line, dom_line, rep_line] if p]
        sub_text  = "  |  ".join(sub_parts) if sub_parts else ""

        hdr_data = [[Paragraph(empresa_nombre, st_emp)],
                    [Paragraph(sub_text, st_sub)]]
        t_hdr = Table(hdr_data, colWidths=[W])
        t_hdr.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), C_NAVY),
            ('LEFTPADDING',   (0,0), (-1,-1), 10),
            ('RIGHTPADDING',  (0,0), (-1,-1), 10),
            ('TOPPADDING',    (0,0), (0, 0),  8),
            ('BOTTOMPADDING', (0,1), (-1,-1), 8),
            ('TOPPADDING',    (0,1), (-1,-1), 2),
        ]))
        elements.append(t_hdr)

        # ── B. TÍTULO DEL DOCUMENTO ─────────────────────────────────────────
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("BOLETA DE PAGO DE REMUNERACIONES", st_tit))
        elements.append(Paragraph(f"(D.S. N° 001-98-TR)  ·  Periodo: {periodo_texto}", st_per))
        elements.append(Spacer(1, 8))

        # ── C. DATOS DEL TRABAJADOR ─────────────────────────────────────────
        st_val_wrap = ParagraphStyle('ValW', fontName="Helvetica", fontSize=8,
                                     textColor=colors.black, leading=10, wordWrap='LTR')
        info_data = [
            ["TRABAJADOR",     Paragraph(nombre, st_val_wrap), "DOC. IDENTIDAD", dni],
            ["CARGO",          cargo,            "FECHA INGRESO",  fecha_ingreso],
            ["SIST. PENSIÓN",  sistema_pension,  "CUSPP",          cuspp],
            ["SEGURO SOCIAL",  seg_label,        "REM. DIARIA",    f"S/ {data_aud.get('rem_diaria', 0.0):,.2f}"],
            ["DÍAS LABORADOS", str(int(dias_lab)),"HORAS EXTRAS",  f"{hrs_ext:.1f} h"],
        ]
        WL, WV, WL2, WV2 = 82, 170, 82, 189
        t_info = Table(info_data, colWidths=[WL, WV, WL2, WV2])
        t_info.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), C_LIGHT),
            ('BACKGROUND',    (0,0), (0,-1), C_NAVY),
            ('BACKGROUND',    (2,0), (2,-1), C_NAVY),
            ('TEXTCOLOR',     (0,0), (0,-1), C_WHITE),
            ('TEXTCOLOR',     (2,0), (2,-1), C_WHITE),
            ('FONTNAME',      (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTNAME',      (2,0), (2,-1), 'Helvetica-Bold'),
            ('FONTNAME',      (1,0), (1,-1), 'Helvetica'),
            ('FONTNAME',      (3,0), (3,-1), 'Helvetica'),
            ('FONTSIZE',      (0,0), (-1,-1), 8),
            ('ALIGN',         (0,0), (-1,-1), 'LEFT'),
            ('LEFTPADDING',   (0,0), (-1,-1), 6),
            ('RIGHTPADDING',  (0,0), (-1,-1), 6),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('BOX',           (0,0), (-1,-1), 0.8, C_STEEL),
            ('INNERGRID',     (0,0), (-1,-1), 0.3, C_BORDER),
        ]))
        elements.append(t_info)
        elements.append(Spacer(1, 10))

        # ── D. MATRIZ FINANCIERA: INGRESOS | DESCUENTOS (2 columnas) ───────
        # Equalizamos el número de filas para alinear ambas columnas
        max_rows = max(len(ing_list), len(desc_list), 1)
        ing_pad  = ing_list  + [("", None)] * (max_rows - len(ing_list))
        desc_pad = desc_list + [("", None)] * (max_rows - len(desc_list))

        # Anchos: cada columna = (W - 2px separación) / 2
        W_COL = (W - 2) / 2          # ~260 pt
        W_LBL = W_COL * 0.73         # ~190 pt — concepto
        W_MNT = W_COL * 0.27         # ~70 pt  — monto

        # Cabeceras
        fin_data = [[
            Paragraph("<b>INGRESOS</b>", ParagraphStyle('H', fontName="Helvetica-Bold", fontSize=8.5, textColor=C_WHITE, alignment=TA_LEFT)),
            Paragraph("<b>S/</b>", ParagraphStyle('H2', fontName="Helvetica-Bold", fontSize=8.5, textColor=C_WHITE, alignment=TA_RIGHT)),
            Paragraph("<b>DESCUENTOS Y RETENCIONES</b>", ParagraphStyle('H', fontName="Helvetica-Bold", fontSize=8.5, textColor=C_WHITE, alignment=TA_LEFT)),
            Paragraph("<b>S/</b>", ParagraphStyle('H2', fontName="Helvetica-Bold", fontSize=8.5, textColor=C_WHITE, alignment=TA_RIGHT)),
        ]]

        for i in range(max_rows):
            ik, iv = ing_pad[i]
            dk, dv = desc_pad[i]
            fin_data.append([
                ik,
                f"{iv:,.2f}" if iv is not None and iv > 0 else "",
                dk,
                f"{dv:,.2f}" if dv is not None and dv > 0 else "",
            ])

        # Fila de totales
        fin_data.append([
            Paragraph("<b>TOTAL INGRESOS</b>", ParagraphStyle('T', fontName="Helvetica-Bold", fontSize=8.5, textColor=C_WHITE)),
            Paragraph(f"<b>{tot_ing:,.2f}</b>", ParagraphStyle('T2', fontName="Helvetica-Bold", fontSize=8.5, textColor=C_WHITE, alignment=TA_RIGHT)),
            Paragraph("<b>TOTAL DESCUENTOS</b>", ParagraphStyle('T', fontName="Helvetica-Bold", fontSize=8.5, textColor=C_WHITE)),
            Paragraph(f"<b>{tot_desc:,.2f}</b>", ParagraphStyle('T2', fontName="Helvetica-Bold", fontSize=8.5, textColor=C_WHITE, alignment=TA_RIGHT)),
        ])

        t_fin = Table(fin_data, colWidths=[W_LBL, W_MNT, W_LBL, W_MNT])
        fin_style = [
            # Cabecera
            ('BACKGROUND',    (0,0), (-1,0),  C_STEEL),
            # Columna separadora visual (borde derecho de col 1)
            ('LINEAFTER',     (1,0), (1,-1),  1.2, C_STEEL),
            # Filas alternadas ingresos (col 0-1)
            ('ROWBACKGROUNDS',(0,1), (1,-2),  [C_WHITE, C_LIGHT]),
            # Filas alternadas descuentos (col 2-3)
            ('ROWBACKGROUNDS',(2,1), (3,-2),  [C_WHITE, C_LIGHT]),
            # Total
            ('BACKGROUND',    (0,-1), (-1,-1), C_TOTAL),
            # Alineación montos a la derecha
            ('ALIGN',         (1,0), (1,-1),  'RIGHT'),
            ('ALIGN',         (3,0), (3,-1),  'RIGHT'),
            ('ALIGN',         (0,0), (0,-1),  'LEFT'),
            ('ALIGN',         (2,0), (2,-1),  'LEFT'),
            ('FONTNAME',      (0,1), (-1,-2), 'Helvetica'),
            ('FONTSIZE',      (0,1), (-1,-2), 8),
            ('LEFTPADDING',   (0,0), (-1,-1), 5),
            ('RIGHTPADDING',  (0,0), (-1,-1), 5),
            ('TOPPADDING',    (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('BOX',           (0,0), (-1,-1), 0.8, C_STEEL),
            ('INNERGRID',     (0,0), (-1,-1), 0.25, C_BORDER),
        ]
        t_fin.setStyle(TableStyle(fin_style))
        elements.append(t_fin)
        elements.append(Spacer(1, 6))

        # ── E. APORTES DEL EMPLEADOR ────────────────────────────────────────
        apo_data = [
            [Paragraph("<b>APORTES A CARGO DEL EMPLEADOR</b>",
                        ParagraphStyle('AH', fontName="Helvetica-Bold", fontSize=8, textColor=C_WHITE)),
             "", ""],
            [et_seg, f"Base: S/ {aporte_seg:,.2f}", f"S/ {aporte_seg:,.2f}"],
        ]
        t_apo = Table(apo_data, colWidths=[W * 0.5, W * 0.3, W * 0.2])
        t_apo.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,0),  C_GRAY),
            ('SPAN',          (0,0), (-1,0)),
            ('BACKGROUND',    (0,1), (-1,1),  C_LIGHT),
            ('FONTNAME',      (0,1), (-1,1),  'Helvetica'),
            ('FONTNAME',      (2,1), (2,1),   'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 8),
            ('ALIGN',         (2,0), (2,-1),  'RIGHT'),
            ('ALIGN',         (0,0), (1,-1),  'LEFT'),
            ('LEFTPADDING',   (0,0), (-1,-1), 6),
            ('RIGHTPADDING',  (0,0), (-1,-1), 6),
            ('TOPPADDING',    (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('BOX',           (0,0), (-1,-1), 0.8, C_STEEL),
            ('INNERGRID',     (0,0), (-1,-1), 0.25, C_BORDER),
        ]))
        elements.append(t_apo)
        elements.append(Spacer(1, 8))

        # ── F. NETO A PAGAR ─────────────────────────────────────────────────
        neto_data = [[
            Paragraph("NETO A PAGAR AL TRABAJADOR",
                       ParagraphStyle('NL', fontName="Helvetica-Bold", fontSize=11, textColor=C_WHITE, alignment=TA_RIGHT)),
            Paragraph(f"S/  {neto:,.2f}",
                       ParagraphStyle('NV', fontName="Helvetica-Bold", fontSize=13, textColor=C_NETO_ACC, alignment=TA_CENTER)),
        ]]
        t_neto = Table(neto_data, colWidths=[W * 0.65, W * 0.35])
        t_neto.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), C_NETO),
            ('ALIGN',         (0,0), (0,0),   'RIGHT'),
            ('ALIGN',         (1,0), (1,0),   'CENTER'),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING',    (0,0), (-1,-1), 10),
            ('BOTTOMPADDING', (0,0), (-1,-1), 10),
            ('LEFTPADDING',   (0,0), (-1,-1), 10),
            ('BOX',           (0,0), (-1,-1), 1, C_STEEL),
        ]))
        elements.append(t_neto)
        elements.append(Spacer(1, 80))

        # ── G. FIRMAS ────────────────────────────────────────────────────────
        sig_data = [
            ["_" * 35, "", "_" * 35],
            [f"Empleador: {empresa_nombre}", "", f"Trabajador: {nombre}"],
            ["Sello y Firma", "", f"DNI: {dni}"],
        ]
        t_sig = Table(sig_data, colWidths=[W * 0.42, W * 0.16, W * 0.42])
        t_sig.setStyle(TableStyle([
            ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME',   (0,1), (-1,-1), 'Helvetica-Bold'),
            ('FONTNAME',   (0,2), (-1,-1), 'Helvetica'),
            ('FONTSIZE',   (0,0), (-1,-1), 8),
            ('TEXTCOLOR',  (0,0), (-1,-1), C_GRAY),
            ('TOPPADDING', (0,0), (-1,-1), 2),
        ]))
        elements.append(t_sig)

        elements.append(Spacer(1, 10))
        elements.append(PageBreak())

    doc.build(elements)
    buffer.seek(0)
    return buffer


def generar_zip_boletas(empresa_info, periodo, df_resultados, df_trabajadores, df_variables, auditoria_data):
    """Genera un archivo ZIP que contiene un PDF individual por cada trabajador"""
    zip_buffer = io.BytesIO()
    df_data = df_resultados[df_resultados['Apellidos y Nombres'] != 'TOTALES']
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for index, row in df_data.iterrows():
            dni = str(row['DNI'])
            nombre = row['Apellidos y Nombres']
            
            # Filtramos el dataframe para enviarle solo a este trabajador al motor de PDF
            df_individual = df_data[df_data['DNI'] == dni]
            
            # Generamos el PDF único de este trabajador
            pdf_individual_buffer = generar_pdf_boletas_masivas(
                empresa_info, periodo, df_individual, df_trabajadores, df_variables, auditoria_data
            )
            
            # Formateamos el nombre del archivo: BOLETA_12345678_JUAN_PEREZ.pdf
            nombre_archivo = f"BOLETA_{dni}_{nombre.replace(' ', '_')}.pdf"
            
            # Escribimos el PDF dentro del ZIP
            zip_file.writestr(nombre_archivo, pdf_individual_buffer.getvalue())
            
    zip_buffer.seek(0)
    return zip_buffer


def render():
    st.title("🖨️ Emisión de Boletas de Pago")
    st.markdown("---")

    empresa_id = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')

    if not empresa_id:
        st.error("⚠️ Acceso denegado. Seleccione una empresa en el Dashboard.")
        return

    db = SessionLocal()
    try:
        # ── SIEMPRE cargar planillas disponibles de Neon y mostrar selector ──────
        planillas = _recuperar_datos_desde_neon(db, empresa_id)
        if not planillas:
            st.warning("⚠️ No hay planillas calculadas para esta empresa.")
            st.info("Vaya al módulo 'Cálculo de Planilla', seleccione un periodo y ejecute el motor primero.")
            return

        periodos_disponibles = [p.periodo_key for p in planillas]
        labels_disponibles   = [_periodo_legible(k) for k in periodos_disponibles]

        # Detectar periodo activo en sesión para poner como default
        session_periodo = ""
        if st.session_state.get('auditoria_data'):
            vals = list(st.session_state['auditoria_data'].values())
            if vals:
                session_periodo = vals[0].get('periodo', '')

        default_idx = periodos_disponibles.index(session_periodo) if session_periodo in periodos_disponibles else 0
        sel_label   = st.selectbox(
            "Seleccione el periodo a emitir:", labels_disponibles,
            index=default_idx, key="emision_periodo_sel"
        )
        periodo_key = periodos_disponibles[labels_disponibles.index(sel_label)]

        # Cargar datos: desde sesión si coincide el periodo, sino desde Neon
        session_matches = (
            periodo_key == session_periodo
            and not st.session_state.get('res_planilla', pd.DataFrame()).empty
        )
        if session_matches:
            df_resultados  = st.session_state['res_planilla']
            auditoria_data = st.session_state.get('auditoria_data', {})
            df_trab = st.session_state.get('trabajadores_mock', pd.DataFrame())
            df_var  = st.session_state.get('variables_por_periodo', {}).get(periodo_key, pd.DataFrame())
            if df_trab.empty or df_var.empty:
                _, _, df_trab, df_var = _cargar_planilla_periodo(db, empresa_id, periodo_key)
        else:
            df_resultados, auditoria_data, df_trab, df_var = _cargar_planilla_periodo(
                db, empresa_id, periodo_key
            )
            if df_resultados is None:
                st.error(f"No se pudo cargar la planilla del periodo {periodo_key}.")
                return
            st.session_state['res_planilla']     = df_resultados
            st.session_state['auditoria_data']   = auditoria_data
            st.session_state['trabajadores_mock'] = df_trab
            if 'variables_por_periodo' not in st.session_state:
                st.session_state['variables_por_periodo'] = {}
            st.session_state['variables_por_periodo'][periodo_key] = df_var

    except Exception as e:
        st.error(f"Error al conectar con la base de datos: {e}")
        db.close()
        return

    db.close()

    # Dict con datos completos de la empresa para los PDF
    empresa_info = {
        'nombre':        st.session_state.get('empresa_activa_nombre', ''),
        'ruc':           st.session_state.get('empresa_activa_ruc', ''),
        'domicilio':     st.session_state.get('empresa_activa_domicilio', ''),
        'representante': st.session_state.get('empresa_activa_representante', ''),
    }
    periodo_legible = _periodo_legible(periodo_key)

    st.success(f"✅ Planilla del periodo **{periodo_legible}** lista para emisión.")
    st.markdown(f"**Empresa:** {empresa_nombre}")

    # --- PANEL DE DISTRIBUCIÓN MULTICANAL ---
    st.markdown("### 📄 Centro de Distribución de Documentos")
    
    tab1, tab2, tab3 = st.tabs([
        "📚 Descarga Masiva (Para RRHH)", 
        "👤 Emisión Individual (Por Trabajador)",
        "📧 Distribución Digital (Email)"
    ])

    with tab1:
        st.markdown("Elija el formato de descarga masiva para toda la planilla del mes:")
        col1, col2 = st.columns(2)
        
        with col1:
            st.info("**Opción 1: Libro Consolidado**\n\nGenera un único archivo PDF que contiene todas las boletas una detrás de otra. Ideal para imprimir todo de una sola vez y archivar físicamente.")
            if st.button("🖨️ Generar 1 Solo PDF con Todo", use_container_width=True):
                with st.spinner('Compilando libro maestro...'):
                    pdf_buffer = generar_pdf_boletas_masivas(empresa_info, periodo_key, df_resultados, df_trab, df_var, auditoria_data)
                    st.download_button(
                        label=f"📥 Descargar LIBRO_{periodo_legible}.pdf",
                        data=pdf_buffer, file_name=f"LIBRO_BOLETAS_{periodo_key}.pdf", mime="application/pdf",
                        type="primary", use_container_width=True
                    )

        with col2:
            st.info("**Opción 2: Archivo ZIP (Separadas)**\n\nGenera un archivo comprimido (.zip) que contiene las boletas en formato PDF individualizadas, cada una con el DNI y Nombre del trabajador.")
            if st.button("🗂️ Generar Archivo ZIP (PDFs separados)", use_container_width=True):
                with st.spinner('Empaquetando PDFs individuales en ZIP...'):
                    zip_buffer = generar_zip_boletas(empresa_info, periodo_key, df_resultados, df_trab, df_var, auditoria_data)
                    st.download_button(
                        label=f"📥 Descargar PAQUETE_{periodo_legible}.zip",
                        data=zip_buffer, file_name=f"BOLETAS_INDIVIDUALES_{periodo_key}.zip", mime="application/zip",
                        type="primary", use_container_width=True
                    )

    with tab2:
        st.markdown("Seleccione un trabajador específico para descargar únicamente su boleta de pago de este periodo.")
        
        df_sin_totales = df_resultados[df_resultados['Apellidos y Nombres'] != 'TOTALES']
        opciones_trab = df_sin_totales['DNI'].astype(str) + " - " + df_sin_totales['Apellidos y Nombres']
        
        trabajador_sel = st.selectbox("Buscar Trabajador:", opciones_trab)
        
        if trabajador_sel:
            dni_sel = trabajador_sel.split(" - ")[0]
            nombre_sel = trabajador_sel.split(" - ")[1]
            
            st.markdown(f"**Trabajador Seleccionado:** {nombre_sel}")
            
            col_ind1, col_ind2 = st.columns(2)
            
            if col_ind1.button(f"📄 Generar Boleta de {nombre_sel}", type="primary", use_container_width=True):
                df_individual = df_sin_totales[df_sin_totales['DNI'] == dni_sel]
                
                with st.spinner('Generando boleta...'):
                    pdf_ind_buffer = generar_pdf_boletas_masivas(empresa_info, periodo_key, df_individual, df_trab, df_var, auditoria_data)
                    st.download_button(
                        label=f"📥 Descargar BOLETA_{dni_sel}.pdf",
                        data=pdf_ind_buffer,
                        file_name=f"BOLETA_{dni_sel}_{periodo_key}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )

            # --- OPCIÓN DE ENVÍO INDIVIDUAL POR EMAIL ---
            trab_email_row = df_trab[df_trab['Num. Doc.'] == dni_sel]
            email_destino = ""
            if not trab_email_row.empty:
                email_destino = trab_email_row.iloc[0].get('correo_electronico', "")

            if col_ind2.button(f"📧 Enviar por Correo a {nombre_sel}", use_container_width=True, disabled=not email_destino):
                from core.use_cases.envio_correos import encriptar_pdf_en_memoria, enviar_boleta_por_correo
                from infrastructure.database.models import LogEnvioBoleta, Trabajador as TrabajadorModel
                
                with st.spinner('Procesando envío seguro...'):
                    try:
                        # 1. Generar PDF
                        df_ind_mail = df_sin_totales[df_sin_totales['DNI'] == dni_sel]
                        pdf_orig_ind = generar_pdf_boletas_masivas(empresa_info, periodo_key, df_ind_mail, df_trab, df_var, auditoria_data)
                        
                        # 2. Encriptar
                        pdf_enc_ind = encriptar_pdf_en_memoria(pdf_orig_ind, dni_sel)
                        
                        # 3. Enviar
                        db_conf = SessionLocal()
                        emp_db = db_conf.query(Empresa).get(empresa_id)
                        smtp_conf = {
                            'host': emp_db.smtp_host, 'port': emp_db.smtp_port,
                            'user': emp_db.smtp_user, 'pass': emp_db.smtp_pass
                        }
                        res_mail = enviar_boleta_por_correo(email_destino, periodo_legible, pdf_enc_ind, nombre_sel, empresa_nombre, config_smtp=smtp_conf)
                        db_conf.close()
                        
                        # 4. Registrar Log
                        db_log_ind = SessionLocal()
                        t_obj = db_log_ind.query(TrabajadorModel).filter_by(num_doc=dni_sel, empresa_id=empresa_id).first()
                        
                        log_ind = LogEnvioBoleta(
                            empresa_id=empresa_id,
                            trabajador_id=t_obj.id if t_obj else 0,
                            periodo_key=periodo_key,
                            correo_destino=email_destino,
                            estado="ENVIADO" if res_mail is True else "ERROR",
                            mensaje_error=None if res_mail is True else str(res_mail)
                        )
                        db_log_ind.add(log_ind)
                        db_log_ind.commit()
                        db_log_ind.close()

                        if res_mail is True:
                            st.success(f"✅ Boleta enviada correctamente a **{email_destino}**")
                        else:
                            st.error(f"❌ Error al enviar: {res_mail}")
                    except Exception as e_ind:
                        st.error(f"Error crítico: {e_ind}")
            
            if not email_destino:
                st.caption("⚠️ El trabajador no tiene correo registrado. Configure su email en el Maestro de Personal para habilitar el envío.")

    with tab3:
        st.subheader("🚀 Envío Masivo de Boletas por Correo")
        st.info("Esta función enviará automáticamente las boletas encriptadas a los correos registrados.")

        # Data Quality Check - Asegurar existencia de la columna para evitar KeyError
        df_emails = df_trab[df_trab['Num. Doc.'].isin(df_resultados['DNI'])].copy()
        if 'correo_electronico' not in df_emails.columns:
            df_emails['correo_electronico'] = ""

        sin_correo = df_emails[df_emails['correo_electronico'].isna() | (df_emails['correo_electronico'] == '')]
        con_correo = df_emails[~df_emails['Num. Doc.'].isin(sin_correo['Num. Doc.'])]

        if not sin_correo.empty:
            st.warning(f"⚠️ **Alerta de Cumplimiento:** {len(sin_correo)} trabajador(es) NO tienen correo registrado y no recibirán su boleta.")
            with st.expander("Ver lista de trabajadores sin correo"):
                st.write(sin_correo[['Num. Doc.', 'Nombres y Apellidos']])
        
        st.success(f"✅ {len(con_correo)} trabajador(es) listos para envío seguro.")

        if st.button("🚀 Iniciar Envío Masivo Seguro", use_container_width=True, type="primary"):
            from core.use_cases.envio_correos import encriptar_pdf_en_memoria, enviar_boleta_por_correo
            from infrastructure.database.models import LogEnvioBoleta
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            exitos = 0
            errores = 0
            
            db_log = SessionLocal()
            try:
                total_envios = len(con_correo)
                for i, (_, t_row) in enumerate(con_correo.iterrows()):
                    dni_envio = str(t_row['Num. Doc.'])
                    nombre_envio = t_row['Nombres y Apellidos']
                    mail_destino = t_row['correo_electronico']
                    
                    status_text.text(f"Procesando ({i+1}/{total_envios}): {nombre_envio}")
                    
                    # 1. Generar PDF Individual
                    df_ind = df_resultados[df_resultados['DNI'] == dni_envio]
                    pdf_orig = generar_pdf_boletas_masivas(empresa_info, periodo_key, df_ind, df_trab, df_var, auditoria_data)
                    
                    # 2. Encriptar con DNI
                    pdf_enc = encriptar_pdf_en_memoria(pdf_orig, dni_envio)
                    
                    # 3. Enviar con configuración de la empresa
                    emp_db = db_log.query(Empresa).get(empresa_id)
                    smtp_conf = {
                        'host': emp_db.smtp_host, 'port': emp_db.smtp_port,
                        'user': emp_db.smtp_user, 'pass': emp_db.smtp_pass
                    }
                    resultado = enviar_boleta_por_correo(mail_destino, periodo_legible, pdf_enc, nombre_envio, empresa_nombre, config_smtp=smtp_conf)
                    
                    # 4. Log
                    log = LogEnvioBoleta(
                        empresa_id=empresa_id,
                        trabajador_id=db_log.query(Trabajador).filter_by(num_doc=dni_envio, empresa_id=empresa_id).first().id,
                        periodo_key=periodo_key,
                        correo_destino=mail_destino,
                        estado="ENVIADO" if resultado is True else "ERROR",
                        mensaje_error=None if resultado is True else str(resultado)
                    )
                    db_log.add(log)
                    db_log.commit()
                    
                    if resultado is True: exitos += 1
                    else: errores += 1
                    
                    progress_bar.progress((i + 1) / total_envios)
                
                st.balloons()
                st.success(f"🎊 Proceso terminado. Enviados: {exitos} | Errores: {errores}")
                if errores > 0:
                    st.error("Revise los logs de envío en la base de datos para ver los detalles de los errores.")
            except Exception as e_proc:
                st.error(f"Error crítico en proceso: {e_proc}")
            finally:
                db_log.close()
