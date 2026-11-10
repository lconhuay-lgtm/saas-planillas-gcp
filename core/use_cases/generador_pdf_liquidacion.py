"""
Generador del PDF de Liquidación de Beneficios Sociales por Cese.

Documento oficial — solo se genera a partir de un registro LiquidacionCese ya
GUARDADO (no de un cálculo de pantalla todavía sin persistir), para que todo PDF
emitido corresponda siempre a un registro real y auditable.

Incluye un "Detalle de Liquidación" completo por beneficio (vacaciones,
gratificación, CTS) — base imponible, periodo/meses/días exactos y la fórmula
aplicada — para que el trabajador pueda verificar cada monto sin ninguna cifra
"de caja negra". No hay una tabla-resumen separada al inicio: el desglose ES el
resumen, y el Neto a Pagar cierra el documento como conclusión de todo el cálculo.
El documento puede extenderse a más de una página; el flujo de reportlab lo maneja
automáticamente.
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

# Paleta corporativa — misma que boletas, para que todos los documentos se vean
# como parte del mismo sistema.
C_NAVY   = colors.HexColor("#0F2744")
C_STEEL  = colors.HexColor("#1E4D8C")
C_LIGHT  = colors.HexColor("#F0F4F9")
C_WHITE  = colors.white
C_BORDER = colors.HexColor("#CBD5E1")
C_TOTAL  = colors.HexColor("#1E4D8C")
C_NETO_ACC = colors.HexColor("#90CAF9")
C_GRAY   = colors.HexColor("#64748B")
C_MEMO_HDR = colors.HexColor("#3D5A80")
C_DEDUCCION = C_GRAY   # las deducciones se marcan con signo negativo, no con color de alerta


def generar_pdf_liquidacion(empresa_info, trabajador, liquidacion) -> io.BytesIO:
    """
    empresa_info: dict con claves nombre, ruc, domicilio, representante.
    trabajador: objeto Trabajador (para nombre, cargo, CUSPP, banco).
    liquidacion: objeto LiquidacionCese ya guardado (trae el id como N° de documento).
    """
    empresa_nombre    = empresa_info.get('nombre', '')
    empresa_ruc       = empresa_info.get('ruc', '')
    empresa_domicilio = empresa_info.get('domicilio', '')
    empresa_rep       = empresa_info.get('representante', '')

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=30, bottomMargin=30)
    elements = []
    W = 595 - 72  # A4 ancho - márgenes = 523 pt

    st_emp = ParagraphStyle('Emp', fontName="Helvetica-Bold", fontSize=15, textColor=C_WHITE, spaceAfter=1, leading=18)
    st_sub = ParagraphStyle('Sub', fontName="Helvetica", fontSize=8, textColor=C_GRAY, spaceAfter=0, leading=11)
    st_tit = ParagraphStyle('Tit', fontName="Helvetica-Bold", fontSize=12, textColor=C_NAVY, alignment=TA_CENTER, spaceAfter=2)
    st_per = ParagraphStyle('Per', fontName="Helvetica", fontSize=10, textColor=C_STEEL, alignment=TA_CENTER, spaceAfter=0)
    st_val_wrap = ParagraphStyle('ValW', fontName="Helvetica", fontSize=8, textColor=colors.black, leading=10, wordWrap='LTR')
    st_memo_lbl = ParagraphStyle('MemoL', fontName="Helvetica", fontSize=7.8, textColor=colors.black, leading=10)
    st_memo_val = ParagraphStyle('MemoV', fontName="Helvetica", fontSize=7.8, textColor=colors.black, alignment=TA_RIGHT, leading=10)
    st_memo_formula = ParagraphStyle('MemoF', fontName="Helvetica-Oblique", fontSize=7.5, textColor=C_STEEL, leading=10)
    st_seccion = ParagraphStyle('Seccion', fontName="Helvetica-Bold", fontSize=10, textColor=C_NAVY, spaceAfter=4, spaceBefore=10)

    def _fecha(d):
        return d.strftime('%d/%m/%Y') if d else '—'

    _letra_actual = [64]  # ord('A') - 1, para poder incrementar con clausura

    def _sig_letra():
        _letra_actual[0] += 1
        return chr(_letra_actual[0])

    def _tabla_memoria(titulo, filas, formula_txt, total_label, total_valor, es_deduccion=False):
        """
        Mini-tabla de detalle para un concepto: filas (label, valor) en texto plano,
        una línea de fórmula en cursiva, y una fila de total resaltada. Las
        deducciones se resaltan en rojo y con signo negativo para diferenciarlas
        claramente de los conceptos que SUMAN al bruto.
        """
        color_total = C_DEDUCCION if es_deduccion else C_TOTAL
        signo = "-" if es_deduccion else ""
        data = [[Paragraph(f"<b>{titulo}</b>", ParagraphStyle('MT', fontName="Helvetica-Bold", fontSize=8.5, textColor=C_WHITE)), ""]]
        for label, valor in filas:
            data.append([Paragraph(label, st_memo_lbl), Paragraph(valor, st_memo_val)])
        if formula_txt:
            data.append([Paragraph(formula_txt, st_memo_formula), ""])
        data.append([
            Paragraph(f"<b>{total_label}</b>", ParagraphStyle('MTot', fontName="Helvetica-Bold", fontSize=8.5, textColor=C_WHITE)),
            Paragraph(f"<b>{signo}S/ {total_valor:,.2f}</b>", ParagraphStyle('MTotV', fontName="Helvetica-Bold", fontSize=8.5, textColor=C_WHITE, alignment=TA_RIGHT)),
        ])
        t = Table(data, colWidths=[W * 0.68, W * 0.32])
        n = len(data)
        idx_formula = n - 2 if formula_txt else None
        style = [
            ('BACKGROUND', (0, 0), (-1, 0), C_MEMO_HDR), ('SPAN', (0, 0), (-1, 0)),
            ('BACKGROUND', (0, n - 1), (-1, n - 1), color_total),
            ('ROWBACKGROUNDS', (0, 1), (-1, n - (3 if formula_txt else 2)), [C_WHITE, C_LIGHT]),
            ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 3.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
            ('TOPPADDING', (0, n - 1), (-1, n - 1), 4), ('BOTTOMPADDING', (0, n - 1), (-1, n - 1), 5),
            ('INNERGRID', (0, 1), (-1, n - (3 if formula_txt else 2)), 0.25, C_BORDER),
            ('BOX', (0, 0), (-1, -1), 0.8, C_STEEL),
        ]
        if idx_formula is not None:
            style.append(('SPAN', (0, idx_formula), (-1, idx_formula)))
        t.setStyle(TableStyle(style))
        # KeepTogether evita que la tabla se corte a mitad de fila entre dos páginas
        # (reportlab por defecto sí permite partir una Table larga en el salto de página).
        return KeepTogether([t])

    def _banner_total(label, valor, color, texto_color=C_WHITE, signo=""):
        data = [[
            Paragraph(label, ParagraphStyle('BL', fontName="Helvetica-Bold", fontSize=10, textColor=texto_color, alignment=TA_RIGHT)),
            Paragraph(f"{signo}S/ {valor:,.2f}", ParagraphStyle('BV', fontName="Helvetica-Bold", fontSize=11, textColor=texto_color, alignment=TA_CENTER)),
        ]]
        t = Table(data, colWidths=[W * 0.65, W * 0.35])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), color),
            ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        return t

    # ── A. Cabecera de empresa ───────────────────────────────────────────────
    ruc_line = f"RUC: {empresa_ruc}" if empresa_ruc else ""
    dom_line = empresa_domicilio[:80] if empresa_domicilio else ""
    rep_line = f"Rep. Legal: {empresa_rep}" if empresa_rep else ""
    sub_text = "  |  ".join(p for p in [ruc_line, dom_line, rep_line] if p)

    t_hdr = Table([[Paragraph(empresa_nombre, st_emp)], [Paragraph(sub_text, st_sub)]], colWidths=[W])
    t_hdr.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), C_NAVY),
        ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (0, 0), 8), ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 2),
    ]))
    elements.append(t_hdr)

    # ── B. Título del documento ──────────────────────────────────────────────
    elements.append(Spacer(1, 8))
    elements.append(Paragraph("LIQUIDACIÓN DE BENEFICIOS SOCIALES POR CESE", st_tit))
    elements.append(Paragraph(f"Documento N° LIQ-{liquidacion.id:06d}  ·  Fecha de cese: {liquidacion.fecha_cese_snapshot.strftime('%d/%m/%Y')}", st_per))
    elements.append(Spacer(1, 8))

    # ── C. Datos del trabajador ──────────────────────────────────────────────
    cuspp = getattr(trabajador, 'cuspp', '') or '—'
    info_data = [
        ["TRABAJADOR", Paragraph(trabajador.nombres, st_val_wrap), "DOC. IDENTIDAD", trabajador.num_doc],
        ["CARGO", trabajador.cargo or '—', "FECHA INGRESO", liquidacion.fecha_ingreso_snapshot.strftime('%d/%m/%Y')],
        ["SIST. PENSIÓN", trabajador.sistema_pension or 'NO AFECTO', "CUSPP", cuspp],
        ["FECHA DE CESE", liquidacion.fecha_cese_snapshot.strftime('%d/%m/%Y'), "SUELDO BASE", f"S/ {liquidacion.sueldo_base_snapshot:,.2f}"],
    ]
    WL, WV, WL2, WV2 = 82, 170, 82, 189
    t_info = Table(info_data, colWidths=[WL, WV, WL2, WV2])
    t_info.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), C_LIGHT),
        ('BACKGROUND', (0, 0), (0, -1), C_NAVY), ('BACKGROUND', (2, 0), (2, -1), C_NAVY),
        ('TEXTCOLOR', (0, 0), (0, -1), C_WHITE), ('TEXTCOLOR', (2, 0), (2, -1), C_WHITE),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'), ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'), ('FONTNAME', (3, 0), (3, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 8), ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('BOX', (0, 0), (-1, -1), 0.8, C_STEEL), ('INNERGRID', (0, 0), (-1, -1), 0.3, C_BORDER),
    ]))
    elements.append(t_info)
    elements.append(Spacer(1, 10))

    # ── D. DETALLE DE LIQUIDACIÓN — desglose completo por beneficio ──────────
    elements.append(Paragraph("DETALLE DE LIQUIDACIÓN", st_seccion))

    # D.1 Sueldo proporcional del mes de cese (si aplica)
    if liquidacion.incluye_sueldo_mes_cese and liquidacion.monto_sueldo_proporcional > 0:
        valor_dia_sueldo = liquidacion.sueldo_base_snapshot / 30.0
        filas_sp = [
            ("Días laborados en el mes de cese", f"{liquidacion.dias_laborados_mes_cese} día(s)"),
            ("Valor día (Sueldo Base ÷ 30)", f"S/ {valor_dia_sueldo:,.2f}"),
        ]
        formula_sp = f"{liquidacion.dias_laborados_mes_cese} día(s) × S/ {valor_dia_sueldo:,.2f}/día"
        elements.append(_tabla_memoria(f"{_sig_letra()}. SUELDO PROPORCIONAL DEL MES DE CESE", filas_sp, formula_sp,
                                        "TOTAL SUELDO PROPORCIONAL", liquidacion.monto_sueldo_proporcional))
        elements.append(Spacer(1, 6))

    # D.2 Vacaciones truncas
    valor_dia = liquidacion.sueldo_base_snapshot / 30.0
    _vac_meses_totales = getattr(liquidacion, 'vac_meses_completos', 0) or 0
    _vac_anios, _vac_meses_resto = divmod(_vac_meses_totales, 12)
    _partes_tiempo = [p for p in [
        f"{_vac_anios} año(s)" if _vac_anios else "",
        f"{_vac_meses_resto} mes(es)",
        f"{getattr(liquidacion, 'vac_dias_sueltos', 0):.0f} día(s)",
    ] if p]
    _tiempo_servicio_txt = ", ".join(_partes_tiempo[:-1]) + " y " + _partes_tiempo[-1] if len(_partes_tiempo) > 1 else _partes_tiempo[0]
    filas_vac = [
        ("Periodo de servicio considerado", f"{_fecha(liquidacion.fecha_ingreso_snapshot)} al {_fecha(liquidacion.fecha_cese_snapshot)}"),
        ("Tiempo de servicio", _tiempo_servicio_txt),
        ("Total de días devengados en el periodo (dozavos y treintavos)", f"{getattr(liquidacion, 'vac_devengados', 0):.2f} días"),
        ("(–) Días ya gozados / vendidos anteriormente", f"{getattr(liquidacion, 'vac_consumidos', 0):.2f} días"),
        ("(=) Vacaciones truncas pendientes de pago", f"{liquidacion.dias_vacaciones_pendientes:.2f} días"),
        ("Valor día (Sueldo Base ÷ 30)", f"S/ {valor_dia:,.2f}"),
    ]
    formula_vac = f"{liquidacion.dias_vacaciones_pendientes:.2f} días × S/ {valor_dia:,.2f}/día"
    elements.append(_tabla_memoria(f"{_sig_letra()}. VACACIONES TRUNCAS", filas_vac, formula_vac, "TOTAL VACACIONES TRUNCAS", liquidacion.monto_vacaciones_truncas))
    elements.append(Spacer(1, 6))

    # D.3 Gratificación trunca
    grati_ini = getattr(liquidacion, 'grati_fecha_efectivo_ini', None)
    grati_fin = getattr(liquidacion, 'grati_fecha_efectivo_fin', None)
    grati_base = getattr(liquidacion, 'grati_base_computable', 0) or 0
    grati_factor = getattr(liquidacion, 'grati_factor', 1.0) or 0
    asig_fam_txt = " (incluye Asig. Familiar)" if grati_base > liquidacion.sueldo_base_snapshot else ""
    filas_grati = [
        ("Semestre de gratificación", liquidacion.periodo_grati_ref),
        ("Periodo efectivamente laborado en este semestre", f"{_fecha(grati_ini)} al {_fecha(grati_fin)}"),
        ("Meses calendario COMPLETOS laborados (Ley 27735)", f"{liquidacion.meses_grati} de 6 meses"),
        (f"Base computable{asig_fam_txt}", f"S/ {grati_base:,.2f}"),
        ("Factor de gratificación (régimen laboral)", f"{grati_factor*100:.0f}%"),
    ]
    formula_grati = f"S/ {grati_base:,.2f} × {grati_factor*100:.0f}% × ({liquidacion.meses_grati}/6 meses)"
    elements.append(_tabla_memoria(f"{_sig_letra()}. GRATIFICACIÓN TRUNCA", filas_grati, formula_grati, "TOTAL GRATIFICACIÓN TRUNCA", liquidacion.monto_grati_trunca))
    elements.append(Spacer(1, 6))

    # D.4 Bonificación Extraordinaria — 9 %, o 6.75 % con EPS (Ley 30334). La tasa se
    # deduce de los montos guardados para que el PDF coincida con lo calculado.
    _tasa_bono = (liquidacion.monto_bono_9 / liquidacion.monto_grati_trunca) if liquidacion.monto_grati_trunca else 0.09
    _tasa_txt = "6.75% (EPS)" if abs(_tasa_bono - 0.0675) < 0.001 else "9%"
    filas_bono9 = [
        ("Base: Gratificación Trunca calculada arriba", f"S/ {liquidacion.monto_grati_trunca:,.2f}"),
        ("Tasa (Ley 30334 — Bonificación Extraordinaria)", _tasa_txt),
    ]
    formula_bono9 = f"S/ {liquidacion.monto_grati_trunca:,.2f} × {_tasa_txt.split()[0]}"
    elements.append(_tabla_memoria(f"{_sig_letra()}. BONIFICACIÓN EXTRAORDINARIA", filas_bono9, formula_bono9, "TOTAL BONIFICACIÓN EXTRAORDINARIA", liquidacion.monto_bono_9))
    elements.append(Spacer(1, 6))

    # D.5 CTS truncada
    cts_ini = getattr(liquidacion, 'cts_fecha_efectivo_ini', None)
    cts_fin = getattr(liquidacion, 'cts_fecha_efectivo_fin', None)
    cts_remun = getattr(liquidacion, 'cts_remuneracion_base', 0) or 0
    cts_factor = getattr(liquidacion, 'cts_factor', 1.0) or 0
    cts_dias_sueltos = getattr(liquidacion, 'cts_dias_sueltos', 0) or 0
    grati_ref = getattr(liquidacion, 'grati_referencia_cts', 0) or 0
    grati_ref_periodo = getattr(liquidacion, 'grati_referencia_cts_periodo', '') or '—'
    sexto_grati = round(grati_ref / 6.0, 2)
    fecha_cts_txt = liquidacion.fecha_ultimo_deposito_cts.strftime('%d/%m/%Y') if liquidacion.fecha_ultimo_deposito_cts else "sin depósitos previos registrados"
    filas_cts = [
        ("Periodo semestral CTS", liquidacion.periodo_cts_ref),
        ("Periodo efectivamente laborado en este semestre", f"{_fecha(cts_ini)} al {_fecha(cts_fin)}"),
        ("Tiempo computado (dozavos y treintavos)", f"{liquidacion.meses_cts} mes(es) y {cts_dias_sueltos} día(s) de 6 meses"),
        ("Remuneración computable (Sueldo Base + Asig. Familiar)", f"S/ {cts_remun:,.2f}"),
        (f"1/6 de gratificación de referencia (S/ {grati_ref:,.2f}, periodo {grati_ref_periodo})", f"S/ {sexto_grati:,.2f}"),
        ("Base CTS (Remuneración computable + 1/6 gratificación)", f"S/ {liquidacion.base_cts:,.2f}"),
        ("Factor CTS (régimen laboral)", f"{cts_factor*100:.0f}%"),
        ("Último depósito de CTS considerado", fecha_cts_txt),
    ]
    formula_cts = f"S/ {liquidacion.base_cts:,.2f} × {cts_factor*100:.0f}% × ({liquidacion.meses_cts}/12 + {cts_dias_sueltos}/360)"
    elements.append(_tabla_memoria(f"{_sig_letra()}. CTS TRUNCADA", filas_cts, formula_cts, "TOTAL CTS TRUNCADA", liquidacion.monto_cts_trunca))
    elements.append(Spacer(1, 6))

    # D.6 Bono por Cese (si aplica)
    if getattr(liquidacion, 'monto_bono_cese', 0) > 0:
        filas_bc = [("Monto pactado con el trabajador (código SUNAT 0906)", "Libre acuerdo")]
        elements.append(_tabla_memoria(
            f"{_sig_letra()}. BONO / INCENTIVO POR CESE (EXENTO)", filas_bc,
            "Monto fijo pactado — no afecto a AFP/ONP, 5ta Categoría ni EsSalud",
            "TOTAL BONO POR CESE", liquidacion.monto_bono_cese,
        ))
        elements.append(Spacer(1, 6))

    # ── TOTAL BRUTO ───────────────────────────────────────────────────────────
    elements.append(_banner_total("TOTAL BRUTO", liquidacion.total_bruto, C_STEEL))
    elements.append(Spacer(1, 10))

    # D.7 Deducción AFP/ONP — con la base afecta y desglose de tríada en rojo
    tiene_deducciones = False
    if getattr(liquidacion, 'monto_pension_afp_onp', 0) > 0:
        tiene_deducciones = True
        _sist_pen = getattr(liquidacion, 'sistema_pension_snapshot', None) or 'AFP/ONP'
        base_afp_txt = "Vacaciones truncas" + (" + Sueldo proporcional del mes de cese" if liquidacion.incluye_sueldo_mes_cese else "")
        base_afp_monto = liquidacion.monto_vacaciones_truncas + (liquidacion.monto_sueldo_proporcional if liquidacion.incluye_sueldo_mes_cese else 0)
        filas_pension = [(f"Base afecta: {base_afp_txt}", f"S/ {base_afp_monto:,.2f}")]
        formula_pension = None
        if "AFP" in _sist_pen and (getattr(liquidacion, 'monto_aporte_afp', 0) or getattr(liquidacion, 'monto_prima_afp', 0) or getattr(liquidacion, 'monto_comision_afp', 0)):
            filas_pension += [
                ("Aporte obligatorio (10%)", f"S/ {liquidacion.monto_aporte_afp:,.2f}"),
                ("Prima de seguro", f"S/ {liquidacion.monto_prima_afp:,.2f}"),
                ("Comisión de la administradora", f"S/ {liquidacion.monto_comision_afp:,.2f}"),
            ]
            formula_pension = "Suma de los componentes de la tríada (aporte + prima + comisión)"
        elements.append(_tabla_memoria(
            f"{_sig_letra()}. DEDUCCIÓN {_sist_pen}", filas_pension, formula_pension,
            f"TOTAL {_sist_pen}", liquidacion.monto_pension_afp_onp, es_deduccion=True,
        ))
        elements.append(Spacer(1, 6))

    # D.8 Préstamos / Adelantos pendientes (si aplica)
    if liquidacion.monto_prestamos_pendientes > 0:
        tiene_deducciones = True
        filas_prest = [("Cuotas pendientes de préstamos/adelantos vigentes", f"S/ {liquidacion.monto_prestamos_pendientes:,.2f}")]
        elements.append(_tabla_memoria(
            f"{_sig_letra()}. PRÉSTAMOS / ADELANTOS PENDIENTES", filas_prest, None,
            "TOTAL PRÉSTAMOS/ADELANTOS", liquidacion.monto_prestamos_pendientes, es_deduccion=True,
        ))
        elements.append(Spacer(1, 6))

    # D.9 Retención de 5ta Categoría (si aplica)
    if liquidacion.monto_retencion_5ta > 0:
        tiene_deducciones = True
        base_gravada_5ta = round(liquidacion.monto_vacaciones_truncas + liquidacion.monto_grati_trunca + liquidacion.monto_bono_9, 2)
        filas_5ta = [
            ("Vacaciones truncas (afecta, código SUNAT 0114)", f"S/ {liquidacion.monto_vacaciones_truncas:,.2f}"),
            ("Gratificación trunca (afecta)", f"S/ {liquidacion.monto_grati_trunca:,.2f}"),
            ("Bonificación Extraordinaria (afecta)", f"S/ {liquidacion.monto_bono_9:,.2f}"),
            ("Base gravada total", f"S/ {base_gravada_5ta:,.2f}"),
        ]
        elements.append(_tabla_memoria(
            f"{_sig_letra()}. RETENCIÓN DE 5TA CATEGORÍA", filas_5ta,
            "Proyección anual de renta de 5ta categoría sobre la base gravada (CTS y Bono por Cese son inafectos)",
            "TOTAL RETENCIÓN 5TA", liquidacion.monto_retencion_5ta, es_deduccion=True,
        ))
        elements.append(Spacer(1, 6))

    if tiene_deducciones:
        total_deducciones = round(
            (liquidacion.monto_pension_afp_onp or 0) + (liquidacion.monto_prestamos_pendientes or 0) + (liquidacion.monto_retencion_5ta or 0), 2
        )
        elements.append(_banner_total("TOTAL DEDUCCIONES", total_deducciones, C_DEDUCCION, signo="-"))
        elements.append(Spacer(1, 10))

    # ── E. NETO A PAGAR — conclusión final del documento ─────────────────────
    neto_data = [[
        Paragraph("NETO A PAGAR AL TRABAJADOR", ParagraphStyle('NL', fontName="Helvetica-Bold", fontSize=11, textColor=C_WHITE, alignment=TA_RIGHT)),
        Paragraph(f"S/  {liquidacion.total_neto:,.2f}", ParagraphStyle('NV', fontName="Helvetica-Bold", fontSize=13, textColor=C_NETO_ACC, alignment=TA_CENTER)),
    ]]
    t_neto = Table(neto_data, colWidths=[W * 0.65, W * 0.35])
    t_neto.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), C_NAVY),
        ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(KeepTogether([t_neto]))
    elements.append(Spacer(1, 8))

    # ── F. Aportes a cargo del empleador (informativo, no afecta el neto) ────
    if getattr(liquidacion, 'monto_essalud_vacaciones', 0) > 0:
        apo_data = [[
            Paragraph("<b>APORTES A CARGO DEL EMPLEADOR</b>", ParagraphStyle('AH', fontName="Helvetica-Bold", fontSize=8, textColor=C_WHITE)),
            "",
        ], [
            "EsSalud (sobre vacaciones truncas)",
            Paragraph(f"S/ {liquidacion.monto_essalud_vacaciones:,.2f}", ParagraphStyle('AV', fontName="Helvetica", fontSize=8.5, alignment=TA_RIGHT)),
        ]]
        t_apo = Table(apo_data, colWidths=[W * 0.75, W * 0.25])
        t_apo.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), C_GRAY), ('SPAN', (0, 0), (-1, 0)),
            ('BACKGROUND', (0, 1), (-1, 1), C_LIGHT),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('BOX', (0, 0), (-1, -1), 0.8, C_STEEL), ('INNERGRID', (0, 0), (-1, -1), 0.25, C_BORDER),
        ]))
        elements.append(KeepTogether([t_apo]))
        elements.append(Spacer(1, 6))

    # ── G. Observaciones generales ────────────────────────────────────────────
    obs_lines = []
    if not liquidacion.incluye_sueldo_mes_cese:
        obs_lines.append("El sueldo del mes de cese no se incluye en este documento — se asume pagado por la planilla regular de ese mes.")
    if liquidacion.observaciones:
        obs_lines.append(liquidacion.observaciones)
    if obs_lines:
        st_obs = ParagraphStyle('Obs', fontName="Helvetica", fontSize=7.5, textColor=C_GRAY, leading=10)
        for line in obs_lines:
            elements.append(Paragraph(f"• {line}", st_obs))

    # ── H. Firmas ─────────────────────────────────────────────────────────────
    # Espacio amplio antes de las firmas, para que el empleador y el trabajador
    # tengan suficiente lugar para firmar al momento del pago.
    elements.append(Spacer(1, 60))
    st_firma = ParagraphStyle('Firma', fontName="Helvetica", fontSize=8, alignment=TA_CENTER,
                               textColor=colors.black, leading=13)
    firma_data = [[
        Paragraph(f"___________________________________<br/><b>Empleador:</b> {empresa_nombre}<br/>Sello y Firma", st_firma),
        Paragraph(f"___________________________________<br/><b>Trabajador:</b> {trabajador.nombres}<br/>DNI: {trabajador.num_doc}", st_firma),
    ]]
    t_firma = Table(firma_data, colWidths=[W / 2, W / 2])
    t_firma.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(KeepTogether([t_firma]))

    doc.build(elements)
    buffer.seek(0)
    return buffer
