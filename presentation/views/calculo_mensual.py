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

MESES = ["01 - Enero", "02 - Febrero", "03 - Marzo", "04 - Abril", "05 - Mayo", "06 - Junio", 
         "07 - Julio", "08 - Agosto", "09 - Septiembre", "10 - Octubre", "11 - Noviembre", "12 - Diciembre"]

# --- 1. GENERADORES DE EXPORTACIÓN ---

def generar_excel_sabana(df, empresa_nombre, periodo):
    """Genera un archivo Excel nativo (.xlsx) profesional con colores corporativos"""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=f'Planilla_{periodo[:2]}', index=False, startrow=4)
        ws = writer.sheets[f'Planilla_{periodo[:2]}']
        
        # 1. Títulos de Cabecera
        ws['A1'] = empresa_nombre
        ws['A1'].font = Font(size=16, bold=True, color="1A365D")
        ws['A2'] = f"DETALLE DE PLANILLA DE REMUNERACIONES - PERIODO {periodo}"
        ws['A2'].font = Font(size=11, bold=True, color="34495E")
        ws['A3'] = f"Fecha y Hora de Cálculo: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        ws['A3'].font = Font(size=10, italic=True, color="7F8C8D")
        
        # 2. Estilos Corporativos
        fill_header = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")
        font_header = Font(color="FFFFFF", bold=True)
        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        border_thin = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        fill_total = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
        
        # 3. Aplicar formato a las celdas de la tabla
        for row in ws.iter_rows(min_row=5, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
            for cell in row:
                cell.border = border_thin
                if cell.row == 5: # Fila de nombres de columnas
                    cell.fill = fill_header
                    cell.font = font_header
                    cell.alignment = align_center
                elif cell.row == ws.max_row: # Última fila (Totales)
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

def generar_pdf_sabana(df, empresa_nombre, periodo):
    """Genera la sábana principal de planilla con Cuadro Resumen de AFP"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(legal), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleCorp', parent=styles['Normal'], fontSize=16, textColor=colors.HexColor("#0F2027"), fontName="Helvetica-Bold", spaceAfter=5)
    sub_style = ParagraphStyle('SubCorp', parent=styles['Normal'], fontSize=11, textColor=colors.HexColor("#34495E"), fontName="Helvetica")
    
    fecha_calc = datetime.now().strftime("%d/%m/%Y %H:%M")
    elements.append(Paragraph(empresa_nombre, title_style))
    elements.append(Paragraph(f"DETALLE DE PLANILLA DE REMUNERACIONES | PERIODO: {periodo}", sub_style))
    elements.append(Paragraph(f"FECHA DE CÁLCULO: {fecha_calc}", ParagraphStyle('Date', parent=sub_style, fontSize=9, textColor=colors.HexColor("#7F8C8D"))))
    
    # MÁS ESPACIO (AIRE VISUAL) SEGÚN TU SOLICITUD
    elements.append(Spacer(1, 25)) 

    # Construir Tabla Principal
    cols_pdf = df.columns.tolist()
    data = [cols_pdf]
    for _, row in df.iterrows():
        fila_str = []
        for val in row:
            if isinstance(val, float): fila_str.append(f"{val:,.2f}") 
            else: fila_str.append(str(val))
        data.append(fila_str)

    t = Table(data, repeatRows=1)
    estilo_tabla = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 7.5),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('TOPPADDING', (0,0), (-1,0), 6),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 7),
        ('ALIGN', (1,1), (1,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#F8FAFC")]) 
    ]
    estilo_tabla.extend([
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#CBD5E1")),
        ('TEXTCOLOR', (0,-1), (-1,-1), colors.HexColor("#0F2027")),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
    ])
    t.setStyle(TableStyle(estilo_tabla))
    elements.append(t)
    
    # --- NUEVO: CUADRO RESUMEN DE PREVISIONES (AFP/ONP) ---
    elements.append(Spacer(1, 30))
    elements.append(Paragraph("<b>RESUMEN GENERAL DE RETENCIONES PREVISIONALES</b>", sub_style))
    elements.append(Spacer(1, 10))
    
    df_data = df.iloc[:-1] # Filtramos la fila de totales para no duplicar
    resumen_data = [["ENTIDAD", "APORTE / FONDO", "SEGURO / PRIMA", "COMISIÓN", "TOTAL A PAGAR"]]
    
    total_general = 0.0
    
    # Calcular ONP
    if 'ONP (13%)' in df_data.columns:
        onp_total = df_data['ONP (13%)'].sum()
        if onp_total > 0:
            resumen_data.append(["ONP (Sistema Nacional)", f"{onp_total:,.2f}", "-", "-", f"{onp_total:,.2f}"])
            total_general += onp_total
            
    # Calcular AFPs
    if 'Sist. Pensión' in df_data.columns:
        afps = df_data['Sist. Pensión'].unique()
        for afp in afps:
            if "AFP" in str(afp):
                df_afp = df_data[df_data['Sist. Pensión'] == afp]
                aporte = df_afp['AFP Aporte'].sum()
                seguro = df_afp['AFP Seguro'].sum()
                comis = df_afp['AFP Comis.'].sum()
                tot = aporte + seguro + comis
                if tot > 0:
                    resumen_data.append([afp, f"{aporte:,.2f}", f"{seguro:,.2f}", f"{comis:,.2f}", f"{tot:,.2f}"])
                    total_general += tot
                    
    resumen_data.append(["TOTAL A DECLARAR", "", "", "", f"S/ {total_general:,.2f}"])
    
    t_res = Table(resumen_data, colWidths=[180, 90, 90, 90, 100])
    t_res.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#34495E")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('ALIGN', (0,0), (0,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#BDC3C7")),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#E5E7E9")),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
    ]))
    
    # Solo mostramos la tabla si hay aportes
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

    if 'parametros_globales' not in st.session_state or periodo_key not in st.session_state['parametros_globales']:
        st.error(f"🛑 ALTO: No se han configurado los Parámetros Legales para el periodo **{periodo_key}**.")
        return
        
    p = st.session_state['parametros_globales'][periodo_key]

    if 'trabajadores_mock' not in st.session_state or st.session_state['trabajadores_mock'].empty:
        st.warning("⚠️ Faltan datos: No hay trabajadores en el Maestro.") 
        return
    if 'variables_por_periodo' not in st.session_state or periodo_key not in st.session_state['variables_por_periodo']:
        st.warning(f"⚠️ Faltan datos: No se han ingresado Asistencias para **{periodo_key}**.") 
        return

    df_conceptos = st.session_state.get('conceptos_mock', pd.DataFrame())
    conceptos_empresa = df_conceptos[df_conceptos['Empresa_ID'] == empresa_id] if not df_conceptos.empty else pd.DataFrame()

    df_trab = st.session_state['trabajadores_mock']
    df_var = st.session_state['variables_por_periodo'][periodo_key]
    df_planilla = pd.merge(df_trab, df_var, on="Num. Doc.", how="inner")

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

            # --- ESSALUD Y NETO ---
            tasa_essalud = (p['tasa_eps'] / 100) if row.get('EPS', 'No') == "Sí" else (p['tasa_essalud'] / 100)
            aporte_essalud = max(base_essalud, p['rmv']) * tasa_essalud
            
            neto_pagar = ingresos_totales - total_pension - retencion_quinta - descuentos_manuales

            # --- FILA DE LA SÁBANA CORPORATIVA ---
            resultados.append({
                "N°": index + 1,
                "DNI": dni_trabajador, # ✅ AQUI RESTAURAMOS EL DNI PARA QUE LAS BOLETAS FUNCIONEN
                "Apellidos y Nombres": nombres,
                "Sist. Pensión": sistema,
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
                "EsSalud Patronal": round(aporte_essalud, 2) 
            })

            auditoria_data[dni_trabajador] = {
                "nombres": nombres, "periodo": periodo_key, "dias": dias_computables,
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
        totales = { "N°": "", "DNI": "", "Apellidos y Nombres": "TOTALES", "Sist. Pensión": "" }
        for col in df_resultados.columns[4:]: # Sumar desde la columna 4 (Sueldo Base)
            totales[col] = df_resultados[col].sum()
            
        df_resultados = pd.concat([df_resultados, pd.DataFrame([totales])], ignore_index=True)
        st.session_state['res_planilla'] = df_resultados
        st.session_state['auditoria_data'] = auditoria_data

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
                excel_file = generar_excel_sabana(df_resultados, empresa_nombre, periodo_key)
                st.download_button("📊 Descargar Sábana (.xlsx)", data=excel_file, file_name=f"PLANILLA_{periodo_key}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            except Exception:
                csv = df_resultados.to_csv(index=False).encode('utf-8')
                st.download_button("📊 Descargar Sábana (CSV)", data=csv, file_name=f"PLANILLA_{periodo_key}.csv", mime="text/csv", use_container_width=True)
        with col_btn2:
            pdf_buffer = generar_pdf_sabana(df_resultados, empresa_nombre, periodo_key)
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