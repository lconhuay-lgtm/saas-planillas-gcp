import json
import streamlit as st
import pandas as pd
from sqlalchemy import or_
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Trabajador, Concepto, VariablesMes, PlanillaMensual
from core.domain.catalogos_sunat import CATALOGO_T21_SUSPENSIONES

MESES = ["01 - Enero", "02 - Febrero", "03 - Marzo", "04 - Abril", "05 - Mayo", "06 - Junio",
         "07 - Julio", "08 - Agosto", "09 - Septiembre", "10 - Octubre", "11 - Noviembre", "12 - Diciembre"]

CONCEPTOS_FIJOS = {"SUELDO BASICO", "ASIGNACION FAMILIAR"}

# Suspensiones que se muestran como columnas directas en la grilla de tiempos
# Formato: (codigo_sunat, etiqueta_columna)
SUSPENSIONES_GRILLA = [
    ("07", "Faltas Injust. (07)"),
    ("20", "Desc. Médico (20)"),
    ("23", "Vacaciones (23)"),
    ("16", "Lic. s/Haber (16)"),
]
_COL_A_COD = {etq: cod for cod, etq in SUSPENSIONES_GRILLA}


def _suspensiones_from_row(row) -> dict:
    """Convierte columnas de la fila de edición a dict suspensiones_json."""
    result = {}
    for cod, etq in SUSPENSIONES_GRILLA:
        val = int(row.get(etq, 0) or 0)
        if val > 0:
            result[cod] = val
    return result


def _total_ausencias(susp: dict) -> int:
    return sum(susp.values())


