"""
Módulo de Gratificaciones y CTS.

Gratificaciones: Ley 27735 — dos pagos anuales (Julio y Diciembre).
CTS: D.L. 650 — dos depósitos anuales (Mayo y Noviembre).
"""
import io
import json
import calendar
import datetime

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import (
    Trabajador, ParametroLegal, VariablesMes, DepositoCTS, Empresa,
)
from core.use_cases.calculo_beneficios_sociales import (
    calcular_gratificacion_trabajador,
    calcular_cts_trabajador,
    SEMESTRES_GRATI,
    PERIODOS_CTS,
)

C_NAVY  = colors.HexColor("#0F2744")
C_STEEL = colors.HexColor("#1E4D8C")
C_LIGHT = colors.HexColor("#F0F4F9")
C_GRAY  = colors.HexColor("#64748B")
C_WHITE = colors.white


# ── Helpers período grati ↔ período CTS ────────────────────────────────────────

def _grati_periodo_key(periodo_cts: str, anio_dep: int) -> str:
    """Retorna el periodo_key de la grati que sirve como referencia para este depósito CTS."""
    # NOV-ABR (depósito Mayo) → grati Diciembre año anterior
    # MAY-OCT (depósito Nov)  → grati Julio año mismo
    return f"12-{anio_dep - 1}" if periodo_cts == 'NOV-ABR' else f"07-{anio_dep}"


def _semestre_grati(periodo_cts: str) -> str:
    return 'JUL-DIC' if periodo_cts == 'NOV-ABR' else 'ENE-JUN'


def _anio_grati(periodo_cts: str, anio_dep: int) -> int:
    return anio_dep - 1 if periodo_cts == 'NOV-ABR' else anio_dep


# ── Helpers de exportación ─────────────────────────────────────────────────────

def _excel_beneficios(df: pd.DataFrame, titulo: str) -> io.BytesIO:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, startrow=3, sheet_name='Detalle')
        ws = writer.sheets['Detalle']
        ws['A1'] = titulo
        ws['A2'] = f"Generado: {datetime.date.today().strftime('%d/%m/%Y')}"
    buf.seek(0)
    return buf


