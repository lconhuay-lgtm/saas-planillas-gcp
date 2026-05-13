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
from reportlab.lib.pagesizes import landscape, letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

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

C_NAVY = colors.HexColor("#0F2744")


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
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(letter),
                            leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    st_h   = ParagraphStyle('H', fontName='Helvetica-Bold', fontSize=11, textColor=C_NAVY)
    st_sub = ParagraphStyle('S', fontName='Helvetica', fontSize=8)

    elems = [
        Paragraph(empresa_nombre.upper(), st_h),
        Paragraph(titulo, st_h),
        Paragraph(f"Fecha: {datetime.date.today().strftime('%d/%m/%Y')}", st_sub),
        Spacer(1, 10),
    ]

    col_widths = [120] + [55] * (len(df.columns) - 1)
    data = [list(df.columns)] + df.values.tolist()
    tbl  = Table(data, colWidths=col_widths)
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), C_NAVY),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
        ('FONTSIZE',   (0, 0), (-1, -1), 7),
        ('ALIGN',      (1, 0), (-1, -1), 'CENTER'),
        ('GRID',       (0, 0), (-1, -1), 0.4, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F0F4F9')]),
    ]))
    elems.append(tbl)
    doc.build(elems)
    buf.seek(0)
    return buf


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
            empresa_obj = db.query(Empresa).filter_by(id=empresa_id).first()
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
                'Aplica':          r['aplica'],
                'Observaciones':   r['observaciones'],
                '_concepto_key':   r['concepto_json_key'],
                '_trabajador_id':  t.id,
                '_monto_grati':    r['monto_grati'],
            })

        df_show = pd.DataFrame([{k: v for k, v in f.items() if not k.startswith('_')}
                                  for f in filas])
        st.session_state['_grati_filas']       = filas
        st.session_state['_grati_periodo_pago'] = periodo_pago
        st.session_state['_grati_semestre']    = semestre
        st.session_state['_grati_anio']        = anio

        # Resumen
        total_grati = sum(f['_monto_grati'] for f in filas if f['Aplica'])
        total_bono  = sum(f['Bono 9%']      for f in filas if f['Aplica'])
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

    # Excel
    buf_xl = _excel_beneficios(df_show_saved,
                                f"Gratificaciones {SEMESTRES_GRATI[st.session_state.get('_grati_semestre','ENE-JUN')]['label']} {st.session_state.get('_grati_anio', anio)}")
    col_a.download_button("📊 Descargar Excel", data=buf_xl,
                           file_name=f"Gratificaciones_{periodo_pago_saved}.xlsx",
                           key="dl_grati_xl", use_container_width=True)

    # PDF
    buf_pdf = _pdf_beneficios(df_show_saved,
                               f"Gratificaciones — Período {periodo_pago_saved}",
                               empresa_nombre)
    col_b.download_button("📄 Descargar PDF", data=buf_pdf,
                           file_name=f"Gratificaciones_{periodo_pago_saved}.pdf",
                           mime="application/pdf", key="dl_grati_pdf", use_container_width=True)

    # Registrar en planilla
    if col_c.button("💾 Registrar en Planilla", type="primary",
                     use_container_width=True, key="btn_reg_grati",
                     help=f"Guarda los montos en las variables del período {periodo_pago_saved}"):
        db2 = SessionLocal()
        try:
            registrados = 0
            for f in filas:
                if not f['Aplica'] or f['_monto_grati'] <= 0:
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

    grati_ref = st.number_input(
        "Gratificación de referencia por trabajador (S/) — para calcular el 1/6",
        min_value=0.0, step=100.0, value=0.0, key="cts_grati_ref",
        help="Ingresa el monto de la última gratificación pagada (o la calculada en el semestre anterior). "
             "Se usará como base para el 1/6 de gratificación en la base CTS."
    )
    st.caption("Si cada trabajador tiene una gratificación diferente, calcúlala primero en la pestaña Gratificaciones y usa el valor de cada fila.")

    if st.button("🧮 Calcular CTS", type="primary",
                  use_container_width=True, key="btn_calc_cts"):
        db = SessionLocal()
        try:
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
            r = calcular_cts_trabajador(
                trabajador=t,
                periodo=periodo_cts,
                anio_deposito=anio_dep,
                rmv=rmv,
                grati_semestral=float(grati_ref),
                regimen_empresa=regimen_empresa,
                fecha_acogimiento=fecha_acogimiento,
            )
            filas.append({
                'Trabajador':      t.nombres,
                'DNI':             t.num_doc,
                'Sueldo Base':     t.sueldo_base,
                'Asig. Fam.':      round(r['monto_asig_fam'], 2),
                '1/6 Grati':       r['sexto_grati'],
                'Base CTS':        r['base_cts'],
                'Factor':          f"{r['factor_cts']*100:.0f}%",
                'Meses':           r['meses_computados'],
                'Depósito CTS':    r['monto_cts'],
                'Aplica':          r['aplica'],
                'Período':         r['periodo_label'],
                'Observaciones':   r['observaciones'],
                '_trabajador_id':  t.id,
                '_monto_cts':      r['monto_cts'],
                '_base_cts':       r['base_cts'],
                '_sexto_grati':    r['sexto_grati'],
                '_meses':          r['meses_computados'],
                '_factor':         r['factor_cts'],
                '_aplica':         r['aplica'],
            })

        df_show = pd.DataFrame([{k: v for k, v in f.items() if not k.startswith('_')}
                                  for f in filas])
        st.session_state['_cts_filas']          = filas
        st.session_state['_cts_periodo_key_dep'] = periodo_key_dep
        st.session_state['_cts_periodo_cts']    = periodo_cts
        st.session_state['_cts_anio_dep']       = anio_dep

        total_cts = sum(f['_monto_cts'] for f in filas if f['_aplica'])
        m1, m2 = st.columns(2)
        m1.metric("Total a Depositar", f"S/ {total_cts:,.2f}")
        m2.metric("N° Trabajadores",   str(sum(1 for f in filas if f['_aplica'])))

        st.dataframe(df_show, use_container_width=True, hide_index=True)

    # ── Acciones ──────────────────────────────────────────────────────────────
    filas = st.session_state.get('_cts_filas')
    if not filas:
        return

    periodo_key_dep_saved = st.session_state.get('_cts_periodo_key_dep', periodo_key_dep)
    periodo_cts_saved     = st.session_state.get('_cts_periodo_cts', periodo_cts)
    anio_dep_saved        = st.session_state.get('_cts_anio_dep', anio_dep)
    df_show_saved = pd.DataFrame([{k: v for k, v in f.items() if not k.startswith('_')}
                                   for f in filas])

    st.markdown("---")
    col_a, col_b, col_c = st.columns(3)

    buf_xl = _excel_beneficios(df_show_saved,
                                f"CTS {PERIODOS_CTS[periodo_cts_saved]['label']} {anio_dep_saved}")
    col_a.download_button("📊 Excel Banco", data=buf_xl,
                           file_name=f"CTS_{periodo_key_dep_saved}.xlsx",
                           key="dl_cts_xl", use_container_width=True)

    buf_pdf = _pdf_beneficios(df_show_saved,
                               f"Depósito CTS — {periodo_key_dep_saved}",
                               empresa_nombre)
    col_b.download_button("📄 PDF Declaración", data=buf_pdf,
                           file_name=f"CTS_{periodo_key_dep_saved}.pdf",
                           mime="application/pdf", key="dl_cts_pdf", use_container_width=True)

    if col_c.button("💾 Registrar Depósitos", type="primary",
                     use_container_width=True, key="btn_reg_cts",
                     help="Guarda los depósitos en la tabla histórica de CTS"):
        db3 = SessionLocal()
        try:
            registrados = 0
            cfg_periodo = PERIODOS_CTS[periodo_cts_saved]
            if periodo_cts_saved == 'NOV-ABR':
                periodo_label_str = (
                    f"NOV {anio_dep_saved - 1} – ABR {anio_dep_saved}"
                )
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
                'Período':        d.periodo_label or d.periodo_key_deposito,
                'Mes Depósito':   d.periodo_key_deposito,
                'Trabajador':     d.trabajador.nombres,
                'DNI':            d.trabajador.num_doc,
                'Base CTS':       d.base_computable,
                '1/6 Grati':      d.sexto_grati,
                'Meses':          d.meses_computados,
                'Factor':         f"{d.factor*100:.0f}%",
                'Monto':          d.monto,
                'Estado':         d.estado,
                'Fec. Depósito':  d.fecha_deposito.strftime('%d/%m/%Y') if d.fecha_deposito else '—',
            } for d in deps])
            st.dataframe(hist, use_container_width=True, hide_index=True)

            # Marcar como DEPOSITADO
            st.markdown("**Marcar depósito como realizado:**")
            opciones_pend = list({d.periodo_key_deposito for d in deps if d.estado == 'PENDIENTE'})
            if opciones_pend:
                per_marcar = st.selectbox("Período a confirmar", sorted(opciones_pend, reverse=True),
                                          key="cts_per_marcar")
                fecha_dep_conf = st.date_input("Fecha de depósito efectivo",
                                               value=datetime.date.today(), key="cts_fecha_dep")
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
    empresa_id      = st.session_state.get('empresa_activa_id')
    empresa_nombre  = st.session_state.get('empresa_activa_nombre', '')
    regimen_empresa = st.session_state.get('empresa_activa_regimen', 'Régimen General')
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