def render():
    empresa_id     = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')
    if not empresa_id:
        st.error("Acceso denegado. Seleccione una empresa.")
        return

    st.title("Ingreso de Asistencias y Variables")
    st.markdown(f"**Empresa:** {empresa_nombre}")

    col_m, col_a = st.columns([2, 1])
    mes_sel  = col_m.selectbox("Mes", MESES, key="asis_mes")
    anio_sel = col_a.selectbox("Año", [2025, 2026, 2027, 2028], index=1, key="asis_anio")
    periodo_key = f"{mes_sel[:2]}-{anio_sel}"
    st.markdown("---")

    db = SessionLocal()
    try:
        # ── Separar empleados de planilla y locadores ─────────────────────────
        planilleros = (
            db.query(Trabajador)
            .filter_by(empresa_id=empresa_id, situacion="ACTIVO")
            .filter(or_(Trabajador.tipo_contrato == 'PLANILLA', Trabajador.tipo_contrato == None))
            .all()
        )
        locadores = (
            db.query(Trabajador)
            .filter_by(empresa_id=empresa_id, situacion="ACTIVO", tipo_contrato='LOCADOR')
            .all()
        )

        # Fix 5: Excluir trabajadores que ingresan DESPUÉS del periodo seleccionado
        _mes_asis  = int(mes_sel[:2])
        _anio_asis = int(anio_sel)

        def _activo_en_periodo(t):
            if not t.fecha_ingreso:
                return True
            fi = t.fecha_ingreso
            return not (fi.year > _anio_asis or (fi.year == _anio_asis and fi.month > _mes_asis))

        planilleros = [t for t in planilleros if _activo_en_periodo(t)]
        locadores   = [t for t in locadores   if _activo_en_periodo(t)]

        # Conceptos dinámicos de la empresa (para planilla)
        conceptos      = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
        conceptos_ing  = [c for c in conceptos if c.tipo == "INGRESO"  and c.nombre not in CONCEPTOS_FIJOS]
        conceptos_desc = [c for c in conceptos if c.tipo == "DESCUENTO"]

        # Variables del periodo (cubre planilleros y locadores)
        variables_exist = {
            v.trabajador_id: v
            for v in db.query(VariablesMes).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).all()
        }

        # Estado de cierre del periodo
        planilla_estado = db.query(PlanillaMensual).filter_by(
            empresa_id=empresa_id, periodo_key=periodo_key
        ).first()
        es_cerrada = planilla_estado is not None and getattr(planilla_estado, 'estado', 'ABIERTA') == 'CERRADA'

        if es_cerrada:
            st.error(f"🔒 El periodo **{periodo_key}** está CERRADO. Los datos mostrados son de solo lectura. Solicite a un Supervisor que reabra la planilla si necesita hacer modificaciones.")
        elif variables_exist:
            st.info(f"Datos previos cargados para **{periodo_key}**.")
        else:
            st.success(f"Nueva hoja de variables para **{periodo_key}**.")

        # Mostrar mensajes de éxito diferidos (tras rerun)
        if st.session_state.get('_msg_asistencia'):
            st.toast(st.session_state.pop('_msg_asistencia'), icon="✅")

        # ── Cuatro pestañas principales (Estándar Corporativo) ──────────────────
        usuario_rol = st.session_state.get('usuario_rol', '')
        es_supervisor = usuario_rol in ['supervisor', 'admin']

        tabs_list = [
            "📋 1. Planilla (5ta Cat.)",
            "🧾 2. Locadores (4ta Cat.)",
            "📝 3. Notas de Gestión"
        ]
        if es_supervisor:
            tabs_list.append("🔧 4. Ajustes de Auditoría")

        tabs = st.tabs(tabs_list)
        tab_plan = tabs[0]
        tab_loc = tabs[1]
        tab_notas = tabs[2]

        # ══════════════════════════════════════════════════════════════════════
        # TAB 1 — PLANILLA DE EMPLEADOS
        # ══════════════════════════════════════════════════════════════════════
        with tab_plan:
            # Aviso obligatorio si hay locadores sin asistencia guardada para este periodo
            if locadores and not es_cerrada:
                loc_sin_vars = [l for l in locadores if l.id not in variables_exist]
                if loc_sin_vars:
                    st.warning(
                        f"⚠️ **PASO OBLIGATORIO:** Hay **{len(locadores)}** locador(es) de servicio "
                        f"registrado(s). Después de guardar esta pestaña, guarde también la pestaña "
                        f"**'🧾 2. Valorización de Locadores'** antes de ejecutar el Cálculo de Planilla."
                    )
            if not planilleros:
                st.info("No hay empleados de planilla activos. Registre trabajadores con tipo 'Planilla (5ta Categoría)' en el Maestro de Personal.")
            else:
                conceptos_vals = {}
                for t in planilleros:
                    v = variables_exist.get(t.id)
                    conceptos_vals[t.id] = json.loads(v.conceptos_json) if v else {}

                def get_v(t_id, field, default):
                    v = variables_exist.get(t_id)
                    return getattr(v, field, default) if v else default

                def get_susp(t_id, cod):
                    v = variables_exist.get(t_id)
                    if v:
                        susp = json.loads(getattr(v, 'suspensiones_json', '{}') or '{}')
                        if not susp and cod == "07":
                            return getattr(v, 'dias_faltados', 0) or 0
                        return susp.get(cod, 0)
                    return 0

                ids     = [t.id      for t in planilleros]
                docs    = [t.num_doc for t in planilleros]
                nombres = [t.nombres for t in planilleros]

                # ── Sección A: TIEMPOS ────────────────────────────────────────
                df_t_data: dict = {
                    "Trabajador_ID":       ids,
                    "Num. Doc.":           docs,
                    "Nombres y Apellidos": nombres,
                }
                for cod, etq in SUSPENSIONES_GRILLA:
                    df_t_data[etq] = [get_susp(t.id, cod) for t in planilleros]
                df_t_data["Min. Tardanza"]  = [get_v(t.id, 'min_tardanza', 0)    for t in planilleros]
                df_t_data["Hrs Extras 25%"] = [get_v(t.id, 'hrs_extras_25', 0.0) for t in planilleros]
                df_t_data["Hrs Extras 35%"] = [get_v(t.id, 'hrs_extras_35', 0.0) for t in planilleros]
                df_tiempos = pd.DataFrame(df_t_data)

                # ── Sección B: INGRESOS VARIABLES ─────────────────────────────
                dict_i = {"Num. Doc.": docs, "Nombres y Apellidos": nombres,
                          "Sueldo Base": [t.sueldo_base for t in planilleros],
                          "Asig. Fam.": ["Sí" if t.asig_fam else "No" for t in planilleros]}
                for c in conceptos_ing:
                    dict_i[c.nombre] = [conceptos_vals[t.id].get(c.nombre, 0.0) for t in planilleros]
                df_ingresos = pd.DataFrame(dict_i)

                # ── Sección C: DESCUENTOS ─────────────────────────────────────
                dict_d = {"Num. Doc.": docs, "Nombres y Apellidos": nombres}
                for c in conceptos_desc:
                    dict_d[c.nombre] = [conceptos_vals[t.id].get(c.nombre, 0.0) for t in planilleros]
                df_descuentos = pd.DataFrame(dict_d)

                doc_to_id = {t.num_doc: t.id for t in planilleros}

                col_cfg_t = {"Trabajador_ID": None,
                             "Min. Tardanza":  st.column_config.NumberColumn(min_value=0, step=1),
                             "Hrs Extras 25%": st.column_config.NumberColumn(min_value=0.0, step=0.5, format="%.1f"),
                             "Hrs Extras 35%": st.column_config.NumberColumn(min_value=0.0, step=0.5, format="%.1f")}
                for _, etq in SUSPENSIONES_GRILLA:
                    col_cfg_t[etq] = st.column_config.NumberColumn(min_value=0, max_value=31, step=1,
                                                                    help=f"Código SUNAT: {_COL_A_COD[etq]}")

                col_cfg_ing  = {c.nombre: st.column_config.NumberColumn(
                                    label=c.nombre, min_value=0.0, step=0.01, format="S/ %.2f")
                                for c in conceptos_ing}
                col_cfg_desc = {c.nombre: st.column_config.NumberColumn(
                                    label=c.nombre, min_value=0.0, step=0.01, format="S/ %.2f")
                                for c in conceptos_desc}

                tab_t, tab_i, tab_d = st.tabs(["Tiempos y Asistencias", "Ingresos Variables", "Descuentos Directos"])

                with tab_t:
                    st.caption(
                        "**Tipos de suspensión SUNAT** — Faltas Injust.(07) · Desc.Médico(20) · "
                        "Vacaciones(23) · Lic.s/Haber(16). Para otros tipos use el campo libre abajo."
                    )
                    df_t_edit = st.data_editor(
                        df_tiempos,
                        disabled=True if es_cerrada else ["Num. Doc.", "Nombres y Apellidos"],
                        num_rows="fixed", use_container_width=True, hide_index=True,
                        column_config=col_cfg_t, key="ed_tiempos",
                    )
                    if not es_cerrada:
                        st.markdown("**Suspensiones adicionales** (código libre Tabla 21 SUNAT):")
                        col_aux1, col_aux2 = st.columns([1, 3])
                        with col_aux1:
                            opciones_susp = [f"{k} — {v}" for k, v in sorted(CATALOGO_T21_SUSPENSIONES.items())]
                            cod_extra = st.selectbox("Tipo adicional:", opciones_susp, key="susp_extra_cod")
                        with col_aux2:
                            st.caption("Días para este tipo se ingresarán en la grilla como columna extra en el próximo guardado.")

                with tab_i:
                    df_i_edit = st.data_editor(
                        df_ingresos,
                        disabled=True if es_cerrada else ["Num. Doc.", "Nombres y Apellidos", "Sueldo Base", "Asig. Fam."],
                        num_rows="fixed", use_container_width=True, hide_index=True,
                        column_config=col_cfg_ing, key="ed_ingresos",
                    )

                with tab_d:
                    if not conceptos_desc:
                        st.info("No hay conceptos de descuento. Agrégelos en el Maestro de Conceptos.")
                        df_d_edit = df_descuentos
                    else:
                        df_d_edit = st.data_editor(
                            df_descuentos,
                            disabled=True if es_cerrada else ["Num. Doc.", "Nombres y Apellidos"],
                            num_rows="fixed", use_container_width=True, hide_index=True,
                            column_config=col_cfg_desc, key="ed_descuentos",
                        )

                st.markdown("---")

                if not es_cerrada and st.button(f"Guardar Variables de {periodo_key}", type="primary", use_container_width=True):
                    try:
                        for _, fila_t in df_t_edit.iterrows():
                            doc     = fila_t["Num. Doc."]
                            trab_id = doc_to_id.get(doc)
                            if not trab_id:
                                continue

                            susp_dict  = _suspensiones_from_row(fila_t)
                            total_falt = susp_dict.get("07", 0)

                            conceptos_data: dict = {}
                            filas_i = df_i_edit[df_i_edit["Num. Doc."] == doc]
                            if not filas_i.empty:
                                fila_i = filas_i.iloc[0]
                                for c in conceptos_ing:
                                    val = float(fila_i.get(c.nombre, 0.0) or 0.0)
                                    if val > 0:
                                        conceptos_data[c.nombre] = val

                            if not df_d_edit.empty and "Num. Doc." in df_d_edit.columns:
                                filas_d = df_d_edit[df_d_edit["Num. Doc."] == doc]
                                if not filas_d.empty:
                                    fila_d = filas_d.iloc[0]
                                    for c in conceptos_desc:
                                        val = float(fila_d.get(c.nombre, 0.0) or 0.0)
                                        if val > 0:
                                            conceptos_data[c.nombre] = val

                            v_exist = variables_exist.get(trab_id)
                            if v_exist:
                                v_exist.dias_faltados    = total_falt
                                v_exist.min_tardanza     = int(fila_t["Min. Tardanza"] or 0)
                                v_exist.hrs_extras_25    = float(fila_t["Hrs Extras 25%"] or 0.0)
                                v_exist.hrs_extras_35    = float(fila_t["Hrs Extras 35%"] or 0.0)
                                v_exist.suspensiones_json = json.dumps(susp_dict)
                                v_exist.conceptos_json   = json.dumps(conceptos_data)
                            else:
                                db.add(VariablesMes(
                                    empresa_id=empresa_id, trabajador_id=trab_id, periodo_key=periodo_key,
                                    dias_faltados=total_falt,
                                    min_tardanza=int(fila_t["Min. Tardanza"] or 0),
                                    hrs_extras_25=float(fila_t["Hrs Extras 25%"] or 0.0),
                                    hrs_extras_35=float(fila_t["Hrs Extras 35%"] or 0.0),
                                    suspensiones_json=json.dumps(susp_dict),
                                    conceptos_json=json.dumps(conceptos_data),
                                ))

                        db.commit()
                        st.session_state['_msg_asistencia'] = f"Variables de Planilla ({periodo_key}) guardadas con éxito."
                        st.rerun()
                    except Exception as e:
                        db.rollback()
                        st.error(f"Error al guardar: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # TAB 2 — VALORIZACIÓN DE LOCADORES
        # ══════════════════════════════════════════════════════════════════════
        with tab_loc:
            if not locadores:
                st.info("No hay locadores de servicio activos. Registre trabajadores con tipo 'Locador de Servicio (4ta Categoría)' en el Maestro de Personal.")
            else:
                loc_ids      = [l.id        for l in locadores]
                loc_docs     = [l.num_doc   for l in locadores]
                loc_nombres  = [l.nombres   for l in locadores]
                loc_hon      = [l.sueldo_base for l in locadores]
                doc_to_loc_id = {l.num_doc: l.id for l in locadores}

                def get_loc_v(t_id, field, default):
                    v = variables_exist.get(t_id)
                    return getattr(v, field, default) if v else default

                def get_loc_concepto(t_id, key):
                    v = variables_exist.get(t_id)
                    if v:
                        c = json.loads(v.conceptos_json or '{}')
                        return float(c.get(key, 0.0))
                    return 0.0

                df_loc = pd.DataFrame({
                    "Trabajador_ID":                  loc_ids,
                    "Num. Doc.":                      loc_docs,
                    "Nombres y Apellidos":             loc_nombres,
                    "Honorario Base (S/)":             loc_hon,
                    "Días no prestados":               [get_loc_v(lid, 'dias_descuento_locador', 0) for lid in loc_ids],
                    "Otros Pagos / Bonos":             [get_loc_concepto(lid, '_otros_pagos_loc') for lid in loc_ids],
                    "Otros Descuentos / Penalidades":  [get_loc_concepto(lid, '_otros_descuentos_loc') for lid in loc_ids],
                })

                col_cfg_loc = {
                    "Trabajador_ID": None,
                    "Días no prestados": st.column_config.NumberColumn(min_value=0, max_value=31, step=1),
                    "Otros Pagos / Bonos": st.column_config.NumberColumn(min_value=0.0, step=0.01, format="S/ %.2f"),
                    "Otros Descuentos / Penalidades": st.column_config.NumberColumn(min_value=0.0, step=0.01, format="S/ %.2f"),
                }

                st.caption("Ingrese los días no prestados y los pagos/descuentos adicionales. El cálculo de retención (8%) se ejecuta en el módulo **Cálculo de Planilla**.")
                df_loc_edit = st.data_editor(
                    df_loc,
                    disabled=True if es_cerrada else ["Num. Doc.", "Nombres y Apellidos", "Honorario Base (S/)"],
                    column_config=col_cfg_loc,
                    num_rows="fixed", use_container_width=True, hide_index=True,
                    key="ed_locadores",
                )

                st.markdown("---")

                if not es_cerrada and st.button(
                    f"Guardar Valorizaciones de Locadores — {periodo_key}",
                    type="primary", use_container_width=True,
                ):
                    try:
                        for _, fila in df_loc_edit.iterrows():
                            doc     = fila["Num. Doc."]
                            trab_id = doc_to_loc_id.get(doc)
                            if not trab_id:
                                continue

                            dias         = int(fila.get("Días no prestados", 0) or 0)
                            otros_pagos  = float(fila.get("Otros Pagos / Bonos", 0.0) or 0.0)
                            otros_dsctos = float(fila.get("Otros Descuentos / Penalidades", 0.0) or 0.0)

                            conceptos_data: dict = {}
                            if otros_pagos  > 0: conceptos_data['_otros_pagos_loc']      = otros_pagos
                            if otros_dsctos > 0: conceptos_data['_otros_descuentos_loc'] = otros_dsctos

                            v_exist = variables_exist.get(trab_id)
                            if v_exist:
                                v_exist.dias_descuento_locador = dias
                                v_exist.conceptos_json = json.dumps(conceptos_data)
                            else:
                                db.add(VariablesMes(
                                    empresa_id=empresa_id,
                                    trabajador_id=trab_id,
                                    periodo_key=periodo_key,
                                    dias_descuento_locador=dias,
                                    conceptos_json=json.dumps(conceptos_data),
                                ))

                        db.commit()
                        st.session_state['_msg_asistencia'] = f"Valorizaciones de Locadores ({periodo_key}) guardadas con éxito."
                        st.rerun()
                    except Exception as e:
                        db.rollback()
                        st.error(f"Error al guardar: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # TAB 3 — NOTAS DE GESTIÓN (SAP/ORACLE STYLE)
        # ══════════════════════════════════════════════════════════════════════
        with tab_notas:
            st.subheader("📝 Anotaciones Ejecutivas para Tesorería")
            st.info("Estas notas aparecerán estrictamente en el Reporte de Tesorería y Boletas de Pago como información oficial de gestión.")
            
            todos = planilleros + locadores
            if not todos:
                st.info("No hay personal activo para registrar notas.")
            else:
                df_notas_data = []
                for t in todos:
                    v = variables_exist.get(t.id)
                    df_notas_data.append({
                        "ID": t.id,
                        "Personal": f"{t.nombres} ({'Planilla' if t.tipo_contrato != 'LOCADOR' else 'Locador'})",
                        "Notas de Gestión / Observación Manual": getattr(v, 'notas_gestion', '') or ''
                    })
                
                df_n = pd.DataFrame(df_notas_data)
                df_n_edit = st.data_editor(
                    df_n,
                    column_config={
                        "ID": None,
                        "Personal": st.column_config.TextColumn(disabled=True, width="medium"),
                        "Notas de Gestión / Observación Manual": st.column_config.TextColumn(width="large")
                    },
                    hide_index=True, use_container_width=True, key="ed_notas_gestion",
                    disabled=True if es_cerrada else False
                )

                if not es_cerrada and st.button("💾 Guardar Notas de Gestión", type="primary", use_container_width=True):
                    try:
                        for _, fila in df_n_edit.iterrows():
                            tid = fila["ID"]
                            txt = fila["Notas de Gestión / Observación Manual"]
                            v_ex = variables_exist.get(tid)
                            if v_ex:
                                v_ex.notas_gestion = txt
                            else:
                                db.add(VariablesMes(
                                    empresa_id=empresa_id, trabajador_id=tid, 
                                    periodo_key=periodo_key, notas_gestion=txt
                                ))
                        db.commit()
                        st.session_state['_msg_asistencia'] = "Notas de Gestión actualizadas correctamente."
                        st.rerun()
                    except Exception as e:
                        db.rollback()
                        st.error(f"Error: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # TAB 4 — AJUSTES DE AUDITORÍA (SAP/ORACLE STYLE)
        # ══════════════════════════════════════════════════════════════════════
        if es_supervisor:
            tab_ajustes = tabs[3]
            with tab_ajustes:
                st.subheader("🔧 Ajustes y Regularizaciones de Nómina")
                st.info("Utilice esta sección para ingresar montos manuales que regularicen errores de meses previos o sistemas externos. Estos montos afectan directamente al Neto a Pagar.")
                
                if not planilleros:
                    st.info("No hay personal en planilla para aplicar ajustes.")
                else:
                    df_ajustes_data = []
                    for t in planilleros:
                        v = variables_exist.get(t.id)
                        cj = json.loads(v.conceptos_json or '{}') if v else {}
                        df_ajustes_data.append({
                            "ID": t.id,
                            "Trabajador": t.nombres,
                            "Ajuste AFP (S/)": float(cj.get('_ajuste_afp', 0.0)),
                            "Ajuste Quinta Cat (S/)": float(cj.get('_ajuste_quinta', 0.0)),
                            "Otros Ajustes (S/)": float(cj.get('_ajuste_otros', 0.0))
                        })
                    
                    df_aj = pd.DataFrame(df_ajustes_data)
                    df_aj_edit = st.data_editor(
                        df_aj,
                        column_config={
                            "ID": None,
                            "Trabajador": st.column_config.TextColumn(disabled=True),
                            "Ajuste AFP (S/)": st.column_config.NumberColumn(format="%.2f"),
                            "Ajuste Quinta Cat (S/)": st.column_config.NumberColumn(format="%.2f"),
                            "Otros Ajustes (S/)": st.column_config.NumberColumn(format="%.2f")
                        },
                        hide_index=True, use_container_width=True, key="ed_ajustes_audit",
                        disabled=True if es_cerrada else False
                    )

                    if not es_cerrada and st.button("💾 Guardar Ajustes de Auditoría", type="primary", use_container_width=True):
                        try:
                            for _, fila in df_aj_edit.iterrows():
                                tid = fila["ID"]
                                v_ex = variables_exist.get(tid)
                                cj = json.loads(v_ex.conceptos_json or '{}') if v_ex else {}
                                
                                # Inyectar claves de ajuste en el JSON
                                cj['_ajuste_afp'] = float(fila["Ajuste AFP (S/)"] or 0.0)
                                cj['_ajuste_quinta'] = float(fila["Ajuste Quinta Cat (S/)"] or 0.0)
                                cj['_ajuste_otros'] = float(fila["Otros Ajustes (S/)"] or 0.0)
                                
                                if v_ex:
                                    v_ex.conceptos_json = json.dumps(cj)
                                else:
                                    db.add(VariablesMes(
                                        empresa_id=empresa_id, trabajador_id=tid, 
                                        periodo_key=periodo_key, conceptos_json=json.dumps(cj)
                                    ))
                            db.commit()
                            st.session_state['_msg_asistencia'] = "Ajustes de Auditoría guardados correctamente."
                            st.rerun()
                        except Exception as e:
                            db.rollback()
                            st.error(f"Error: {e}")

    finally:
        db.close()