def _pdf_beneficios(df: pd.DataFrame, titulo: str, empresa_nombre: str) -> io.BytesIO:
    """PDF genérico para Gratificaciones (landscape letter, columnas simples)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    st_h   = ParagraphStyle('H', fontName='Helvetica-Bold', fontSize=11, textColor=C_NAVY)
    st_sub = ParagraphStyle('S', fontName='Helvetica', fontSize=8)
    st_hdr = ParagraphStyle('Hdr', fontName='Helvetica-Bold', fontSize=7,
                             textColor=C_WHITE, leading=9)
    st_cel = ParagraphStyle('Cel', fontName='Helvetica', fontSize=7, leading=9)

    elems = [
        Paragraph(empresa_nombre.upper(), st_h),
        Paragraph(titulo, st_h),
        Paragraph(f"Fecha: {datetime.date.today().strftime('%d/%m/%Y')}", st_sub),
        Spacer(1, 10),
    ]

    W = 842 - 60  # landscape A4 usable
    # Primer col más ancho para nombre, resto proporcional
    n_cols = len(df.columns)
    rest_w = (W - 150) / max(n_cols - 1, 1)
    col_widths = [150] + [rest_w] * (n_cols - 1)

    header_row = [Paragraph(str(c), st_hdr) for c in df.columns]
    data_rows  = [[Paragraph(str(v) if pd.notna(v) else '', st_cel) for v in row]
                  for _, row in df.iterrows()]

    tbl = Table([header_row] + data_rows, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ('BACKGROUND',     (0, 0), (-1, 0), C_NAVY),
        ('FONTSIZE',       (0, 0), (-1, -1), 7),
        ('GRID',           (0, 0), (-1, -1), 0.4, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [C_WHITE, C_LIGHT]),
        ('VALIGN',         (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING',    (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 3),
    ]))
    elems.append(tbl)
    doc.build(elems)
    buf.seek(0)
    return buf


def _pdf_declaracion_cts(df: pd.DataFrame, titulo: str,
                          empresa_nombre: str, empresa_ruc: str = '',
                          empresa_domicilio: str = '') -> io.BytesIO:
    """PDF de declaración CTS: landscape A4, header corporativo, anchos calibrados."""
    buf = io.BytesIO()
    PAGE_W, PAGE_H = landscape(A4)  # 842 × 595
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    W = PAGE_W - 60  # ≈ 782pt

    st_emp = ParagraphStyle('Emp', fontName='Helvetica-Bold', fontSize=13,
                             textColor=C_WHITE, leading=16)
    st_sub_hdr = ParagraphStyle('SubH', fontName='Helvetica', fontSize=8,
                                 textColor=C_GRAY, leading=11)
    st_tit = ParagraphStyle('Tit', fontName='Helvetica-Bold', fontSize=11,
                             textColor=C_NAVY, alignment=TA_CENTER, spaceAfter=4)
    st_fecha = ParagraphStyle('Fec', fontName='Helvetica', fontSize=8,
                               textColor=C_GRAY, alignment=TA_CENTER)
    st_hdr  = ParagraphStyle('Hdr', fontName='Helvetica-Bold', fontSize=7,
                              textColor=C_WHITE, leading=9)
    st_cel  = ParagraphStyle('Cel', fontName='Helvetica', fontSize=7, leading=9)

    # Header corporativo
    sub_parts = [p for p in [f"RUC: {empresa_ruc}" if empresa_ruc else '',
                              empresa_domicilio] if p]
    hdr_data = [[Paragraph(empresa_nombre.upper(), st_emp)],
                [Paragraph("  |  ".join(sub_parts), st_sub_hdr)]]
    t_hdr = Table(hdr_data, colWidths=[W])
    t_hdr.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_NAVY),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('TOPPADDING',    (0, 0), (0, 0),   8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ('TOPPADDING',    (0, 1), (-1, -1), 2),
    ]))

    elems = [
        t_hdr, Spacer(1, 6),
        Paragraph(titulo, st_tit),
        Paragraph(f"Generado: {datetime.date.today().strftime('%d/%m/%Y')}", st_fecha),
        Spacer(1, 8),
    ]

    # Anchos de columna calibrados (suma ≈ W=782)
    col_names = list(df.columns)
    w_map = {
        'Trabajador':    150,
        'DNI':            58,
        'Sueldo Base':    52,
        'Asig. Fam.':     43,
        'Grati Ref.':     50,
        '1/6 Grati':      43,
        'Base CTS':       52,
        'Factor':         35,
        'Meses':          35,
        'Depósito CTS':   55,
        'Período':       103,
        'Observaciones':  106,
    }
    col_widths = [w_map.get(c, 55) for c in col_names]

    header_row = [Paragraph(c, st_hdr) for c in col_names]
    data_rows  = [[Paragraph(str(v) if pd.notna(v) else '', st_cel) for v in row]
                  for _, row in df.iterrows()]

    tbl = Table([header_row] + data_rows, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ('BACKGROUND',     (0, 0), (-1, 0), C_NAVY),
        ('FONTSIZE',       (0, 0), (-1, -1), 7),
        ('GRID',           (0, 0), (-1, -1), 0.4, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [C_WHITE, C_LIGHT]),
        ('VALIGN',         (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING',    (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 3),
    ]))
    elems.append(tbl)

    # Fila de totales
    if 'Depósito CTS' in col_names:
        total_dep = df['Depósito CTS'].sum()
        st_tot = ParagraphStyle('Tot', fontName='Helvetica-Bold', fontSize=7,
                                 textColor=C_NAVY)
        idx_dep = col_names.index('Depósito CTS')
        tot_row = [Paragraph('', st_tot)] * len(col_names)
        tot_row[0]       = Paragraph('TOTAL', st_tot)
        tot_row[idx_dep] = Paragraph(f"S/ {total_dep:,.2f}", st_tot)
        tot_tbl = Table([tot_row], colWidths=col_widths)
        tot_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), C_LIGHT),
            ('GRID',       (0, 0), (-1, -1), 0.4, colors.grey),
            ('FONTSIZE',   (0, 0), (-1, -1), 7),
        ]))
        elems.append(tot_tbl)

    doc.build(elems)
    buf.seek(0)
    return buf


def generar_pdf_liquidacion_cts_individual(
    filas: list,
    empresa_nombre: str,
    empresa_ruc: str,
    empresa_domicilio: str,
    empresa_rep: str,
    periodo_label: str,
    periodo_key_dep: str,
    db_session,
) -> io.BytesIO:
    """
    PDF multi-página: una hoja de liquidación CTS por trabajador (D.S. 004-97-TR).
    Estilo corporativo idéntico al de boletas de pago.
    """
    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4  # 595 × 842
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    W = PAGE_W - 72  # ≈ 523pt

    # ── Estilos ────────────────────────────────────────────────────────────────
    st_emp  = ParagraphStyle('Emp',  fontName='Helvetica-Bold', fontSize=15,
                              textColor=C_WHITE, leading=18)
    st_sub  = ParagraphStyle('Sub',  fontName='Helvetica',      fontSize=8,
                              textColor=C_GRAY,  leading=11)
    st_tit  = ParagraphStyle('Tit',  fontName='Helvetica-Bold', fontSize=12,
                              textColor=C_NAVY,  alignment=TA_CENTER, spaceAfter=2)
    st_per  = ParagraphStyle('Per',  fontName='Helvetica',      fontSize=10,
                              textColor=C_STEEL, alignment=TA_CENTER, spaceAfter=0)
    st_lbl  = ParagraphStyle('Lbl',  fontName='Helvetica-Bold', fontSize=8,
                              textColor=C_WHITE, leading=11)
    st_val  = ParagraphStyle('Val',  fontName='Helvetica',      fontSize=8,
                              textColor=C_NAVY,  leading=11)
    st_row  = ParagraphStyle('Row',  fontName='Helvetica',      fontSize=8,
                              textColor=C_NAVY,  leading=11)
    st_bold = ParagraphStyle('Bold', fontName='Helvetica-Bold', fontSize=9,
                              textColor=C_NAVY,  leading=12)
    st_mto  = ParagraphStyle('Mto',  fontName='Helvetica-Bold', fontSize=10,
                              textColor=C_STEEL, leading=13, alignment=TA_RIGHT)
    st_foot = ParagraphStyle('Foot', fontName='Helvetica',      fontSize=7,
                              textColor=C_GRAY,  leading=10)

    # ── Mes de depósito legible ────────────────────────────────────────────────
    _meses_es = {1:'Enero',2:'Febrero',3:'Marzo',4:'Abril',5:'Mayo',6:'Junio',
                 7:'Julio',8:'Agosto',9:'Septiembre',10:'Octubre',
                 11:'Noviembre',12:'Diciembre'}
    try:
        _mes_num, _anio_num = int(periodo_key_dep[:2]), int(periodo_key_dep[3:])
        fecha_limite_str = f"15 de {_meses_es.get(_mes_num,'?')} de {_anio_num}"
    except Exception:
        fecha_limite_str = periodo_key_dep

    all_elements = []

    for i, f in enumerate(filas):
        if not f.get('_aplica') or f.get('_monto_cts', 0) <= 0:
            continue

        t_id = f['_trabajador_id']
        t = db_session.query(Trabajador).get(t_id)
        if not t:
            continue

        # Datos trabajador
        nombre_completo = t.nombres
        ap_pat = getattr(t, 'apellido_paterno', '') or ''
        ap_mat = getattr(t, 'apellido_materno', '') or ''
        if ap_pat or ap_mat:
            nombre_completo = f"{ap_pat} {ap_mat}, {t.nombres}".strip(', ')
        tipo_doc_label = {'01': 'DNI', '04': 'CE'}.get(
            getattr(t, 'tipo_documento', '01') or '01', 'Doc.')
        fecha_ing_str = (t.fecha_ingreso.strftime('%d/%m/%Y')
                         if t.fecha_ingreso else '—')
        cargo_str    = getattr(t, 'cargo', '') or '—'
        regimen_str  = f.get('_regimen_trab', '') or '—'
        pension_str  = getattr(t, 'sistema_pension', '') or '—'

        # Banco/cuenta CTS desde DepositoCTS más reciente
        dep_banco = '—'
        dep_cuenta = '—'
        try:
            dep_rec = (
                db_session.query(DepositoCTS)
                .filter_by(empresa_id=t.empresa_id, trabajador_id=t_id)
                .order_by(DepositoCTS.fecha_registro.desc())
                .first()
            )
            if dep_rec:
                dep_banco  = dep_rec.banco_cts  or '—'
                dep_cuenta = dep_rec.cuenta_cts or '—'
        except Exception:
            pass

        elems = []

        # ── A. Header corporativo ──────────────────────────────────────────────
        sub_parts = [p for p in [
            f"RUC: {empresa_ruc}" if empresa_ruc else '',
            empresa_domicilio,
            f"Rep. Legal: {empresa_rep}" if empresa_rep else '',
        ] if p]
        hdr_data = [[Paragraph(empresa_nombre.upper(), st_emp)],
                    [Paragraph("  |  ".join(sub_parts), st_sub)]]
        t_hdr = Table(hdr_data, colWidths=[W])
        t_hdr.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), C_NAVY),
            ('LEFTPADDING',   (0, 0), (-1, -1), 10),
            ('TOPPADDING',    (0, 0), (0, 0),   8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('TOPPADDING',    (0, 1), (-1, -1), 2),
        ]))
        elems += [Spacer(1, 4), t_hdr, Spacer(1, 6)]

        # ── B. Título ──────────────────────────────────────────────────────────
        elems += [
            Paragraph("HOJA DE LIQUIDACIÓN DE CTS", st_tit),
            Paragraph(
                f"Período: {periodo_label}  —  Fecha límite de depósito: {fecha_limite_str}",
                st_per,
            ),
            Spacer(1, 8),
        ]

        # ── C. Datos del trabajador ────────────────────────────────────────────
        W2 = W / 2
        W_lbl = 120
        W_val = W2 - W_lbl
        trab_data = [
            [Paragraph('Apellidos y Nombres', st_lbl),
             Paragraph(nombre_completo, st_val),
             Paragraph(tipo_doc_label, st_lbl),
             Paragraph(t.num_doc, st_val)],
            [Paragraph('Cargo', st_lbl),
             Paragraph(cargo_str, st_val),
             Paragraph('Fecha de Ingreso', st_lbl),
             Paragraph(fecha_ing_str, st_val)],
            [Paragraph('Régimen Laboral', st_lbl),
             Paragraph(regimen_str, st_val),
             Paragraph('Sistema Pensionario', st_lbl),
             Paragraph(pension_str, st_val)],
        ]
        t_trab = Table(trab_data, colWidths=[W_lbl, W_val, W_lbl, W_val])
        t_trab.setStyle(TableStyle([
            ('BACKGROUND',  (0, 0), (0, -1), C_NAVY),
            ('BACKGROUND',  (2, 0), (2, -1), C_NAVY),
            ('BACKGROUND',  (1, 0), (1, -1), C_LIGHT),
            ('BACKGROUND',  (3, 0), (3, -1), C_LIGHT),
            ('GRID',        (0, 0), (-1, -1), 0.8, C_STEEL),
            ('FONTSIZE',    (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING',  (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING',(0,0), (-1, -1), 4),
            ('VALIGN',      (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elems += [t_trab, Spacer(1, 10)]

        # ── D. Desglose CTS ────────────────────────────────────────────────────
        grati_ref_val  = f.get('_grati_val', 0.0)
        sexto_grati    = f.get('_sexto_grati', 0.0)
        base_cts       = f.get('_base_cts', 0.0)
        meses_comp     = f.get('_meses', 0)
        factor_cts     = f.get('_factor', 0.0)
        monto_cts      = f.get('_monto_cts', 0.0)
        periodo_lab    = f.get('Período', '')

        W_lbl2 = 310
        W_val2 = W - W_lbl2

        def _fila(label, valor, bold=False, fondo=None):
            _s_l = st_bold if bold else st_row
            _s_v = ParagraphStyle('v', fontName='Helvetica-Bold' if bold else 'Helvetica',
                                   fontSize=9 if bold else 8,
                                   textColor=C_NAVY, alignment=TA_RIGHT, leading=12)
            return [Paragraph(label, _s_l), Paragraph(str(valor), _s_v)]

        sueldo_base = t.sueldo_base or 0.0
        rmv_asig    = f.get('Asig. Fam.', 0.0)
        if not isinstance(rmv_asig, (int, float)):
            try:
                rmv_asig = float(rmv_asig)
            except Exception:
                rmv_asig = 0.0

        desglose_data = [
            _fila('Remuneración básica mensual', f"S/  {sueldo_base:,.2f}"),
            _fila('Asignación familiar', f"S/  {rmv_asig:,.2f}"),
            _fila(f'Gratificación de referencia ({_semestre_grati(_get_periodo_cts_from_filas(f))} {_anio_grati(_get_periodo_cts_from_filas(f), _anio_from_periodo_key(periodo_key_dep))})',
                  f"S/  {grati_ref_val:,.2f}"),
            _fila('  → 1/6 de gratificación (base CTS)', f"S/  {sexto_grati:,.2f}"),
            _fila('BASE COMPUTABLE', f"S/  {base_cts:,.2f}", bold=True),
            _fila('Período computable', periodo_lab),
            _fila('Meses computados', str(meses_comp)),
            _fila(f'Factor ({regimen_str})', f"{factor_cts*100:.0f}%"),
            _fila('MONTO A DEPOSITAR', f"S/  {monto_cts:,.2f}", bold=True),
        ]

        t_des = Table(desglose_data, colWidths=[W_lbl2, W_val2])
        row_styles = []
        for idx, (_, v) in enumerate(desglose_data):
            bg = C_LIGHT if idx % 2 == 0 else C_WHITE
            row_styles.append(('BACKGROUND', (0, idx), (-1, idx), bg))
        # Fila base computable y monto a depositar en C_LIGHT con borde
        for idx in [4, 8]:
            row_styles.append(('BACKGROUND', (0, idx), (-1, idx), colors.HexColor("#D6E4F7")))
            row_styles.append(('LINEABOVE',  (0, idx), (-1, idx), 0.8, C_STEEL))
            row_styles.append(('LINEBELOW',  (0, idx), (-1, idx), 0.8, C_STEEL))

        t_des.setStyle(TableStyle([
            ('GRID',         (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
            ('FONTSIZE',     (0, 0), (-1, -1), 8),
            ('LEFTPADDING',  (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING',   (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
            ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ] + row_styles))
        elems += [t_des, Spacer(1, 10)]

        # ── E. Datos bancarios ─────────────────────────────────────────────────
        banco_data = [[
            Paragraph('Entidad Financiera', st_lbl),
            Paragraph(dep_banco, st_val),
            Paragraph('N° Cuenta CTS', st_lbl),
            Paragraph(dep_cuenta, st_val),
        ]]
        t_banco = Table(banco_data, colWidths=[W_lbl, W_val, W_lbl, W_val])
        t_banco.setStyle(TableStyle([
            ('BACKGROUND',   (0, 0), (0, -1), C_NAVY),
            ('BACKGROUND',   (2, 0), (2, -1), C_NAVY),
            ('BACKGROUND',   (1, 0), (1, -1), C_LIGHT),
            ('BACKGROUND',   (3, 0), (3, -1), C_LIGHT),
            ('GRID',         (0, 0), (-1, -1), 0.8, C_STEEL),
            ('FONTSIZE',     (0, 0), (-1, -1), 8),
            ('LEFTPADDING',  (0, 0), (-1, -1), 6),
            ('TOPPADDING',   (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 5),
            ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elems += [t_banco, Spacer(1, 24)]

        # ── F. Footer firmas ───────────────────────────────────────────────────
        firma_data = [[
            Paragraph(
                f"Generado: {datetime.date.today().strftime('%d/%m/%Y')}",
                st_foot,
            ),
            Paragraph(
                "___________________________<br/>Firma y Sello del Empleador",
                ParagraphStyle('FirmE', fontName='Helvetica', fontSize=7,
                                textColor=C_GRAY, alignment=TA_RIGHT, leading=10),
            ),
        ]]
        t_firma = Table(firma_data, colWidths=[W * 0.5, W * 0.5])
        t_firma.setStyle(TableStyle([
            ('VALIGN',  (0, 0), (-1, -1), 'BOTTOM'),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
        ]))
        elems.append(t_firma)

        all_elements += elems
        # PageBreak entre trabajadores (no al final)
        all_elements.append(PageBreak())

    # Eliminar último PageBreak
    if all_elements and isinstance(all_elements[-1], PageBreak):
        all_elements.pop()

    if not all_elements:
        # PDF vacío con mensaje
        all_elements = [Paragraph("No hay liquidaciones CTS para mostrar.",
                                   ParagraphStyle('msg', fontName='Helvetica', fontSize=10))]

    doc.build(all_elements)
    buf.seek(0)
    return buf


def _get_periodo_cts_from_filas(f: dict) -> str:
    """Extrae el período CTS del campo de período guardado en sesión."""
    return f.get('_periodo_cts', 'NOV-ABR')


def _anio_from_periodo_key(periodo_key_dep: str) -> int:
    try:
        return int(periodo_key_dep[3:])
    except Exception:
        return datetime.date.today().year


# ── Tab 1: Gratificaciones ─────────────────────────────────────────────────────

def _render_tab_gratificaciones(empresa_id: int, empresa_nombre: str,
                                 regimen_empresa: str, fecha_acogimiento):
    st.markdown("#### Cálculo de Gratificaciones Legales")
    st.info(
        "Ley 27735 — Se paga 1 sueldo íntegro en Julio y Diciembre. "
        "Para MYPE Pequeña Empresa: 50%. Micro Empresa: no aplica. "
        "Incluye Bono Extraordinario 9% (Ley 29351)."
    )

    col1, col2, col3 = st.columns(3)
    semestre  = col1.selectbox("Semestre", list(SEMESTRES_GRATI.keys()),
                                format_func=lambda s: SEMESTRES_GRATI[s]['label'],
                                key="grati_semestre")
    anio      = col2.selectbox("Año", [2024, 2025, 2026, 2027], index=1, key="grati_anio")
    mes_pago  = SEMESTRES_GRATI[semestre]['mes_pago']
    periodo_pago = f"{mes_pago:02d}-{anio}"
    col3.metric("Período de Pago", f"{'Julio' if mes_pago == 7 else 'Diciembre'} {anio}")

    if st.button("🧮 Calcular Gratificaciones", type="primary",
                  use_container_width=True, key="btn_calc_grati"):
        db = SessionLocal()
        try:
            empresa_obj    = db.query(Empresa).filter_by(id=empresa_id).first()
            factor_override = getattr(empresa_obj, 'factor_proyeccion_grati', None)

            param = (
                db.query(ParametroLegal)
                .filter_by(empresa_id=empresa_id)
                .order_by(ParametroLegal.periodo_key.desc())
                .first()
            )
            rmv = param.rmv if param else 1025.0

            trabajadores = (
                db.query(Trabajador)
                .filter(
                    Trabajador.empresa_id == empresa_id,
                    Trabajador.situacion == 'ACTIVO',
                    Trabajador.tipo_contrato != 'LOCADOR',
                )
                .order_by(Trabajador.nombres)
                .all()
            )
        finally:
            db.close()

        if not trabajadores:
            st.warning("No hay trabajadores de planilla activos.")
            return

        filas = []
        for t in trabajadores:
            r = calcular_gratificacion_trabajador(
                trabajador=t,
                semestre=semestre,
                anio=anio,
                rmv=rmv,
                regimen_empresa=regimen_empresa,
                fecha_acogimiento=fecha_acogimiento,
                factor_override=factor_override,
            )
            filas.append({
                'Trabajador':      t.nombres,
                'DNI':             t.num_doc,
                'Sueldo Base':     t.sueldo_base,
                'Asig. Fam.':      round(r['monto_asig_fam'], 2),
                'Base Computable': r['base_computable'],
                'Factor':          f"{r['factor_grati']*100:.0f}%",
                'Meses':           r['meses_computados'],
                'Gratificación':   r['monto_grati'],
                'Bono 9%':         r['bono_9pct'],
                'TOTAL':           r['total'],
                'Aplica':          'Sí' if r['aplica'] else 'No',
                'Observaciones':   r['observaciones'],
                '_concepto_key':   r['concepto_json_key'],
                '_trabajador_id':  t.id,
                '_monto_grati':    r['monto_grati'],
                '_aplica':         r['aplica'],
            })

        df_show = pd.DataFrame([{k: v for k, v in f.items() if not k.startswith('_')}
                                  for f in filas])
        st.session_state['_grati_filas']       = filas
        st.session_state['_grati_periodo_pago'] = periodo_pago
        st.session_state['_grati_semestre']    = semestre
        st.session_state['_grati_anio']        = anio

        total_grati = sum(f['_monto_grati'] for f in filas if f['_aplica'])
        total_bono  = sum(f['Bono 9%']      for f in filas if f['_aplica'])
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Gratificaciones", f"S/ {total_grati:,.2f}")
        m2.metric("Total Bono 9%",         f"S/ {total_bono:,.2f}")
        m3.metric("Costo Total Empresa",   f"S/ {total_grati + total_bono:,.2f}")

        st.dataframe(df_show, use_container_width=True, hide_index=True)

    # ── Acciones (solo si ya se calculó) ──────────────────────────────────────
    filas = st.session_state.get('_grati_filas')
    if not filas:
        return

    periodo_pago_saved = st.session_state.get('_grati_periodo_pago', periodo_pago)
    df_show_saved = pd.DataFrame([{k: v for k, v in f.items() if not k.startswith('_')}
                                   for f in filas])

    st.markdown("---")
    col_a, col_b, col_c = st.columns(3)

    buf_xl = _excel_beneficios(df_show_saved,
                                f"Gratificaciones {SEMESTRES_GRATI[st.session_state.get('_grati_semestre','ENE-JUN')]['label']} {st.session_state.get('_grati_anio', anio)}")
    col_a.download_button("📊 Descargar Excel", data=buf_xl,
                           file_name=f"Gratificaciones_{periodo_pago_saved}.xlsx",
                           key="dl_grati_xl", use_container_width=True)

    buf_pdf = _pdf_beneficios(df_show_saved,
                               f"Gratificaciones — Período {periodo_pago_saved}",
                               empresa_nombre)
    col_b.download_button("📄 Descargar PDF", data=buf_pdf,
                           file_name=f"Gratificaciones_{periodo_pago_saved}.pdf",
                           mime="application/pdf", key="dl_grati_pdf", use_container_width=True)

    if col_c.button("💾 Registrar en Planilla", type="primary",
                     use_container_width=True, key="btn_reg_grati",
                     help=f"Guarda los montos en las variables del período {periodo_pago_saved}"):
        db2 = SessionLocal()
        try:
            registrados = 0
            for f in filas:
                if not f['_aplica'] or f['_monto_grati'] <= 0:
                    continue
                v = db2.query(VariablesMes).filter_by(
                    empresa_id=empresa_id,
                    trabajador_id=f['_trabajador_id'],
                    periodo_key=periodo_pago_saved,
                ).first()
                if not v:
                    v = VariablesMes(
                        empresa_id=empresa_id,
                        trabajador_id=f['_trabajador_id'],
                        periodo_key=periodo_pago_saved,
                    )
                    db2.add(v)
                    db2.flush()
                cj = json.loads(v.conceptos_json or '{}')
                cj[f['_concepto_key']] = round(f['_monto_grati'], 2)
                v.conceptos_json = json.dumps(cj)
                registrados += 1
            db2.commit()
            st.success(
                f"✅ Gratificaciones registradas para {registrados} trabajador(es) "
                f"en el período **{periodo_pago_saved}**. "
                f"El Bono 9% se calculará automáticamente en Cálculo de Planilla."
            )
            st.session_state['_grati_filas'] = None
        except Exception as e:
            db2.rollback()
            st.error(f"Error al registrar: {e}")
        finally:
            db2.close()


# ── Tab 2: CTS ────────────────────────────────────────────────────────────────

def _render_tab_cts(empresa_id: int, empresa_nombre: str,
                    regimen_empresa: str, fecha_acogimiento):
    st.markdown("#### Cálculo de CTS — Compensación por Tiempo de Servicios")
    st.info(
        "D.L. 650 — Depósito en Mayo (cubre Nov–Abr) y Noviembre (cubre May–Oct). "
        "Base: Sueldo + Asig.Fam + 1/6 de la gratificación del semestre. "
        "Pequeña Empresa: 50%. Micro Empresa: no aplica. No afecta 5ta categoría."
    )

    col1, col2 = st.columns(2)
    periodo_cts = col1.selectbox("Período CTS", list(PERIODOS_CTS.keys()),
                                  format_func=lambda p: PERIODOS_CTS[p]['label'],
                                  key="cts_periodo")
    anio_dep    = col2.selectbox("Año de depósito", [2024, 2025, 2026, 2027],
                                  index=1, key="cts_anio")
    mes_dep     = PERIODOS_CTS[periodo_cts]['mes_deposito']
    periodo_key_dep = f"{mes_dep:02d}-{anio_dep}"

    st.caption(
        f"Período cubierto: {PERIODOS_CTS[periodo_cts]['label']} — "
        f"Depósito límite: {'15 de Mayo' if mes_dep == 5 else '15 de Noviembre'} {anio_dep}"
    )

    # ── Info sobre detección automática de gratificación ──────────────────────
    _gk = _grati_periodo_key(periodo_cts, anio_dep)
    _sem_label = SEMESTRES_GRATI[_semestre_grati(periodo_cts)]['label']
    _anio_g    = _anio_grati(periodo_cts, anio_dep)
    st.info(
        f"**Gratificación de referencia (1/6 grati):** se obtiene automáticamente "
        f"del período **{_gk}** ({_sem_label} {_anio_g}) registrado en Cálculo de Planilla. "
        f"Si no está disponible, se calcula de forma estimada con el régimen actual del trabajador. "
        f"La columna **'Fuente'** indica el origen: *planilla* o *estimado*."
    )

    if st.button("🧮 Calcular CTS", type="primary",
                  use_container_width=True, key="btn_calc_cts"):
        db = SessionLocal()
        try:
            empresa_obj    = db.query(Empresa).filter_by(id=empresa_id).first()
            factor_override = getattr(empresa_obj, 'factor_proyeccion_grati', None)

            param = (
                db.query(ParametroLegal)
                .filter_by(empresa_id=empresa_id)
                .order_by(ParametroLegal.periodo_key.desc())
                .first()
            )
            rmv = param.rmv if param else 1025.0

            trabajadores = (
                db.query(Trabajador)
                .filter(
                    Trabajador.empresa_id == empresa_id,
                    Trabajador.situacion == 'ACTIVO',
                    Trabajador.tipo_contrato != 'LOCADOR',
                )
                .order_by(Trabajador.nombres)
                .all()
            )

            grati_pk = _grati_periodo_key(periodo_cts, anio_dep)
            sem_grati = _semestre_grati(periodo_cts)
            anio_g    = _anio_grati(periodo_cts, anio_dep)

            filas = []
            for t in trabajadores:
                # ── 1. Intentar leer grati registrada en VariablesMes ──────────
                v_grati = db.query(VariablesMes).filter_by(
                    empresa_id=empresa_id,
                    trabajador_id=t.id,
                    periodo_key=grati_pk,
                ).first()
                grati_val   = 0.0
                grati_fuente = "sin dato"
                if v_grati:
                    cj = json.loads(v_grati.conceptos_json or '{}')
                    grati_val = float(cj.get("GRATIFICACION (JUL/DIC)", 0.0))
                    if grati_val > 0:
                        grati_fuente = "planilla"

                # ── 2. Si no hay, calcular grati teórica como estimado ─────────
                if grati_val == 0.0:
                    rg = calcular_gratificacion_trabajador(
                        trabajador=t,
                        semestre=sem_grati,
                        anio=anio_g,
                        rmv=rmv,
                        regimen_empresa=regimen_empresa,
                        fecha_acogimiento=fecha_acogimiento,
                        factor_override=factor_override,
                    )
                    grati_val    = rg['monto_grati']
                    grati_fuente = "estimado"

                r = calcular_cts_trabajador(
                    trabajador=t,
                    periodo=periodo_cts,
                    anio_deposito=anio_dep,
                    rmv=rmv,
                    grati_semestral=grati_val,
                    regimen_empresa=regimen_empresa,
                    fecha_acogimiento=fecha_acogimiento,
                )
                filas.append({
                    'Trabajador':    t.nombres,
                    'DNI':           t.num_doc,
                    'Sueldo Base':   t.sueldo_base,
                    'Asig. Fam.':    round(r['monto_asig_fam'], 2),
                    'Grati Ref.':    round(grati_val, 2),
                    'Fuente':        grati_fuente,
                    '1/6 Grati':     r['sexto_grati'],
                    'Base CTS':      r['base_cts'],
                    'Factor':        f"{r['factor_cts']*100:.0f}%",
                    'Meses':         r['meses_computados'],
                    'Depósito CTS':  r['monto_cts'],
                    'Período':       r['periodo_label'],
                    'Observaciones': r['observaciones'],
                    '_trabajador_id': t.id,
                    '_monto_cts':     r['monto_cts'],
                    '_base_cts':      r['base_cts'],
                    '_sexto_grati':   r['sexto_grati'],
                    '_meses':         r['meses_computados'],
                    '_factor':        r['factor_cts'],
                    '_aplica':        r['aplica'],
                    '_grati_val':     grati_val,
                    '_grati_fuente':  grati_fuente,
                    '_regimen_trab':  r.get('regimen_trab', regimen_empresa),
                    '_periodo_cts':   periodo_cts,
                })
        finally:
            db.close()

        if not filas:
            st.warning("No hay trabajadores de planilla activos.")
            return

        df_show = pd.DataFrame([{k: v for k, v in f.items() if not k.startswith('_')}
                                  for f in filas])
        st.session_state['_cts_filas']           = filas
        st.session_state['_cts_periodo_key_dep'] = periodo_key_dep
        st.session_state['_cts_periodo_cts']     = periodo_cts
        st.session_state['_cts_anio_dep']        = anio_dep

        total_cts = sum(f['_monto_cts'] for f in filas if f['_aplica'])
        n_aplica  = sum(1 for f in filas if f['_aplica'])
        n_estim   = sum(1 for f in filas if f['_grati_fuente'] == 'estimado')
        m1, m2, m3 = st.columns(3)
        m1.metric("Total a Depositar", f"S/ {total_cts:,.2f}")
        m2.metric("N° Trabajadores",   str(n_aplica))
        m3.metric("Con grati estimada", str(n_estim),
                  help="Trabajadores cuya gratificación fue calculada teóricamente por no estar registrada en planilla")

        if n_estim > 0:
            st.warning(
                f"⚠️ {n_estim} trabajador(es) tienen gratificación **estimada** "
                f"(no registrada en el período {grati_pk}). "
                f"Para mayor precisión, calcula y registra las gratificaciones en la pestaña 🎁 Gratificaciones primero."
            )

        st.dataframe(df_show, use_container_width=True, hide_index=True)

    # ── Acciones ──────────────────────────────────────────────────────────────
    filas = st.session_state.get('_cts_filas')
    if not filas:
        return

    periodo_key_dep_saved = st.session_state.get('_cts_periodo_key_dep', periodo_key_dep)
    periodo_cts_saved     = st.session_state.get('_cts_periodo_cts', periodo_cts)
    anio_dep_saved        = st.session_state.get('_cts_anio_dep', anio_dep)

    # DataFrame para pantalla (todas las columnas)
    df_show_saved = pd.DataFrame([{k: v for k, v in f.items() if not k.startswith('_')}
                                   for f in filas])

    # DataFrame solo para PDF declaración: solo trabajadores aplicables, sin columnas internas
    filas_aplica = [f for f in filas if f['_aplica'] and f['_monto_cts'] > 0]
    df_cts_pdf = pd.DataFrame([{
        k: v for k, v in f.items()
        if not k.startswith('_') and k not in ('Fuente',)
    } for f in filas_aplica])

    st.markdown("---")
    empresa_ruc = st.session_state.get('empresa_activa_ruc', '')
    empresa_dom = st.session_state.get('empresa_activa_domicilio', '')
    empresa_rep = st.session_state.get('empresa_activa_representante', '')

    col_a, col_b, col_c, col_d = st.columns(4)

    buf_xl = _excel_beneficios(df_show_saved,
                                f"CTS {PERIODOS_CTS[periodo_cts_saved]['label']} {anio_dep_saved}")
    col_a.download_button("📊 Excel Banco", data=buf_xl,
                           file_name=f"CTS_{periodo_key_dep_saved}.xlsx",
                           key="dl_cts_xl", use_container_width=True)

    if not df_cts_pdf.empty:
        buf_pdf = _pdf_declaracion_cts(
            df_cts_pdf,
            f"Declaración Depósito CTS — {periodo_key_dep_saved}",
            empresa_nombre, empresa_ruc, empresa_dom,
        )
    else:
        buf_pdf = _pdf_beneficios(df_show_saved,
                                   f"Depósito CTS — {periodo_key_dep_saved}",
                                   empresa_nombre)
    col_b.download_button("📄 PDF Declaración", data=buf_pdf,
                           file_name=f"CTS_{periodo_key_dep_saved}.pdf",
                           mime="application/pdf", key="dl_cts_pdf", use_container_width=True)

    # PDF de liquidaciones individuales
    if filas_aplica:
        db_liq = SessionLocal()
        try:
            if periodo_cts_saved == 'NOV-ABR':
                _per_lab = f"NOV {anio_dep_saved - 1} – ABR {anio_dep_saved}"
            else:
                _per_lab = f"MAY {anio_dep_saved} – OCT {anio_dep_saved}"
            buf_liq = generar_pdf_liquidacion_cts_individual(
                filas=filas_aplica,
                empresa_nombre=empresa_nombre,
                empresa_ruc=empresa_ruc,
                empresa_domicilio=empresa_dom,
                empresa_rep=empresa_rep,
                periodo_label=_per_lab,
                periodo_key_dep=periodo_key_dep_saved,
                db_session=db_liq,
            )
        finally:
            db_liq.close()
        col_c.download_button("📋 Liquidaciones Ind.", data=buf_liq,
                               file_name=f"Liquidaciones_CTS_{periodo_key_dep_saved}.pdf",
                               mime="application/pdf", key="dl_cts_liq",
                               use_container_width=True)
    else:
        col_c.info("Sin liquidaciones aplicables")

    if col_d.button("💾 Registrar Depósitos", type="primary",
                     use_container_width=True, key="btn_reg_cts",
                     help="Guarda los depósitos en la tabla histórica de CTS"):
        db3 = SessionLocal()
        try:
            registrados = 0
            if periodo_cts_saved == 'NOV-ABR':
                periodo_label_str = f"NOV {anio_dep_saved - 1} – ABR {anio_dep_saved}"
            else:
                periodo_label_str = f"MAY {anio_dep_saved} – OCT {anio_dep_saved}"

            for f in filas:
                if not f['_aplica'] or f['_monto_cts'] <= 0:
                    continue
                dep = db3.query(DepositoCTS).filter_by(
                    empresa_id=empresa_id,
                    trabajador_id=f['_trabajador_id'],
                    periodo_key_deposito=periodo_key_dep_saved,
                ).first()
                if dep:
                    dep.base_computable  = f['_base_cts']
                    dep.sexto_grati      = f['_sexto_grati']
                    dep.meses_computados = f['_meses']
                    dep.factor           = f['_factor']
                    dep.monto            = f['_monto_cts']
                else:
                    dep = DepositoCTS(
                        empresa_id=empresa_id,
                        trabajador_id=f['_trabajador_id'],
                        periodo_label=periodo_label_str,
                        periodo_key_deposito=periodo_key_dep_saved,
                        base_computable=f['_base_cts'],
                        sexto_grati=f['_sexto_grati'],
                        meses_computados=f['_meses'],
                        factor=f['_factor'],
                        monto=f['_monto_cts'],
                        estado='PENDIENTE',
                    )
                    db3.add(dep)
                registrados += 1
            db3.commit()
            st.success(
                f"✅ CTS registrada para {registrados} trabajador(es). "
                f"Período: **{periodo_label_str}** → depósito en **{periodo_key_dep_saved}**."
            )
            st.session_state['_cts_filas'] = None
        except Exception as e:
            db3.rollback()
            st.error(f"Error al registrar: {e}")
        finally:
            db3.close()

    # ── Historial de depósitos registrados ────────────────────────────────────
    st.markdown("---")
    st.markdown("##### Historial de Depósitos CTS Registrados")
    db4 = SessionLocal()
    try:
        deps = (
            db4.query(DepositoCTS)
            .filter_by(empresa_id=empresa_id)
            .order_by(DepositoCTS.periodo_key_deposito.desc())
            .all()
        )
        if not deps:
            st.info("Sin depósitos registrados aún.")
        else:
            hist = pd.DataFrame([{
                'Período':       d.periodo_label or d.periodo_key_deposito,
                'Mes Depósito':  d.periodo_key_deposito,
                'Trabajador':    d.trabajador.nombres,
                'DNI':           d.trabajador.num_doc,
                'Base CTS':      d.base_computable,
                '1/6 Grati':     d.sexto_grati,
                'Meses':         d.meses_computados,
                'Factor':        f"{d.factor*100:.0f}%",
                'Monto':         d.monto,
                'Estado':        d.estado,
                'Fec. Depósito': d.fecha_deposito.strftime('%d/%m/%Y') if d.fecha_deposito else '—',
            } for d in deps])
            st.dataframe(hist, use_container_width=True, hide_index=True)

            st.markdown("**Marcar depósito como realizado:**")
            opciones_pend = list({d.periodo_key_deposito for d in deps if d.estado == 'PENDIENTE'})
            if opciones_pend:
                per_marcar     = st.selectbox("Período a confirmar",
                                              sorted(opciones_pend, reverse=True),
                                              key="cts_per_marcar")
                fecha_dep_conf = st.date_input("Fecha de depósito efectivo",
                                               value=datetime.date.today(),
                                               key="cts_fecha_dep")
                if st.button("✅ Confirmar Depósito", key="btn_conf_cts"):
                    for d in deps:
                        if d.periodo_key_deposito == per_marcar and d.estado == 'PENDIENTE':
                            d.estado = 'DEPOSITADO'
                            d.fecha_deposito = fecha_dep_conf
                    db4.commit()
                    st.success(f"Depósito de {per_marcar} marcado como DEPOSITADO.")
                    st.rerun()
    finally:
        db4.close()


# ── Render principal ───────────────────────────────────────────────────────────

def render():
    empresa_id        = st.session_state.get('empresa_activa_id')
    empresa_nombre    = st.session_state.get('empresa_activa_nombre', '')
    regimen_empresa   = st.session_state.get('empresa_activa_regimen', 'Régimen General')
    fecha_acogimiento = st.session_state.get('empresa_acogimiento', None)

    if not empresa_id:
        st.warning("⚠️ Seleccione una empresa para continuar.")
        return

    st.title("🏦 Gratificaciones y CTS")
    st.markdown(f"**Empresa:** {empresa_nombre} | **Régimen:** {regimen_empresa}")
    st.markdown("---")

    tab_grati, tab_cts = st.tabs(["🎁 Gratificaciones", "🏦 CTS"])

    with tab_grati:
        _render_tab_gratificaciones(empresa_id, empresa_nombre,
                                     regimen_empresa, fecha_acogimiento)

    with tab_cts:
        _render_tab_cts(empresa_id, empresa_nombre,
                        regimen_empresa, fecha_acogimiento)
