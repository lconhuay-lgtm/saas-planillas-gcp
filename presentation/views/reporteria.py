import json
import io
import streamlit as st
import pandas as pd
from datetime import datetime, date

import calendar as _cal
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import PlanillaMensual, Trabajador, VariablesMes, ParametroLegal
from core.use_cases.exportador_plame import generar_zip_plame, resumen_aportes_empleador_plame

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
    
    empresa_id     = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre', '')

    st.markdown("Consulta el historial completo de planillas procesadas y cerradas de la empresa activa.")
    st.markdown("---")

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
        df_mostrar.drop(columns=['Periodo Key']).style.map(_color_estado, subset=['Estado']),
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

        # Filtro de seguridad: Si el trabajador fue cesado ANTES de este periodo, 
        # no debería visualizarse en el detalle, incluso si está en el JSON.
        mes_p, anio_p = int(sel_key[:2]), int(sel_key[3:])
        
        # Recuperar trabajadores de la BD para verificar fecha de cese real
        db_aux = SessionLocal()
        trab_cesados = db_aux.query(Trabajador).filter(
            Trabajador.empresa_id == empresa_id,
            Trabajador.fecha_cese != None
        ).all()
        db_aux.close()

        dnis_a_omitir = [
            t.num_doc for t in trab_cesados 
            if (t.fecha_cese.year < anio_p or (t.fecha_cese.year == anio_p and t.fecha_cese.month < mes_p))
        ]

        if dnis_a_omitir and not df_planilla.empty:
            df_planilla = df_planilla[~df_planilla['DNI'].isin(dnis_a_omitir)]
            # También limpiar la auditoría para consistencia
            auditoria = {dni: info for dni, info in auditoria.items() if dni not in dnis_a_omitir}

    except Exception as e:
        st.error(f"No se pudo deserializar la planilla: {e}")
        return

    # Tabs de detalle
    tab_sabana, tab_resumen, tab_audit, tab_interfaces, tab_loc, tab_tesoreria, tab_bcp, tab_asiento, tab_personalizado = st.tabs(
        ["📋 Sábana de Planilla", "📊 Resumen de Obligaciones",
         "🔍 Auditoría por Trabajador", "📥 Interfaces SUNAT/AFPnet",
         "🧾 Locadores (4ta Cat.)", "🏦 Reporte Tesorería", "💳 Pago Masivo BCP",
         "📒 Asiento Contable", "🛠️ Reporte Personalizado"]
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
                import calendar as _cal_rep
                from infrastructure.database.connection import SessionLocal as _SL
                from infrastructure.database.models import Concepto as _Concepto, Trabajador as _Trab, LiquidacionCese as _LiqCese
                _db = _SL()
                empresa_id_rep = st.session_state.get('empresa_activa_id')
                conc_db  = _db.query(_Concepto).filter_by(empresa_id=empresa_id_rep).all()
                trab_db  = _db.query(_Trab).filter_by(empresa_id=empresa_id_rep).all()

                # Liquidaciones por Cese aprobadas cuya fecha de cese cae en este periodo:
                # su AFP/ONP sobre vacaciones truncas (y sueldo prop. si aplica) también
                # debe declararse en AFPnet (solo la porción AFP — ONP no va en este archivo).
                _ultimo_dia_rep = _cal_rep.monthrange(anio_num, mes_num)[1]
                liq_periodo_rep = _db.query(_LiqCese).filter(
                    _LiqCese.empresa_id == empresa_id_rep,
                    _LiqCese.estado != 'BORRADOR',
                    _LiqCese.fecha_cese_snapshot >= date(anio_num, mes_num, 1),
                    _LiqCese.fecha_cese_snapshot <= date(anio_num, mes_num, _ultimo_dia_rep),
                ).all()
                liquidaciones_afp_rep = {}
                for _liq in liq_periodo_rep:
                    if "AFP" not in str(_liq.sistema_pension_snapshot or '').upper():
                        continue
                    _trab_liq = _db.query(_Trab).filter_by(id=_liq.trabajador_id).first()
                    if not _trab_liq:
                        continue
                    _base_extra = float(_liq.monto_vacaciones_truncas or 0.0) + float(_liq.monto_sueldo_proporcional or 0.0)
                    if _base_extra > 0:
                        liquidaciones_afp_rep[str(_trab_liq.num_doc)] = liquidaciones_afp_rep.get(str(_trab_liq.num_doc), 0.0) + _base_extra

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
                    "Fecha Cese":       t.fecha_cese,
                    "CUSPP":            t.cuspp or '',
                    "Sistema Pensión":  t.sistema_pension or '',
                } for t in trab_db])
            except Exception as e_load:
                st.error(f"Error cargando datos: {e_load}")
                df_conceptos_rep = pd.DataFrame()
                df_trabajadores_rep = pd.DataFrame()
                liquidaciones_afp_rep = {}

            if liquidaciones_afp_rep:
                st.info(
                    f"ℹ️ Se incluirán {len(liquidaciones_afp_rep)} Liquidación(es) por Cese de este "
                    f"periodo (vacaciones truncas y demás conceptos afectos) en el PLAME y/o AFPnet."
                )

            col_p, col_a = st.columns(2)

            with col_p:
                st.markdown("#### Archivos PLAME (Estructura PDT)")
                st.caption("Genera el paquete oficial (.rem, .jor, .sub, .not) con validación estricta de códigos SUNAT.")

                # Aportes del empleador (Vida Ley / SCTR) en el .REM — opcional y apagado por
                # defecto hasta validar el layout con una declaración de prueba en el PDT.
                incluir_aportes_emp = st.checkbox(
                    "Incluir aportes del empleador (Vida Ley / SCTR) en el .REM",
                    value=False, key="chk_plame_aportes_emp",
                    help="Agrega por trabajador los códigos 0803 (Vida Ley), 0810 (SCTR Salud con EPS), "
                         "0813 (SCTR Pensión con ONP) y 0814 (SCTR Pensión con aseguradora). "
                         "Valide el archivo con una declaración de prueba antes de usarlo.",
                )
                if incluir_aportes_emp:
                    try:
                        _res_ap = resumen_aportes_empleador_plame(empresa_id, f"{str(mes_num).zfill(2)}-{anio_num}")
                        st.caption(f"{_res_ap['exportables']} línea(s) de aportes del empleador se agregarán al .REM.")
                        if _res_ap["sin_codigo"]:
                            st.warning(
                                f"⚠️ {len(_res_ap['sin_codigo'])} aporte(s) NO se exportarán porque su código PLAME "
                                f"aún no está definido (SCTR Salud con EsSalud): "
                                + ", ".join(f"{d} ({e})" for d, e, _ in _res_ap["sin_codigo"][:8])
                                + ("…" if len(_res_ap["sin_codigo"]) > 8 else "")
                            )
                    except Exception as _e_ap:
                        st.caption(f"No se pudo resumir los aportes del empleador: {_e_ap}")

                if st.button("🚀 Generar ZIP PLAME Profesional", type="primary", use_container_width=True, key="btn_plame_v2"):
                    try:
                        with st.spinner("Procesando histórico y validando conceptos..."):
                            buf_zip = generar_zip_plame(empresa_id, mes_num, anio_num, incluir_aportes_empleador=incluir_aportes_emp)
                            nombre_zip = f"0601{anio_num}{str(mes_num).zfill(2)}{empresa_ruc.zfill(11)}.zip"
                            st.success(f"✅ Archivo listo para declarar.")
                            st.download_button(
                                f"⬇️ Descargar {nombre_zip}", data=buf_zip,
                                file_name=nombre_zip, mime="application/zip",
                                use_container_width=True, key="dl_plame_v2",
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
                            liquidaciones_afp=liquidaciones_afp_rep,
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

        # ── FUENTE ÚNICA DE VERDAD: snapshot congelado en PlanillaMensual.honorarios_json ──
        hon_json_str = getattr(planilla_sel, 'honorarios_json', '[]') or '[]'
        try:
            df_loc_rep = pd.read_json(io.StringIO(hon_json_str), orient='records')
            
            # Aplicar mismo filtro de seguridad para locadores cesados
            if not df_loc_rep.empty and dnis_a_omitir:
                df_loc_rep = df_loc_rep[~df_loc_rep['DNI'].isin(dnis_a_omitir)]
        except Exception:
            df_loc_rep = pd.DataFrame()

        if df_loc_rep.empty:
            if estado_sel == "CERRADA":
                st.warning(
                    "⚠️ **Snapshot de locadores no encontrado** para este periodo cerrado.\n\n"
                    "Los honorarios de locadores no fueron calculados antes del cierre. "
                    "Para recuperar los datos: reabra el periodo (requiere Supervisor), vaya a "
                    "**Cálculo de Planilla → tab 2. Honorarios (4ta Categoría)**, presione "
                    "**🧮 Calcular Honorarios** y vuelva a cerrar el periodo."
                )
            else:
                st.info(
                    "ℹ️ Los honorarios de locadores aún no han sido calculados para este periodo. "
                    "Vaya a **Cálculo de Planilla → tab 2. Honorarios (4ta Categoría)** "
                    "y presione **🧮 Calcular Honorarios**."
                )
        else:
            cols_display = [c for c in df_loc_rep.columns if c not in ("Banco", "N° Cuenta", "CCI", "Observaciones")]
            ml1, ml2, ml3 = st.columns(3)
            ml1.metric("Locadores", len(df_loc_rep))
            ml2.metric("Total Pago Bruto",   f"S/ {df_loc_rep['Pago Bruto'].sum():,.2f}")
            ml3.metric("Total Neto a Pagar", f"S/ {df_loc_rep['NETO A PAGAR'].sum():,.2f}")
            st.caption("📌 Datos congelados al momento del cálculo — Fuente: snapshot auditado del periodo.")
            st.dataframe(df_loc_rep[cols_display], use_container_width=True, hide_index=True)

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

            # ── Detalle individual por locador ─────────────────────────────────────────────
            st.markdown("---")
            st.markdown("#### 🔍 Detalle por Locador")
            resultados_rep_list = df_loc_rep.to_dict('records')
            opciones_loc = [f"{r.get('DNI', '')} — {r.get('Locador', '')}" for r in resultados_rep_list]
            if opciones_loc:
                sel_loc = st.selectbox("Seleccione un locador:", opciones_loc, key="rep_loc_sel")
                dni_loc_sel = sel_loc.split(" — ")[0]
                data_loc = next((r for r in resultados_rep_list if str(r.get('DNI', '')) == dni_loc_sel), None)
                if data_loc:
                    c_ing, c_dsc = st.columns(2)
                    with c_ing:
                        st.markdown("**Ingresos**")
                        st.write(f"- Honorario Base: S/ {float(data_loc.get('Honorario Base', 0) or 0):,.2f}")
                        if float(data_loc.get('Otros Pagos', 0) or 0) > 0:
                            st.write(f"- Otros Pagos/Bonos: S/ {float(data_loc['Otros Pagos']):,.2f}")
                        if float(data_loc.get('Descuento Días', 0) or 0) > 0:
                            st.write(f"- Desc. días no prestados: − S/ {float(data_loc['Descuento Días']):,.2f}")
                        st.success(f"**Pago Bruto: S/ {float(data_loc.get('Pago Bruto', 0) or 0):,.2f}**")
                    with c_dsc:
                        st.markdown("**Deducciones**")
                        ret4ta    = float(data_loc.get('Retención 4ta (8%)', 0) or 0)
                        otros_dsc = float(data_loc.get('Otros Descuentos', 0) or 0)
                        if ret4ta > 0:
                            st.write(f"- Retención 4ta Cat.: S/ {ret4ta:,.2f}")
                        if otros_dsc > 0:
                            st.write(f"- Otros Descuentos: S/ {otros_dsc:,.2f}")
                        st.error(f"**Total Deducciones: S/ {ret4ta + otros_dsc:,.2f}**")
                    st.info(f"**NETO A PAGAR: S/ {float(data_loc.get('NETO A PAGAR', 0) or 0):,.2f}**")
                    obs = str(data_loc.get('Observaciones', '') or '')
                    if obs:
                        st.caption(f"📝 {obs}")

    # ── TAB: REPORTE DE TESORERÍA ─────────────────────────────────────────────
    with tab_tesoreria:
        st.markdown("### 🏦 Reporte de Tesorería — Pagos de Nómina")
        st.markdown(f"**Periodo:** {_periodo_legible(sel_key)}  |  **Estado:** {badge}")
        st.markdown("---")

        try:
            from presentation.views.calculo_mensual import generar_pdf_tesoreria
            
            # LECTURA DE SNAPSHOT (Congelado en BD)
            hon_json_str = getattr(planilla_sel, 'honorarios_json', '[]') or '[]'
            df_loc_t = pd.read_json(io.StringIO(hon_json_str), orient='records')
            if df_loc_t is None:
                df_loc_t = pd.DataFrame()

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
            _FMT_TESO_OPC = {"CLASICO": "Clásico", "DETALLADO": "Detallado (Préstamos/Adelantos, Faltas y Tardanzas, Otros)"}
            _fmt_default = st.session_state.get('empresa_formato_reporte_tesoreria', 'CLASICO') or 'CLASICO'
            fmt_teso_rep = st.selectbox(
                "Formato del reporte", options=list(_FMT_TESO_OPC.keys()),
                index=list(_FMT_TESO_OPC.keys()).index(_fmt_default) if _fmt_default in _FMT_TESO_OPC else 0,
                format_func=lambda x: _FMT_TESO_OPC[x],
                key="sel_fmt_teso_rep",
                help="Solo cambia cómo se presenta el reporte — no afecta ningún cálculo de planilla.",
            )
            # En reportería el DF ya incluye la fila de totales, debemos limpiarla antes de enviarla al PDF
            df_p_clean = df_planilla[df_planilla['Apellidos y Nombres'] != 'TOTALES'].copy()

            from infrastructure.database.models import Concepto as _ConceptoTeso
            _db_norem = SessionLocal()
            _conceptos_norem_rep = {
                c.nombre for c in _db_norem.query(_ConceptoTeso).filter_by(
                    empresa_id=empresa_id, tipo='INGRESO', no_remunerativo=True
                ).all()
            }
            _db_norem.close()

            buf_teso = generar_pdf_tesoreria(
                df_planilla=df_p_clean,
                df_loc=df_loc_t if not df_loc_t.empty else None,
                empresa_nombre=empresa_nombre,
                periodo_key=sel_key,
                auditoria_data=auditoria,
                empresa_ruc=st.session_state.get('empresa_activa_ruc', ''),
                formato=fmt_teso_rep,
                conceptos_no_remunerativos=_conceptos_norem_rep,
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
                    
                    # LECTURA DE SNAPSHOT
                    hon_json_str = getattr(planilla_sel, 'honorarios_json', '[]') or '[]'
                    df_loc_bcp = pd.read_json(io.StringIO(hon_json_str), orient='records')
                    
                    # Mapeo de seguridad para cuentas bancarias en Snapshot BCP
                    if not df_loc_bcp.empty and 'N° Cuenta' not in df_loc_bcp.columns:
                        df_loc_bcp['N° Cuenta'] = df_loc_bcp.apply(lambda r: str(r.get('cuenta_bancaria', '') or '') if str(r.get('Banco', '') or '') == 'BCP' else str(r.get('CCI', '') or ''), axis=1)

                    txt_bcp = generar_txt_bcp(df_planilla, cta_cargo, f_pago, df_loc=df_loc_bcp, solo_bcp=solo_bcp_flag)
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

    # ── TAB: ASIENTO CONTABLE (Excel de importación a SISCONT) ─────────────────
    with tab_asiento:
        from core.use_cases.generador_asiento_contable import VERSION_GENERADOR
        st.markdown("### 📒 Asiento Contable de Planilla")
        st.markdown(f"**Periodo:** {_periodo_legible(sel_key)}  |  **Estado:** {badge}")
        st.caption(
            "Genera el Excel de importación a SISCONT con el asiento de planilla del "
            "mes. No depende de si las boletas ya fueron autorizadas/enviadas."
        )
        st.caption(f"🔧 Versión del generador: `{VERSION_GENERADOR}`")
        st.markdown("---")

        mes_num_asiento = int(sel_key[:2])
        if mes_num_asiento in (7, 12):
            st.info(
                f"ℹ️ En **{_periodo_legible(sel_key)}** el asiento incluye el **pago de la gratificación** "
                f"y el bono extraordinario. Lo ya provisionado mes a mes se cancela contra "
                f"«Gratificación por pagar» y solo la diferencia va a gasto; si todavía no hay "
                f"provisiones registradas del semestre, todo el pago se reconoce como gasto de este mes."
            )
        if estado_sel != "CERRADA":
            st.info("ℹ️ El asiento contable solo está disponible para periodos **cerrados**.")
        else:
            if st.button("📒 Generar Asiento Contable (Excel)", type="primary", use_container_width=True, key="btn_gen_asiento"):
                from core.use_cases.generador_asiento_contable import generar_asiento_planilla, AsientoContableError
                try:
                    with st.spinner("Armando el asiento contable..."):
                        buf_asiento = generar_asiento_planilla(db, empresa_id, sel_key)
                    st.success("✅ Asiento generado y cuadrado correctamente (Debe = Haber).")
                    st.download_button(
                        f"📥 Descargar ASIENTO_{sel_key}.xlsx",
                        data=buf_asiento,
                        file_name=f"ASIENTO_PLANILLA_{sel_key}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key="dl_asiento",
                    )
                except AsientoContableError as ace:
                    if ace.cuentas_faltantes:
                        st.error(f"⚠️ **No se puede generar el asiento contable** — {ace.mensaje}")
                        for cuenta_f in ace.cuentas_faltantes:
                            st.markdown(f"- {cuenta_f}")
                        st.info(
                            "Vaya a **Configuración Contable** (cuentas fijas) o **Maestro de "
                            "Conceptos** (cuentas por concepto) para completarlas, y vuelva a "
                            "intentarlo."
                        )
                    elif ace.detalle_diagnostico:
                        st.error(f"⚠️ {ace.mensaje}")
                        st.markdown("##### 🔍 Diagnóstico — trabajador(es) que causan la diferencia")
                        st.caption(
                            "Cada fila compara, para ese trabajador, todo lo que se le cargó como "
                            "gasto/aporte (Debe) contra todo lo que se le abonó a alguna cuenta "
                            "(Haber). Si no coinciden, ahí está el origen del descuadre."
                        )
                        st.dataframe(
                            pd.DataFrame(ace.detalle_diagnostico)[["dni", "nombre", "debe", "haber", "diferencia"]]
                            .rename(columns={"dni": "DNI", "nombre": "Trabajador", "debe": "Debe (S/)",
                                              "haber": "Haber (S/)", "diferencia": "Diferencia (S/)"}),
                            use_container_width=True, hide_index=True,
                        )
                        st.info(
                            "Si la diferencia coincide con un 'Ajuste AFP' o 'Ajuste Varios' hecho "
                            "en el Panel de Auditoría Tributaria de ese trabajador, revise ese "
                            "periodo en Cálculo de Planilla. Si no reconoce la causa, copie esta "
                            "tabla y compártala para seguir investigando."
                        )
                    else:
                        st.warning(f"ℹ️ {ace.mensaje}")
                except Exception as e_asiento:
                    st.error(f"Error inesperado al generar el asiento: {e_asiento}")

        # ── Provisión mensual de gratificación (+ bono extraordinario) ─────────────
        from core.use_cases import provision_gratificacion as _pg
        from core.use_cases.generador_asiento_contable import AsientoContableError as _ACE
        st.markdown("---")
        st.markdown("### 📈 Provisión Mensual de Gratificación")
        st.caption(
            "Reconoce mes a mes el gasto de la gratificación y el bono extraordinario (voucher "
            "aparte del asiento de planilla). Lo registrado aquí es lo que el asiento de "
            "julio/diciembre y la liquidación por cese descuentan para no duplicar el gasto. "
            f"La provisión arranca en julio 2026. 🔧 `{_pg.VERSION_PROVISION}`"
        )
        if not _pg.es_provisionable(sel_key):
            st.info(f"ℹ️ {_pg.motivo_no_provisionable(sel_key)}")
        elif estado_sel != "CERRADA":
            st.info("ℹ️ La provisión solo está disponible para periodos **cerrados**.")
        else:
            try:
                _prev = _pg.calcular_provision_mes(db, empresa_id, sel_key)
            except _ACE as _e_prev:
                st.warning(f"ℹ️ {_e_prev.mensaje}")
                _prev = []
            _pend = [f for f in _prev if abs(f["delta_total"]) > 0.004]
            # ¿Este mes ya se registró? (el cálculo compara contra meses ANTERIORES, así que
            # un mes ya registrado reaparece como "pendiente" — se avisa y se ofrece regenerar)
            _reg = next((r for r in _pg.resumen_libro(db, empresa_id, int(sel_key[3:])) if r[0] == sel_key), None)
            if _reg:
                st.success(
                    f"✅ La provisión de este periodo ya fue **registrada** el "
                    f"{_reg[4].strftime('%d/%m/%Y %H:%M') if _reg[4] else '—'}: gratificación "
                    f"S/ {_reg[2]:,.2f} + bono extraordinario S/ {_reg[3]:,.2f} ({_reg[1]} trabajador(es))."
                )
            if not _pend and not _reg:
                st.success("✅ No hay provisión pendiente de contabilizar en este periodo.")
            elif _pend:
                _tot_g = sum(f["delta_grati"] for f in _pend)
                _tot_b = sum(f["delta_bono"] for f in _pend)
                c1, c2, c3 = st.columns(3)
                c1.metric("Gratificación a provisionar", f"S/ {_tot_g:,.2f}")
                c2.metric("Bono extraordinario", f"S/ {_tot_b:,.2f}")
                c3.metric("Total del mes", f"S/ {_tot_g + _tot_b:,.2f}")
                with st.expander(f"Detalle por trabajador ({len(_pend)})"):
                    st.dataframe(
                        pd.DataFrame([{
                            "DNI": f["dni"], "Trabajador": f["nombre"],
                            "Base computable": f["base_computable"], "Meses": f["meses_computados"],
                            "Acumulado objetivo": round(f["objetivo_grati"] + f["objetivo_bono"], 2),
                            "Ya provisionado": f["ya_provisionado"], "A provisionar": f["delta_total"],
                        } for f in _pend]),
                        use_container_width=True, hide_index=True,
                    )
                _etq_btn = ("🔁 Regenerar Provisión (reemplaza la ya registrada)" if _reg
                            else "📈 Generar Provisión y Registrarla (Excel)")
                if st.button(_etq_btn, type="primary",
                             use_container_width=True, key="btn_gen_provision"):
                    try:
                        with st.spinner("Armando el asiento de provisión..."):
                            buf_prov = _pg.generar_asiento_provision(
                                db, empresa_id, sel_key, generado_por=st.session_state.get('usuario_logueado'))
                        st.success("✅ Provisión registrada y asiento cuadrado (Debe = Haber).")
                        st.download_button(
                            f"📥 Descargar PROVISION_GRATI_{sel_key}.xlsx", data=buf_prov,
                            file_name=f"ASIENTO_PROVISION_GRATI_{sel_key}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True, key="dl_provision",
                        )
                    except _ACE as _e_prov:
                        if _e_prov.cuentas_faltantes:
                            st.error(f"⚠️ **No se puede generar la provisión** — {_e_prov.mensaje}")
                            for _c in _e_prov.cuentas_faltantes:
                                st.markdown(f"- {_c}")
                            st.info("Vaya a **Configuración Contable** para completar las cuentas y vuelva a intentarlo.")
                        else:
                            st.warning(f"ℹ️ {_e_prov.mensaje}")
                    except Exception as _e_prov2:
                        st.error(f"Error inesperado al generar la provisión: {_e_prov2}")

        # ── Provisión mensual de vacaciones ────────────────────────────────────────
        from core.use_cases import provision_vacaciones as _pv
        st.markdown("---")
        st.markdown("### 🏖️ Provisión Mensual de Vacaciones")
        st.caption(
            "Provisiona cada mes el valor de las vacaciones devengadas y no gozadas (días del Kardex × "
            "sueldo/30). Las vacaciones gozadas se cancelan contra este pasivo en el asiento de planilla y "
            "las vacaciones truncas en la liquidación. **El primer mes (julio 2026) registra de golpe todo el "
            "saldo acumulado** (ajuste de corte). Se registran en orden, mes a mes. "
            f"🔧 `{_pv.VERSION_PROVISION_VAC}`"
        )
        if not _pv.es_provisionable(sel_key):
            st.info(f"ℹ️ {_pv.motivo_no_provisionable(sel_key)}")
        elif estado_sel != "CERRADA":
            st.info("ℹ️ La provisión solo está disponible para periodos **cerrados**.")
        else:
            try:
                _prev_v = _pv.calcular_provision_mes(db, empresa_id, sel_key)
            except _ACE as _e_prev_v:
                st.warning(f"ℹ️ {_e_prev_v.mensaje}")
                _prev_v = []
            _pend_v = [f for f in _prev_v if abs(f["delta"]) > 0.004]
            _reg_v = next((r for r in _pv.resumen_libro(db, empresa_id, int(sel_key[3:])) if r[0] == sel_key), None)
            if _reg_v:
                st.success(
                    f"✅ La provisión de vacaciones de este periodo ya fue **registrada** el "
                    f"{_reg_v[4].strftime('%d/%m/%Y %H:%M') if _reg_v[4] else '—'}: "
                    f"S/ {_reg_v[2]:,.2f} del mes · saldo total S/ {_reg_v[3]:,.2f} ({_reg_v[1]} trabajador(es))."
                )
            if not _pend_v and not _reg_v:
                st.success("✅ No hay provisión de vacaciones pendiente en este periodo.")
            elif _pend_v:
                _tot_v = sum(f["delta"] for f in _pend_v)
                _can_v = sum(f["cancelado"] for f in _pend_v)
                v1, v2 = st.columns(2)
                v1.metric("Vacaciones a provisionar", f"S/ {_tot_v:,.2f}")
                v2.metric("Gozadas (cancelan pasivo)", f"S/ {_can_v:,.2f}")
                with st.expander(f"Detalle por trabajador ({len(_pend_v)})"):
                    st.dataframe(
                        pd.DataFrame([{
                            "DNI": f["dni"], "Trabajador": f["nombre"], "Días devengados no gozados": f["dias_saldo"],
                            "Rem. diaria": f["remuneracion_diaria"], "Saldo objetivo": f["objetivo"],
                            "Saldo previo": f["saldo_previo"], "Gozadas": f["cancelado"], "A provisionar": f["delta"],
                        } for f in _pend_v]),
                        use_container_width=True, hide_index=True,
                    )
                _etq_v = ("🔁 Regenerar Provisión de Vacaciones (reemplaza la ya registrada)" if _reg_v
                          else "🏖️ Generar Provisión de Vacaciones y Registrarla (Excel)")
                if st.button(_etq_v, type="primary", use_container_width=True, key="btn_gen_provision_vac"):
                    try:
                        with st.spinner("Armando el asiento de provisión de vacaciones..."):
                            buf_pv = _pv.generar_asiento_provision(
                                db, empresa_id, sel_key, generado_por=st.session_state.get('usuario_logueado'))
                        st.success("✅ Provisión de vacaciones registrada y asiento cuadrado (Debe = Haber).")
                        st.download_button(
                            f"📥 Descargar PROVISION_VAC_{sel_key}.xlsx", data=buf_pv,
                            file_name=f"ASIENTO_PROVISION_VAC_{sel_key}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True, key="dl_provision_vac",
                        )
                    except _ACE as _e_pv:
                        if _e_pv.cuentas_faltantes:
                            st.error(f"⚠️ **No se puede generar la provisión de vacaciones** — {_e_pv.mensaje}")
                            for _c in _e_pv.cuentas_faltantes:
                                st.markdown(f"- {_c}")
                            st.info("Vaya a **Configuración Contable** para completar las cuentas y vuelva a intentarlo.")
                        else:
                            st.warning(f"ℹ️ {_e_pv.mensaje}")
                    except Exception as _e_pv2:
                        st.error(f"Error inesperado al generar la provisión de vacaciones: {_e_pv2}")

        # ── Provisión mensual de CTS ───────────────────────────────────────────────
        from core.use_cases import provision_cts as _pc
        st.markdown("---")
        st.markdown("### 💼 Provisión Mensual de CTS")
        st.caption(
            "Provisiona cada mes la CTS **al corte**: lo que se pagaría si el trabajador cesara el último día "
            "del mes, calculado con el mismo motor de la liquidación (remuneración variable solo si se percibió en "
            "≥ 3 meses del semestre; no se proyecta el futuro). **Julio 2026 registra de golpe lo devengado del "
            "periodo MAY-OCT** (ajuste de corte). En mayo y noviembre se ajusta contra el **depósito real** y empieza "
            f"el periodo nuevo. 🔧 `{_pc.VERSION_PROVISION_CTS}`"
        )
        if not _pc.es_provisionable(sel_key):
            st.info(f"ℹ️ {_pc.motivo_no_provisionable(sel_key)}")
        elif estado_sel != "CERRADA":
            st.info("ℹ️ La provisión solo está disponible para periodos **cerrados**.")
        else:
            try:
                _prev_c = _pc.calcular_provision_mes(db, empresa_id, sel_key)
            except _ACE as _e_prev_c:
                st.warning(f"ℹ️ {_e_prev_c.mensaje}")
                _prev_c = []
            _pend_c = [f for f in _prev_c if abs(f["delta_provision"]) > 0.004 or abs(f["delta_ajuste"]) > 0.004]
            _reg_c = next((r for r in _pc.resumen_libro(db, empresa_id, int(sel_key[3:])) if r[0] == sel_key), None)
            if _reg_c:
                st.success(
                    f"✅ La provisión de CTS de este periodo ya fue **registrada** el "
                    f"{_reg_c[4].strftime('%d/%m/%Y %H:%M') if _reg_c[4] else '—'}: provisión S/ {_reg_c[2]:,.2f}"
                    f" · ajuste por depósito S/ {_reg_c[3]:,.2f} ({_reg_c[1]} trabajador(es))."
                )
            if not _pend_c and not _reg_c:
                st.success("✅ No hay provisión de CTS pendiente en este periodo.")
            elif _pend_c:
                c1, c2, c3 = st.columns(3)
                c1.metric("CTS a provisionar", f"S/ {sum(f['delta_provision'] for f in _pend_c):,.2f}")
                c2.metric("Ajuste por depósito", f"S/ {sum(f['delta_ajuste'] for f in _pend_c):,.2f}")
                c3.metric("Total CTS del mes", f"S/ {sum(f['delta_total'] for f in _pend_c):,.2f}")
                with st.expander(f"Detalle por trabajador ({len(_pend_c)})"):
                    st.dataframe(
                        pd.DataFrame([{
                            "DNI": f["dni"], "Trabajador": f["nombre"], "Periodo CTS": f["periodo_cts"],
                            "Base CTS": f["base_cts"], "Meses": f["meses"], "CTS al corte": f["objetivo"],
                            "Ya provisionado": f["ya_provisionado"], "A provisionar": f["delta_provision"],
                            "Depósito real": f["deposito"], "Ajuste": f["delta_ajuste"],
                        } for f in _pend_c]),
                        use_container_width=True, hide_index=True,
                    )
                _etq_c = ("🔁 Regenerar Provisión de CTS (reemplaza la ya registrada)" if _reg_c
                          else "💼 Generar Provisión de CTS y Registrarla (Excel)")
                if st.button(_etq_c, type="primary", use_container_width=True, key="btn_gen_provision_cts"):
                    try:
                        with st.spinner("Armando el asiento de provisión de CTS..."):
                            buf_pc = _pc.generar_asiento_provision(
                                db, empresa_id, sel_key, generado_por=st.session_state.get('usuario_logueado'))
                        st.success("✅ Provisión de CTS registrada y asiento cuadrado (Debe = Haber).")
                        st.download_button(
                            f"📥 Descargar PROVISION_CTS_{sel_key}.xlsx", data=buf_pc,
                            file_name=f"ASIENTO_PROVISION_CTS_{sel_key}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True, key="dl_provision_cts",
                        )
                    except _ACE as _e_pc:
                        if _e_pc.cuentas_faltantes:
                            st.error(f"⚠️ **No se puede generar la provisión de CTS** — {_e_pc.mensaje}")
                            for _c in _e_pc.cuentas_faltantes:
                                st.markdown(f"- {_c}")
                            st.info("Vaya a **Configuración Contable** para completar las cuentas y vuelva a intentarlo.")
                        else:
                            st.warning(f"ℹ️ {_e_pc.mensaje}")
                    except Exception as _e_pc2:
                        st.error(f"Error inesperado al generar la provisión de CTS: {_e_pc2}")

        _libro_c = _pc.resumen_libro(db, empresa_id, int(sel_key[3:]))
        if _libro_c:
            with st.expander(f"📚 Provisiones de CTS registradas en {sel_key[3:]}"):
                st.dataframe(
                    pd.DataFrame([{
                        "Periodo": p, "Trabajadores": n, "Provisión": a, "Ajuste por depósito": b,
                        "Registrada": fch.strftime('%d/%m/%Y %H:%M') if fch else "",
                    } for p, n, a, b, fch in _libro_c]),
                    use_container_width=True, hide_index=True,
                )

        _libro_v = _pv.resumen_libro(db, empresa_id, int(sel_key[3:]))
        if _libro_v:
            with st.expander(f"📚 Provisiones de vacaciones registradas en {sel_key[3:]}"):
                st.dataframe(
                    pd.DataFrame([{
                        "Periodo": p, "Trabajadores": n, "Provisión del mes": a, "Saldo total": s_,
                        "Registrada": fch.strftime('%d/%m/%Y %H:%M') if fch else "",
                    } for p, n, a, s_, fch in _libro_v]),
                    use_container_width=True, hide_index=True,
                )

        _libro = _pg.resumen_libro(db, empresa_id, int(sel_key[3:]))
        if _libro:
            with st.expander(f"📚 Provisiones ya registradas en {sel_key[3:]}"):
                st.dataframe(
                    pd.DataFrame([{
                        "Periodo": p, "Trabajadores": n, "Gratificación": g, "Bono extraordinario": b,
                        "Registrada": fch.strftime('%d/%m/%Y %H:%M') if fch else "",
                    } for p, n, g, b, fch in _libro]),
                    use_container_width=True, hide_index=True,
                )

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
                # LECTURA DE SNAPSHOT
                hon_json_str = getattr(planilla_sel, 'honorarios_json', '[]') or '[]'
                df_base_p = pd.read_json(io.StringIO(hon_json_str), orient='records')
                if df_base_p is None:
                    df_base_p = pd.DataFrame()
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

