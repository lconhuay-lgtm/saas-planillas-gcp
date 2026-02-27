import json
import io
import streamlit as st
import pandas as pd
from datetime import datetime

from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import PlanillaMensual

_MESES_ES = {
    "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
    "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
    "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre"
}

def _periodo_legible(periodo_key: str) -> str:
    partes = periodo_key.split("-")
    if len(partes) == 2:
        return f"{_MESES_ES.get(partes[0], partes[0])} {partes[1]}"
    return periodo_key


def render():
    st.title("📊 Reportería de Planillas")
    st.markdown("Consulta el historial completo de planillas procesadas y cerradas de la empresa activa.")
    st.markdown("---")

    empresa_id     = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre', '')

    if not empresa_id:
        st.error("Seleccione una empresa en el Dashboard para acceder a reportería.")
        return

    # ── Cargar todas las planillas de la empresa ──────────────────────────────
    try:
        db = SessionLocal()
        planillas = (
            db.query(PlanillaMensual)
            .filter_by(empresa_id=empresa_id)
            .order_by(PlanillaMensual.fecha_calculo.desc())
            .all()
        )
        db.close()
    except Exception as e:
        st.error(f"Error al conectar con la base de datos: {e}")
        return

    if not planillas:
        st.info("No hay planillas registradas para esta empresa.")
        return

    # ── Tabla resumen de planillas ────────────────────────────────────────────
    resumen = []
    for p in planillas:
        estado    = getattr(p, 'estado', 'ABIERTA') or 'ABIERTA'
        cerr_por  = getattr(p, 'cerrada_por', '') or '—'
        fecha_c   = getattr(p, 'fecha_cierre', None)
        fecha_str = fecha_c.strftime("%d/%m/%Y %H:%M") if fecha_c else '—'
        resumen.append({
            'Periodo':        _periodo_legible(p.periodo_key),
            'Periodo Key':    p.periodo_key,
            'Calculada el':   p.fecha_calculo.strftime("%d/%m/%Y %H:%M") if p.fecha_calculo else '—',
            'Estado':         estado,
            'Cerrada por':    cerr_por,
            'Fecha Cierre':   fecha_str,
        })

    df_res = pd.DataFrame(resumen)

    # KPIs superiores
    total     = len(planillas)
    cerradas  = sum(1 for r in resumen if r['Estado'] == 'CERRADA')
    abiertas  = total - cerradas

    k1, k2, k3 = st.columns(3)
    k1.metric("Total Planillas", total)
    k2.metric("Cerradas", cerradas)
    k3.metric("Abiertas / En proceso", abiertas)

    st.markdown("---")

    # Filtro por estado
    filtro = st.radio("Filtrar por estado:", ["Todas", "Cerradas", "Abiertas"], horizontal=True)
    if filtro == "Cerradas":
        df_mostrar = df_res[df_res['Estado'] == 'CERRADA']
    elif filtro == "Abiertas":
        df_mostrar = df_res[df_res['Estado'] == 'ABIERTA']
    else:
        df_mostrar = df_res

    # Colorear filas según estado
    def _color_estado(val):
        if val == "CERRADA":
            return "background-color:#DCEEFB; color:#0D47A1; font-weight:bold"
        return "background-color:#FFF8E1; color:#E65100; font-weight:bold"

    st.dataframe(
        df_mostrar.drop(columns=['Periodo Key']).style.applymap(_color_estado, subset=['Estado']),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")
    st.markdown("### Ver detalle de una planilla")

    periodos_disp = [r['Periodo Key'] for r in resumen]
    periodos_label = [_periodo_legible(k) for k in periodos_disp]

    sel_label = st.selectbox("Seleccione el periodo:", periodos_label, key="rep_periodo_sel")
    sel_key   = periodos_disp[periodos_label.index(sel_label)]

    planilla_sel = next((p for p in planillas if p.periodo_key == sel_key), None)
    if not planilla_sel:
        return

    estado_sel = getattr(planilla_sel, 'estado', 'ABIERTA') or 'ABIERTA'
    badge = "🔒 CERRADA" if estado_sel == "CERRADA" else "🟡 ABIERTA"
    st.markdown(f"**Periodo:** {_periodo_legible(sel_key)}  |  **Estado:** {badge}")

    try:
        df_planilla = pd.read_json(io.StringIO(planilla_sel.resultado_json), orient='records')
        auditoria   = json.loads(planilla_sel.auditoria_json)
    except Exception as e:
        st.error(f"No se pudo deserializar la planilla: {e}")
        return

    # Tabs de detalle
    tab_sabana, tab_resumen, tab_audit = st.tabs(
        ["📋 Sábana de Planilla", "📊 Resumen de Obligaciones", "🔍 Auditoría por Trabajador"]
    )

    with tab_sabana:
        st.dataframe(df_planilla.iloc[:-1], use_container_width=True, hide_index=True)

        col_xl, col_csv = st.columns(2)
        with col_xl:
            try:
                from presentation.views.calculo_mensual import generar_excel_sabana
                buf_xl = generar_excel_sabana(
                    df_planilla, empresa_nombre, sel_key,
                    empresa_ruc=st.session_state.get('empresa_activa_ruc', '')
                )
                st.download_button(
                    "📊 Descargar Excel", data=buf_xl,
                    file_name=f"PLANILLA_{sel_key}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            except Exception:
                pass
        with col_csv:
            csv_bytes = df_planilla.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📄 Descargar CSV", data=csv_bytes,
                file_name=f"PLANILLA_{sel_key}.csv",
                mime="text/csv",
                use_container_width=True
            )

    with tab_resumen:
        # Totales de la fila de totales
        df_data = df_planilla[df_planilla.get('Apellidos y Nombres', pd.Series(dtype=str)) != 'TOTALES'] \
            if 'Apellidos y Nombres' in df_planilla.columns else df_planilla.iloc[:-1]

        cols_num = [c for c in df_planilla.columns
                    if df_planilla[c].dtype in ['float64', 'int64'] and c not in ('N°', 'DNI')]

        if cols_num:
            totales = {c: df_data[c].sum() for c in cols_num if c in df_data.columns}
            df_tot = pd.DataFrame([
                {"Concepto": c, "Total (S/)": f"{v:,.2f}"}
                for c, v in totales.items() if v > 0
            ])
            st.dataframe(df_tot, use_container_width=True, hide_index=True)

        # N° trabajadores
        n_trab = len(df_data)
        neto_total = df_data['NETO A PAGAR'].sum() if 'NETO A PAGAR' in df_data.columns else 0.0
        bruto_total = df_data['TOTAL BRUTO'].sum() if 'TOTAL BRUTO' in df_data.columns else 0.0

        m1, m2, m3 = st.columns(3)
        m1.metric("Trabajadores", n_trab)
        m2.metric("Masa Salarial Bruta", f"S/ {bruto_total:,.2f}")
        m3.metric("Total Neto a Pagar", f"S/ {neto_total:,.2f}")

    with tab_audit:
        if not auditoria:
            st.info("No hay datos de auditoría disponibles para esta planilla.")
        else:
            opciones = [f"{dni} — {info.get('nombres','')}" for dni, info in auditoria.items()]
            sel_trab = st.selectbox("Trabajador:", opciones, key="rep_audit_trab")
            dni_sel  = sel_trab.split(" — ")[0]
            data     = auditoria[dni_sel]

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Ingresos**")
                for k, v in data.get('ingresos', {}).items():
                    st.write(f"- {k}: S/ {v:,.2f}")
                tot_ing = data.get('totales', {}).get('ingreso', 0)
                st.success(f"**Total Ingresos: S/ {tot_ing:,.2f}**")
            with c2:
                st.markdown("**Descuentos**")
                for k, v in data.get('descuentos', {}).items():
                    st.write(f"- {k}: S/ {v:,.2f}")
                tot_desc = data.get('totales', {}).get('descuento', 0)
                st.error(f"**Total Descuentos: S/ {tot_desc:,.2f}**")

            neto_audit = tot_ing - tot_desc
            st.info(f"**Neto a Pagar: S/ {neto_audit:,.2f}**")
