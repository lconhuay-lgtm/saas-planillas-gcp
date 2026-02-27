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

def generar_pdf_boletas_masivas(empresa_nombre, periodo, df_resultados, df_trabajadores, df_variables, auditoria_data):
    """Genera un PDF con boletas a página completa (Puede recibir 1 o N trabajadores)"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    elements = []
    
    styles = getSampleStyleSheet()
    style_company = ParagraphStyle('Company', parent=styles['Title'], fontSize=16, textColor=colors.HexColor("#1A365D"), alignment=TA_LEFT, fontName="Helvetica-Bold", spaceAfter=2)
    style_ruc = ParagraphStyle('RUC', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor("#7F8C8D"), alignment=TA_LEFT, spaceAfter=20)
    style_title = ParagraphStyle('DocTitle', parent=styles['Title'], fontSize=14, textColor=colors.black, alignment=TA_CENTER, fontName="Helvetica-Bold", spaceAfter=5)
    style_sub = ParagraphStyle('DocSub', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor("#34495E"), alignment=TA_CENTER, spaceAfter=25)

    df_data = df_resultados[df_resultados['Apellidos y Nombres'] != 'TOTALES']
    
    for index, row in df_data.iterrows():
        dni = str(row['DNI'])
        
        # Extracción de datos
        trabajador = df_trabajadores[df_trabajadores['Num. Doc.'] == dni].iloc[0]
        variables = df_variables[df_variables['Num. Doc.'] == dni].iloc[0]
        data_aud = auditoria_data.get(dni, {})
        
        nombre = row['Apellidos y Nombres']
        cargo = trabajador.get('Cargo', 'No especificado')
        fecha_ing_raw = trabajador.get('Fecha Ingreso', '')
        fecha_ingreso = fecha_ing_raw.strftime('%d/%m/%Y') if hasattr(fecha_ing_raw, 'strftime') else str(fecha_ing_raw)
        sistema_pension = trabajador.get('Sistema Pensión', 'NO AFECTO')
        cuspp = trabajador.get('CUSPP', '')
        if pd.isna(cuspp) or cuspp == "N/A" or cuspp == "": cuspp = "---"

        # Seguro social: leer de auditoría (más confiable) o de la sábana
        seguro_social_label = data_aud.get('seguro_social', row.get('Seg. Social', 'ESSALUD'))
        aporte_seg_social = data_aud.get('aporte_seg_social', row.get('Aporte Seg. Social', row.get('EsSalud Patronal', 0.0)))
        if seguro_social_label == "SIS":
            etiqueta_aporte = "SIS (S/15 fijo)"
        elif seguro_social_label == "ESSALUD-EPS":
            etiqueta_aporte = "ESSALUD-EPS"
        else:
            etiqueta_aporte = "ESSALUD (9%)"

        dias_laborados = data_aud.get('dias', 30)
        hrs_ext = float(variables.get('Hrs Extras 25%', 0)) + float(variables.get('Hrs Extras 35%', 0))

        ingresos_dict = data_aud.get('ingresos', {})
        descuentos_dict = data_aud.get('descuentos', {})
        aportes_dict = {etiqueta_aporte: aporte_seg_social}
        
        ing_list = [(k, f"{v:,.2f}") for k, v in ingresos_dict.items() if v > 0]
        desc_list = [(k, f"{v:,.2f}") for k, v in descuentos_dict.items() if v > 0]
        apo_list = [(k, f"{v:,.2f}") for k, v in aportes_dict.items() if v > 0]
        
        tot_ing = row.get('TOTAL BRUTO', 0.0)
        tot_apo = aporte_seg_social
        tot_desc = row.get('T. DESCUENTOS', 0.0)
        if tot_desc == 0.0:
            tot_desc = tot_ing - row.get('NETO A PAGAR', 0.0)
            
        neto = row.get('NETO A PAGAR', 0.0)

        # A. Cabecera Corporativa
        elements.append(Paragraph(empresa_nombre.upper(), style_company))
        elements.append(Paragraph("RUC: 20000000000", style_ruc)) 
        
        # B. Título de Documento Oficial
        elements.append(Paragraph("BOLETA DE PAGO DE REMUNERACIONES", style_title))
        elements.append(Paragraph(f"(D.S. N° 001-98-TR) <br/> <b>Periodo de Pago: {periodo}</b>", style_sub))

        # C. Datos del Trabajador
        info_data = [
            ["TRABAJADOR:", nombre, "DOC. IDENTIDAD:", dni],
            ["CARGO:", cargo, "FECHA INGRESO:", fecha_ingreso],
            ["SIST. PENSIÓN:", sistema_pension, "CUSPP:", cuspp],
            ["SEGURO SOCIAL:", seguro_social_label, "APORTE EMPLEADOR:", f"S/ {aporte_seg_social:,.2f}"],
            ["DÍAS LABORADOS:", str(int(dias_laborados)), "HORAS EXTRAS:", str(hrs_ext)]
        ]
        t_info = Table(info_data, colWidths=[110, 200, 105, 100])
        t_info.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")), 
            ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor("#2C3E50")),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'), 
            ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'), 
            ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
            ('FONTNAME', (3,0), (3,-1), 'Helvetica'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#CBD5E1")),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0"))
        ]))
        elements.append(t_info)
        elements.append(Spacer(1, 25))

        # D. Matriz Financiera Principal
        max_rows = max(len(ing_list), len(desc_list), len(apo_list))
        if max_rows == 0: max_rows = 1
        ing_pad = ing_list + [("", "")] * (max_rows - len(ing_list))
        desc_pad = desc_list + [("", "")] * (max_rows - len(desc_list))
        apo_pad = apo_list + [("", "")] * (max_rows - len(apo_list))

        fin_data = [["INGRESOS", "S/", "DESCUENTOS / RETENCIONES", "S/", "APORTES EMPLEADOR", "S/"]]
        for i in range(max_rows):
            fin_data.append([
                ing_pad[i][0], ing_pad[i][1],
                desc_pad[i][0], desc_pad[i][1],
                apo_pad[i][0], apo_pad[i][1]
            ])
            
        fin_data.append([
            "TOTAL INGRESOS", f"{tot_ing:,.2f}",
            "TOTAL DESCUENTOS", f"{tot_desc:,.2f}",
            "TOTAL APORTES", f"{tot_apo:,.2f}"
        ])

        t_fin = Table(fin_data, colWidths=[125, 45, 140, 45, 115, 45])
        t_fin.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,0), 'CENTER'),
            ('FONTSIZE', (0,0), (-1,0), 8),
            ('BOTTOMPADDING', (0,0), (-1,0), 8),
            ('TOPPADDING', (0,0), (-1,0), 8),
            ('FONTNAME', (0,1), (-1,-2), 'Helvetica'),
            ('FONTSIZE', (0,1), (-1,-2), 9),
            ('ALIGN', (1,1), (1,-1), 'RIGHT'),
            ('ALIGN', (3,1), (3,-1), 'RIGHT'),
            ('ALIGN', (5,1), (5,-1), 'RIGHT'),
            ('BOTTOMPADDING', (0,1), (-1,-2), 4),
            ('TOPPADDING', (0,1), (-1,-2), 4),
            ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#F1F5F9")),
            ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,-1), (-1,-1), 9),
            ('TOPPADDING', (0,-1), (-1,-1), 8),
            ('BOTTOMPADDING', (0,-1), (-1,-1), 8),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#1A365D")),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
            ('LINEABOVE', (0,-1), (-1,-1), 1, colors.HexColor("#1A365D")) 
        ]))
        elements.append(t_fin)
        elements.append(Spacer(1, 15))

        # E. Neto a Pagar
        neto_data = [["NETO A PAGAR AL TRABAJADOR:", f"S/ {neto:,.2f}"]]
        t_neto = Table(neto_data, colWidths=[380, 135])
        t_neto.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#2C3E50")),
            ('TEXTCOLOR', (0,0), (-1,-1), colors.white),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 12),
            ('ALIGN', (0,0), (0,0), 'RIGHT'),
            ('ALIGN', (1,0), (1,0), 'CENTER'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 10),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#1A365D"))
        ]))
        elements.append(t_neto)
        
        # F. Espacio para Firmas
        elements.append(Spacer(1, 80)) 
        
        sig_data = [
            ["_____________________________________", "", "_____________________________________"],
            [f"Empleador: {empresa_nombre}", "", f"Trabajador: {nombre}"],
            ["Sello y Firma", "", f"DNI: {dni}"]
        ]
        t_sig = Table(sig_data, colWidths=[200, 115, 200])
        t_sig.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,1), (-1,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor("#34495E")),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2)
        ]))
        elements.append(t_sig)
        elements.append(PageBreak())

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generar_zip_boletas(empresa_nombre, periodo, df_resultados, df_trabajadores, df_variables, auditoria_data):
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
                empresa_nombre, periodo, df_individual, df_trabajadores, df_variables, auditoria_data
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
        # ── RECUPERAR PLANILLA: session_state tiene prioridad, Neon es el respaldo ──
        hay_planilla_en_sesion = (
            'res_planilla' in st.session_state
            and not st.session_state.get('res_planilla', pd.DataFrame()).empty
        )

        if hay_planilla_en_sesion:
            # Datos ya en memoria (misma sesión de navegador)
            df_resultados = st.session_state['res_planilla']
            auditoria_data = st.session_state.get('auditoria_data', {})
            periodo_key = list(auditoria_data.values())[0]['periodo'] if auditoria_data else "Desconocido"
            df_trab = st.session_state.get('trabajadores_mock', pd.DataFrame())
            df_var = st.session_state.get('variables_por_periodo', {}).get(periodo_key, pd.DataFrame())

            # Si df_trab o df_var están vacíos, cargarlos de Neon como respaldo
            if df_trab.empty or df_var.empty:
                df_res_db, aud_db, df_trab, df_var = _cargar_planilla_periodo(db, empresa_id, periodo_key)
        else:
            # Sin sesión activa: recuperar de Neon y mostrar selector de periodo
            planillas = _recuperar_datos_desde_neon(db, empresa_id)
            if not planillas:
                st.warning("⚠️ No hay planillas calculadas para esta empresa.")
                st.info("Vaya al módulo 'Cálculo de Planilla', seleccione un periodo y ejecute el motor primero.")
                return

            periodos_disponibles = [p.periodo_key for p in planillas]
            st.info("📂 Sesión reiniciada. Seleccione el periodo a emitir:")
            periodo_key = st.selectbox(
                "Periodos con planilla calculada:", periodos_disponibles,
                key="emision_periodo_sel"
            )

            df_resultados, auditoria_data, df_trab, df_var = _cargar_planilla_periodo(
                db, empresa_id, periodo_key
            )
            if df_resultados is None:
                st.error(f"No se pudo cargar la planilla del periodo {periodo_key}.")
                return

            # Restaurar session_state para consistencia
            st.session_state['res_planilla'] = df_resultados
            st.session_state['auditoria_data'] = auditoria_data
            st.session_state['trabajadores_mock'] = df_trab
            if 'variables_por_periodo' not in st.session_state:
                st.session_state['variables_por_periodo'] = {}
            st.session_state['variables_por_periodo'][periodo_key] = df_var

    except Exception as e:
        st.error(f"Error al conectar con la base de datos: {e}")
        db.close()
        return

    db.close()

    st.success(f"✅ Planilla del periodo **{periodo_key}** lista para emisión.")
    st.markdown(f"**Empresa:** {empresa_nombre}")

    # --- PANEL DE DISTRIBUCIÓN MULTICANAL ---
    st.markdown("### 📄 Centro de Distribución de Documentos")
    
    tab1, tab2 = st.tabs(["📚 Descarga Masiva (Para RRHH)", "👤 Emisión Individual (Por Trabajador)"])

    with tab1:
        st.markdown("Elija el formato de descarga masiva para toda la planilla del mes:")
        col1, col2 = st.columns(2)
        
        with col1:
            st.info("**Opción 1: Libro Consolidado**\n\nGenera un único archivo PDF que contiene todas las boletas una detrás de otra. Ideal para imprimir todo de una sola vez y archivar físicamente.")
            if st.button("🖨️ Generar 1 Solo PDF con Todo", use_container_width=True):
                with st.spinner('Compilando libro maestro...'):
                    pdf_buffer = generar_pdf_boletas_masivas(empresa_nombre, periodo_key, df_resultados, df_trab, df_var, auditoria_data)
                    st.download_button(
                        label=f"📥 Descargar LIBRO_{periodo_key}.pdf",
                        data=pdf_buffer, file_name=f"LIBRO_BOLETAS_{periodo_key}.pdf", mime="application/pdf",
                        type="primary", use_container_width=True
                    )
                    
        with col2:
            st.info("**Opción 2: Archivo ZIP (Separadas)**\n\nGenera un archivo comprimido (.zip) que contiene las boletas en formato PDF individualizadas, cada una con el DNI y Nombre del trabajador.")
            if st.button("🗂️ Generar Archivo ZIP (PDFs separados)", use_container_width=True):
                with st.spinner('Empaquetando PDFs individuales en ZIP...'):
                    zip_buffer = generar_zip_boletas(empresa_nombre, periodo_key, df_resultados, df_trab, df_var, auditoria_data)
                    st.download_button(
                        label=f"📥 Descargar PAQUETE_{periodo_key}.zip",
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
            
            if st.button(f"📄 Generar Boleta de {nombre_sel}", type="primary"):
                df_individual = df_sin_totales[df_sin_totales['DNI'] == dni_sel]
                
                with st.spinner('Generando boleta...'):
                    pdf_ind_buffer = generar_pdf_boletas_masivas(empresa_nombre, periodo_key, df_individual, df_trab, df_var, auditoria_data)
                    st.download_button(
                        label=f"📥 Descargar BOLETA_{dni_sel}.pdf",
                        data=pdf_ind_buffer,
                        file_name=f"BOLETA_{dni_sel}_{periodo_key}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )