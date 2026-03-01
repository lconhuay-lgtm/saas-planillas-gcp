import json
import io
import streamlit as st
import pandas as pd
from datetime import datetime

import calendar as _cal
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import PlanillaMensual, Trabajador, VariablesMes, ParametroLegal

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
    from sqlalchemy.orm import joinedload
    try:
        db = SessionLocal()
        planillas = (
            db.query(PlanillaMensual)
            .options(joinedload(PlanillaMensual.empresa))
            .filter_by(empresa_id=empresa_id)
            .order_by(PlanillaMensual.fecha_calculo.desc())
            .all()
        )
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
    tab_sabana, tab_resumen, tab_audit, tab_interfaces, tab_loc, tab_tesoreria, tab_bcp, tab_personalizado = st.tabs(
        ["📋 Sábana de Planilla", "📊 Resumen de Obligaciones",
         "🔍 Auditoría por Trabajador", "📥 Interfaces SUNAT/AFPnet",
         "🧾 Locadores (4ta Cat.)", "🏦 Reporte Tesorería", "💳 Pago Masivo BCP", "🛠️ Reporte Personalizado"]
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

    with tab_interfaces:
        st.markdown("### 📥 Exportación de Interfaces Oficiales")

        if estado_sel != "CERRADA":
            st.warning(
                "⚠️ Solo se pueden exportar interfaces de planillas **CERRADAS**. "
                "Cierre la planilla desde el módulo Cálculo de Planilla."
            )
        else:
            empresa_ruc = st.session_state.get('empresa_activa_ruc', '')
            mes_num, anio_num = int(sel_key[:2]), int(sel_key[3:])

            # Cargar conceptos para validación
            try:
                from infrastructure.database.connection import SessionLocal as _SL
                from infrastructure.database.models import Concepto as _Concepto, Trabajador as _Trab
                _db = _SL()
                empresa_id_rep = st.session_state.get('empresa_activa_id')
                conc_db  = _db.query(_Concepto).filter_by(empresa_id=empresa_id_rep).all()
                trab_db  = _db.query(_Trab).filter_by(empresa_id=empresa_id_rep).all()
                _db.close()
                df_conceptos_rep = pd.DataFrame([{
                    "Nombre del Concepto": c.nombre,
                    "Cód. SUNAT": getattr(c, 'codigo_sunat', '') or '',
                } for c in conc_db])
                df_trabajadores_rep = pd.DataFrame([{
                    "Num. Doc.":        t.num_doc,
                    "Apellido Paterno": getattr(t, 'apellido_paterno', '') or '',
                    "Apellido Materno": getattr(t, 'apellido_materno', '') or '',
                    "Nombres y Apellidos": t.nombres,
                    "Tipo Doc.":        t.tipo_doc or "DNI",
                    "Fecha Ingreso":    t.fecha_ingreso,
                    "CUSPP":            t.cuspp or '',
                    "Sistema Pensión":  t.sistema_pension or '',
                } for t in trab_db])
            except Exception as e_load:
                st.error(f"Error cargando datos: {e_load}")
                df_conceptos_rep = pd.DataFrame()
                df_trabajadores_rep = pd.DataFrame()

            col_p, col_a = st.columns(2)

            with col_p:
                st.markdown("#### Archivos PLAME (T-REGISTRO)")
                st.caption("Genera .REM · .JOR · .SNL comprimidos en un ZIP con nombre oficial SUNAT.")
                if st.button("Generar ZIP PLAME", type="primary", use_container_width=True, key="btn_plame"):
                    try:
                        from core.use_cases.generador_interfaces import generar_archivos_plame
                        buf_zip = generar_archivos_plame(
                            empresa_ruc=empresa_ruc, anio=anio_num, mes=mes_num,
                            df_planilla=df_planilla, auditoria_data=auditoria,
                            df_trabajadores=df_trabajadores_rep,
                            df_conceptos=df_conceptos_rep,
                        )
                        nombre_zip = f"0601{anio_num}{str(mes_num).zfill(2)}{empresa_ruc.zfill(11)}.zip"
                        st.download_button(
                            f"⬇️ Descargar {nombre_zip}", data=buf_zip,
                            file_name=nombre_zip, mime="application/zip",
                            use_container_width=True, key="dl_plame",
                        )
                    except ValueError as ve:
                        st.error(f"❌ {ve}")
                    except Exception as ex:
                        st.error(f"Error inesperado: {ex}")

            with col_a:
                st.markdown("#### Archivo AFPnet")
                st.caption("18 columnas estrictas para declaración AFP: Habitat, Integra, Prima, Profuturo.")
                if st.button("Generar Excel AFPnet", type="primary", use_container_width=True, key="btn_afpnet"):
                    try:
                        from core.use_cases.generador_interfaces import generar_excel_afpnet
                        buf_afp = generar_excel_afpnet(
                            anio=anio_num, mes=mes_num,
                            df_planilla=df_planilla, auditoria_data=auditoria,
                            df_trabajadores=df_trabajadores_rep,
                        )
                        nombre_afp = f"AFPnet_{sel_key.replace('-','_')}.xlsx"
                        st.download_button(
                            f"⬇️ Descargar {nombre_afp}", data=buf_afp,
                            file_name=nombre_afp,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True, key="dl_afpnet",
                        )
                    except ValueError as ve:
                        st.error(f"❌ {ve}")
                    except Exception as ex:
                        st.error(f"Error inesperado: {ex}")

    with tab_loc:
        st.markdown("### 🧾 Locadores de Servicio — Valorización (4ta Categoría)")
        st.markdown(f"**Periodo:** {_periodo_legible(sel_key)}  |  **Estado:** {badge}")
        st.markdown("---")

        try:
            _db2 = SessionLocal()

            locadores_rep = (
                _db2.query(Trabajador)
                .filter_by(empresa_id=empresa_id, situacion="ACTIVO", tipo_contrato="LOCADOR")
                .all()
            )

            if not locadores_rep:
                st.info("ℹ️ No hay Locadores de Servicio activos registrados para esta empresa.")
            else:
                p_rep = _db2.query(ParametroLegal).filter_by(
                    empresa_id=empresa_id, periodo_key=sel_key
                ).first()
                if not p_rep:
                    st.warning(f"No se encontraron Parámetros Legales para **{sel_key}**. Configure las tasas en 'Parámetros Legales'.")
                else:
                    tasa_4ta_r = getattr(p_rep, 'tasa_4ta', 8.0) or 8.0
                    tope_4ta_r = getattr(p_rep, 'tope_4ta', 1500.0) or 1500.0
                    variables_rep = {
                        v.trabajador_id: v
                        for v in _db2.query(VariablesMes).filter_by(
                            empresa_id=empresa_id, periodo_key=sel_key
                        ).all()
                    }
                    mes_rep  = int(sel_key[:2])
                    anio_rep = int(sel_key[3:])
                    dias_mes_r = _cal.monthrange(anio_rep, mes_rep)[1]

                    from core.use_cases.calculo_honorarios import calcular_recibo_honorarios

                    resultados_rep = []
                    for loc in locadores_rep:
                        v = variables_rep.get(loc.id)
                        if v:
                            cj = json.loads(v.conceptos_json or '{}')
                            vars_loc = {
                                'dias_no_prestados': getattr(v, 'dias_descuento_locador', 0) or 0,
                                'otros_pagos':       float(cj.get('_otros_pagos_loc', 0.0) or 0.0),
                                'otros_descuentos':  float(cj.get('_otros_descuentos_loc', 0.0) or 0.0),
                            }
                        else:
                            vars_loc = {'dias_no_prestados': 0, 'otros_pagos': 0.0, 'otros_descuentos': 0.0}

                        res = calcular_recibo_honorarios(
                            loc, vars_loc, dias_mes_r,
                            tasa_4ta=tasa_4ta_r, tope_4ta=tope_4ta_r
                        )
                        resultados_rep.append({
                            "DNI":                loc.num_doc,
                            "Locador":            loc.nombres,
                            "Cargo / Actividad":  loc.cargo or "Locador de Servicio",
                            "Honorario Base":     res['honorario_base'],
                            "Días no Prestados":  res['dias_no_prestados'],
                            "Descuento Días":     res['monto_descuento'],
                            "Otros Pagos":        res['otros_pagos'],
                            "Pago Bruto":         res['pago_bruto'],
                            "Retención 4ta (8%)": res['retencion_4ta'],
                            "Otros Descuentos":   res['otros_descuentos'],
                            "NETO A PAGAR":       res['neto_a_pagar'],
                        })

                    df_loc_rep = pd.DataFrame(resultados_rep)
                    ml1, ml2, ml3 = st.columns(3)
                    ml1.metric("Locadores", len(df_loc_rep))
                    ml2.metric("Total Pago Bruto",    f"S/ {df_loc_rep['Pago Bruto'].sum():,.2f}")
                    ml3.metric("Total Neto a Pagar",  f"S/ {df_loc_rep['NETO A PAGAR'].sum():,.2f}")
                    st.caption(f"Tasa 4ta Cat.: **{tasa_4ta_r}%** | Tope mínimo retención: **S/ {tope_4ta_r:,.2f}**")
                    st.dataframe(df_loc_rep, use_container_width=True, hide_index=True)

                    st.markdown("---")
                    st.markdown("#### 📥 Exportación Corporativa")
                    col_l1, col_l2 = st.columns(2)
                    with col_l1:
                        try:
                            from presentation.views.calculo_mensual import generar_excel_honorarios
                            buf_xl_loc = generar_excel_honorarios(
                                df_loc_rep, empresa_nombre, sel_key,
                                empresa_ruc=st.session_state.get('empresa_activa_ruc', '')
                            )
                            st.download_button(
                                "📊 Descargar Excel Locadores", data=buf_xl_loc,
                                file_name=f"HONORARIOS_{sel_key}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True, key="rep_dl_hon_xl"
                            )
                        except Exception as ex_xl:
                            st.error(f"Error generando Excel: {ex_xl}")
                    with col_l2:
                        try:
                            from presentation.views.calculo_mensual import generar_pdf_honorarios
                            buf_pdf_loc = generar_pdf_honorarios(
                                df_loc_rep, empresa_nombre, sel_key,
                                empresa_ruc=st.session_state.get('empresa_activa_ruc', ''),
                                empresa_regimen=st.session_state.get('empresa_activa_regimen', '')
                            )
                            st.download_button(
                                "📄 Descargar PDF Locadores", data=buf_pdf_loc,
                                file_name=f"HONORARIOS_{sel_key}.pdf",
                                mime="application/pdf",
                                use_container_width=True, key="rep_dl_hon_pdf"
                            )
                        except Exception as ex_pdf:
                            st.error(f"Error generando PDF: {ex_pdf}")

                    # Detalle individual
                    st.markdown("---")
                    st.markdown("#### 🔍 Detalle por Locador")
                    opciones_loc = [f"{r['DNI']} — {r['Locador']}" for r in resultados_rep]
                    if opciones_loc:
                        sel_loc = st.selectbox("Seleccione un locador:", opciones_loc, key="rep_loc_sel")
                        dni_loc_sel = sel_loc.split(" — ")[0]
                        data_loc = next((r for r in resultados_rep if r['DNI'] == dni_loc_sel), None)
                        if data_loc:
                            c_ing, c_dsc = st.columns(2)
                            with c_ing:
                                st.markdown("**Ingresos**")
                                st.write(f"- Honorario Base: S/ {data_loc['Honorario Base']:,.2f}")
                                if data_loc['Otros Pagos'] > 0:
                                    st.write(f"- Otros Pagos/Bonos: S/ {data_loc['Otros Pagos']:,.2f}")
                                if data_loc['Descuento Días'] > 0:
                                    st.write(f"- Desc. días no prestados: − S/ {data_loc['Descuento Días']:,.2f}")
                                st.success(f"**Pago Bruto: S/ {data_loc['Pago Bruto']:,.2f}**")
                            with c_dsc:
                                st.markdown("**Deducciones**")
                                if data_loc['Retención 4ta (8%)'] > 0:
                                    st.write(f"- Retención 4ta Cat. ({tasa_4ta_r}%): S/ {data_loc['Retención 4ta (8%)']:,.2f}")
                                if data_loc['Otros Descuentos'] > 0:
                                    st.write(f"- Otros Descuentos: S/ {data_loc['Otros Descuentos']:,.2f}")
                                tot_dsc = data_loc['Retención 4ta (8%)'] + data_loc['Otros Descuentos']
                                st.error(f"**Total Deducciones: S/ {tot_dsc:,.2f}**")
                            st.info(f"**NETO A PAGAR: S/ {data_loc['NETO A PAGAR']:,.2f}**")

            _db2.close()
        except Exception as e_loc:
            st.error(f"Error cargando datos de locadores: {e_loc}")

    # ── TAB: REPORTE DE TESORERÍA ─────────────────────────────────────────────
    with tab_tesoreria:
        st.markdown("### 🏦 Reporte de Tesorería — Pagos de Nómina")
        st.markdown(f"**Periodo:** {_periodo_legible(sel_key)}  |  **Estado:** {badge}")
        st.markdown("---")

        try:
            from presentation.views.calculo_mensual import generar_pdf_tesoreria
            from core.use_cases.calculo_honorarios import calcular_recibo_honorarios

            _db_t = SessionLocal()
            locadores_t = (
                _db_t.query(Trabajador)
                .filter_by(empresa_id=empresa_id, situacion="ACTIVO", tipo_contrato="LOCADOR")
                .all()
            )
            p_t = _db_t.query(ParametroLegal).filter_by(
                empresa_id=empresa_id, periodo_key=sel_key
            ).first()
            variables_t = {
                v.trabajador_id: v
                for v in _db_t.query(VariablesMes).filter_by(
                    empresa_id=empresa_id, periodo_key=sel_key
                ).all()
            }
            _db_t.close()

            # Recalcular locadores
            import json as _json_t
            mes_t = int(sel_key[:2]); anio_t = int(sel_key[3:])
            dias_mes_t = _cal.monthrange(anio_t, mes_t)[1]
            tasa_4ta_t  = getattr(p_t, 'tasa_4ta',  8.0)    if p_t else 8.0
            tope_4ta_t  = getattr(p_t, 'tope_4ta', 1500.0) if p_t else 1500.0

            resultados_t = []
            for loc in locadores_t:
                v = variables_t.get(loc.id)
                if v:
                    cj = _json_t.loads(v.conceptos_json or '{}')
                    vl = {
                        'dias_no_prestados': getattr(v, 'dias_descuento_locador', 0) or 0,
                        'otros_pagos':       float(cj.get('_otros_pagos_loc', 0.0) or 0.0),
                        'otros_descuentos':  float(cj.get('_otros_descuentos_loc', 0.0) or 0.0),
                    }
                else:
                    vl = {'dias_no_prestados': 0, 'otros_pagos': 0.0, 'otros_descuentos': 0.0}
                res = calcular_recibo_honorarios(loc, vl, dias_mes_t, tasa_4ta=tasa_4ta_t, tope_4ta=tope_4ta_t)
                resultados_t.append({
                    "DNI":                loc.num_doc,
                    "Locador":            loc.nombres,
                    "Días no Prestados":  res['dias_no_prestados'],
                    "Pago Bruto":         res['pago_bruto'],
                    "Retención 4ta (8%)": res['retencion_4ta'],
                    "Otros Descuentos":   res['otros_descuentos'],
                    "NETO A PAGAR":       res['neto_a_pagar'],
                    "Banco":              getattr(loc, 'banco', '') or '',
                    "N° Cuenta":          getattr(loc, 'cuenta_bancaria', '') or '',
                    "CCI":                getattr(loc, 'cci', '') or '',
                })

            df_loc_t = pd.DataFrame(resultados_t) if resultados_t else pd.DataFrame()

            # KPIs
            if not df_loc_t.empty:
                kt1, kt2, kt3 = st.columns(3)
                kt1.metric("Locadores", len(df_loc_t))
                kt2.metric("Total Bruto Locadores", f"S/ {df_loc_t['Pago Bruto'].sum():,.2f}")
                kt3.metric("Total Neto Locadores",  f"S/ {df_loc_t['NETO A PAGAR'].sum():,.2f}")
            if 'NETO A PAGAR' in df_planilla.columns:
                df_plan_sin_tot = df_planilla[df_planilla.get('Apellidos y Nombres', pd.Series(dtype=str)) != 'TOTALES'] \
                    if 'Apellidos y Nombres' in df_planilla.columns else df_planilla.iloc[:-1]
                kp1, kp2 = st.columns(2)
                kp1.metric("Total Bruto Planilla",  f"S/ {df_plan_sin_tot.get('TOTAL BRUTO', pd.Series([0])).sum():,.2f}")
                kp2.metric("Total Neto Planilla",   f"S/ {df_plan_sin_tot['NETO A PAGAR'].sum():,.2f}")

            st.markdown("---")
            # En reportería el DF ya incluye la fila de totales, debemos limpiarla antes de enviarla al PDF
            df_p_clean = df_planilla[df_planilla['Apellidos y Nombres'] != 'TOTALES'].copy()
            
            buf_teso = generar_pdf_tesoreria(
                df_planilla=df_p_clean,
                df_loc=df_loc_t if not df_loc_t.empty else None,
                empresa_nombre=empresa_nombre,
                periodo_key=sel_key,
                auditoria_data=auditoria,
                empresa_ruc=st.session_state.get('empresa_activa_ruc', ''),
            )
            st.download_button(
                "🏦 Descargar Reporte de Tesorería (PDF)",
                data=buf_teso,
                file_name=f"TESORERIA_{sel_key}.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="rep_dl_teso",
            )
        except Exception as e_teso:
            st.error(f"Error generando Reporte de Tesorería: {e_teso}")

    # ── TAB: PAGO MASIVO BCP ──────────────────────────────────────────────────
    with tab_bcp:
        st.markdown("### 💳 Generación de Telecrédito BCP (Haberes)")
        st.info("Esta herramienta genera el archivo TXT para cargar masivamente los pagos en el portal Telecrédito del BCP.")

        col_bcp1, col_bcp2 = st.columns(2)
        with col_bcp1:
            cta_cargo = st.text_input("Cuenta de Cargo BCP de la Empresa",
                                      value=getattr(planilla_sel.empresa, 'cuenta_cargo_bcp', '') or '',
                                      placeholder="Ej: 191-1234567-0-12")
        with col_bcp2:
            f_pago = st.date_input("Fecha de Proceso / Pago", value=datetime.now(), key="bcp_f_pago")

        filtro_banco = st.radio(
            "Filtro de Cuentas a Procesar:",
            ["💳 Todas las Cuentas (BCP + Interbancarias CCI)", "🏦 Solo Cuentas BCP (Ahorros/Corriente)"],
            horizontal=True
        )
        solo_bcp_flag = "Solo Cuentas BCP" in filtro_banco

        if st.button("📥 Generar y Descargar TXT BCP", use_container_width=True, type="primary"):
            if not cta_cargo:
                st.error("Debe ingresar la cuenta de cargo de la empresa.")
            else:
                try:
                    from core.use_cases.generador_interfaces import generar_txt_bcp
                    from core.use_cases.calculo_honorarios import calcular_recibo_honorarios as _chr_txt
                    _db_txt = SessionLocal()
                    locs_txt = _db_txt.query(Trabajador).filter_by(empresa_id=empresa_id, situacion="ACTIVO", tipo_contrato="LOCADOR").all()
                    vars_txt = {v.trabajador_id: v for v in _db_txt.query(VariablesMes).filter_by(empresa_id=empresa_id, periodo_key=sel_key).all()}
                    p_txt = _db_txt.query(ParametroLegal).filter_by(empresa_id=empresa_id, periodo_key=sel_key).first()
                    _db_txt.close()

                    res_l_txt = []
                    mes_i = int(sel_key[:2]); ani_i = int(sel_key[3:])
                    d_mes_i = _cal.monthrange(ani_i, mes_i)[1]
                    for l in locs_txt:
                        v = vars_txt.get(l.id)
                        cj = json.loads(v.conceptos_json or '{}') if v else {}
                        vl = {'dias_no_prestados': getattr(v, 'dias_descuento_locador', 0) or 0,
                              'otros_pagos': float(cj.get('_otros_pagos_loc', 0.0) or 0.0),
                              'otros_descuentos': float(cj.get('_otros_descuentos_loc', 0.0) or 0.0)}
                        r = _chr_txt(l, vl, d_mes_i, 
                                     tasa_4ta=getattr(p_txt, 'tasa_4ta', 8.0) if p_txt else 8.0,
                                     tope_4ta=getattr(p_txt, 'tope_4ta', 1500.0) if p_txt else 1500.0)
                        
                        # Mapear correctamente la cuenta para el generador TXT
                        cuenta_loc = l.cuenta_bancaria if l.banco == 'BCP' else l.cci
                        
                        res_l_txt.append({"DNI": l.num_doc, "Locador": l.nombres, "NETO A PAGAR": r['neto_a_pagar'], "CCI": l.cci, "N° Cuenta": cuenta_loc, "Banco": l.banco})
                    
                    txt_bcp = generar_txt_bcp(df_planilla, cta_cargo, f_pago, df_loc=pd.DataFrame(res_l_txt), solo_bcp=solo_bcp_flag)
                    st.download_button(
                        f"⬇️ Descargar BCP_HABERES_{f_pago.strftime('%Y%m%d')}.txt",
                        data=txt_bcp,
                        file_name=f"BCP_HABERES_{f_pago.strftime('%Y%m%d')}.txt",
                        mime="text/plain",
                        use_container_width=True
                    )
                except ValueError as ve:
                    st.error(f"⚠️ {ve}")
                except Exception as e:
                    st.error(f"Error inesperado: {e}")

    db.close()
    # ── TAB: REPORTE PERSONALIZADO ────────────────────────────────────────────
    with tab_personalizado:
        st.markdown("### 🛠️ Reporte Personalizado")
        st.markdown(f"**Periodo:** {_periodo_legible(sel_key)}  |  **Estado:** {badge}")
        st.markdown("---")

        tipo_rep = st.radio(
            "Seleccione el tipo de reporte:",
            ["Planilla (5ta Categoría)", "Locadores (4ta Categoría)"],
            horizontal=True,
            key="rep_pers_tipo",
        )

        try:
            import json as _json_p
            if tipo_rep.startswith("Planilla"):
                df_base_p = df_planilla.copy()
                if 'Apellidos y Nombres' in df_base_p.columns:
                    df_base_p = df_base_p[df_base_p['Apellidos y Nombres'] != 'TOTALES']
                cols_disp = list(df_base_p.columns)
            else:
                # Recalcular locadores para reporte personalizado
                from core.use_cases.calculo_honorarios import calcular_recibo_honorarios as _chr_p
                _db_p = SessionLocal()
                locadores_p = (
                    _db_p.query(Trabajador)
                    .filter_by(empresa_id=empresa_id, situacion="ACTIVO", tipo_contrato="LOCADOR")
                    .all()
                )
                p_p = _db_p.query(ParametroLegal).filter_by(empresa_id=empresa_id, periodo_key=sel_key).first()
                variables_p = {
                    v.trabajador_id: v
                    for v in _db_p.query(VariablesMes).filter_by(empresa_id=empresa_id, periodo_key=sel_key).all()
                }
                _db_p.close()
                mes_p = int(sel_key[:2]); anio_p = int(sel_key[3:])
                dias_mes_p = _cal.monthrange(anio_p, mes_p)[1]
                tasa_4ta_p = getattr(p_p, 'tasa_4ta',  8.0)    if p_p else 8.0
                tope_4ta_p = getattr(p_p, 'tope_4ta', 1500.0) if p_p else 1500.0
                rows_p = []
                for loc in locadores_p:
                    v = variables_p.get(loc.id)
                    if v:
                        cj = _json_p.loads(v.conceptos_json or '{}')
                        vl = {'dias_no_prestados': getattr(v, 'dias_descuento_locador', 0) or 0,
                              'otros_pagos': float(cj.get('_otros_pagos_loc', 0.0) or 0.0),
                              'otros_descuentos': float(cj.get('_otros_descuentos_loc', 0.0) or 0.0)}
                    else:
                        vl = {'dias_no_prestados': 0, 'otros_pagos': 0.0, 'otros_descuentos': 0.0}
                    res = _chr_p(loc, vl, dias_mes_p, tasa_4ta=tasa_4ta_p, tope_4ta=tope_4ta_p)
                    rows_p.append({
                        "DNI": loc.num_doc, "Locador": loc.nombres, "Cargo": loc.cargo or "",
                        "Honorario Base": res['honorario_base'],
                        "Días no Prestados": res['dias_no_prestados'],
                        "Descuento Días": res['monto_descuento'],
                        "Otros Pagos": res['otros_pagos'],
                        "Pago Bruto": res['pago_bruto'],
                        "Retención 4ta (8%)": res['retencion_4ta'],
                        "Otros Descuentos": res['otros_descuentos'],
                        "NETO A PAGAR": res['neto_a_pagar'],
                        "Banco": getattr(loc, 'banco', '') or '',
                        "N° Cuenta": getattr(loc, 'cuenta_bancaria', '') or '',
                        "CCI": getattr(loc, 'cci', '') or '',
                    })
                df_base_p = pd.DataFrame(rows_p) if rows_p else pd.DataFrame()
                cols_disp = list(df_base_p.columns)

            if df_base_p.empty:
                st.info("No hay datos disponibles para el tipo de reporte seleccionado.")
            else:
                cols_sel = st.multiselect(
                    "Seleccione las columnas a incluir:",
                    options=cols_disp,
                    default=cols_disp,
                    key="rep_pers_cols",
                )
                if cols_sel:
                    df_preview = df_base_p[cols_sel]
                    st.markdown("**Vista Previa:**")
                    st.dataframe(df_preview, use_container_width=True, hide_index=True)

                    tipo_file = "PLANILLA" if tipo_rep.startswith("Planilla") else "LOCADORES"
                    titulo_pdf = (
                        "PLANILLA DE REMUNERACIONES — REPORTE PERSONALIZADO"
                        if tipo_rep.startswith("Planilla")
                        else "LOCADORES DE SERVICIO — REPORTE PERSONALIZADO"
                    )
                    dl_xl, dl_pdf = st.columns(2)

                    # Excel
                    import io as _io_p
                    buf_xl_p = _io_p.BytesIO()
                    with pd.ExcelWriter(buf_xl_p, engine='openpyxl') as _writer_p:
                        df_preview.to_excel(_writer_p, sheet_name='Reporte', index=False)
                    buf_xl_p.seek(0)
                    dl_xl.download_button(
                        f"📊 Descargar Excel",
                        data=buf_xl_p,
                        file_name=f"Reporte_Dinamico_{tipo_file}_{sel_key}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key="rep_dl_pers_xl",
                    )

                    # PDF corporativo
                    try:
                        from presentation.views.calculo_mensual import generar_pdf_personalizado
                        buf_pdf_p = generar_pdf_personalizado(
                            df=df_preview,
                            empresa_nombre=empresa_nombre,
                            periodo_key=sel_key,
                            titulo=titulo_pdf,
                            empresa_ruc=st.session_state.get('empresa_activa_ruc', ''),
                        )
                        dl_pdf.download_button(
                            f"📄 Descargar PDF",
                            data=buf_pdf_p,
                            file_name=f"Reporte_Dinamico_{tipo_file}_{sel_key}.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                            key="rep_dl_pers_pdf",
                        )
                    except Exception as _e_pdf_p:
                        dl_pdf.error(f"Error PDF: {_e_pdf_p}")
                else:
                    st.warning("Seleccione al menos una columna.")
        except Exception as e_pers:
            st.error(f"Error generando Reporte Personalizado: {e_pers}")
