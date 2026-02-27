import json
import streamlit as st
import pandas as pd
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
        trabajadores = db.query(Trabajador).filter_by(empresa_id=empresa_id, situacion="ACTIVO").all()
        if not trabajadores:
            st.warning("No hay trabajadores activos. Vaya al Maestro de Personal.")
            return

        conceptos       = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
        conceptos_ing   = [c for c in conceptos if c.tipo == "INGRESO"   and c.nombre not in CONCEPTOS_FIJOS]
        conceptos_desc  = [c for c in conceptos if c.tipo == "DESCUENTO"]

        variables_exist = {
            v.trabajador_id: v
            for v in db.query(VariablesMes).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).all()
        }

        conceptos_vals = {}
        for t in trabajadores:
            v = variables_exist.get(t.id)
            conceptos_vals[t.id] = json.loads(v.conceptos_json) if v else {}

        # Verificar si el periodo está cerrado
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

        ids    = [t.id    for t in trabajadores]
        docs   = [t.num_doc for t in trabajadores]
        nombres = [t.nombres for t in trabajadores]

        def get_v(t_id, field, default):
            v = variables_exist.get(t_id)
            return getattr(v, field, default) if v else default

        def get_susp(t_id, cod):
            v = variables_exist.get(t_id)
            if v:
                susp = json.loads(getattr(v, 'suspensiones_json', '{}') or '{}')
                # Fallback a dias_faltados en código 07 si suspensiones vacío
                if not susp and cod == "07":
                    return getattr(v, 'dias_faltados', 0) or 0
                return susp.get(cod, 0)
            return 0

        # ── SECCIÓN A: TIEMPOS ────────────────────────────────────────────────
        df_t_data: dict = {
            "Trabajador_ID":       ids,
            "Num. Doc.":           docs,
            "Nombres y Apellidos": nombres,
        }
        for cod, etq in SUSPENSIONES_GRILLA:
            df_t_data[etq] = [get_susp(t.id, cod) for t in trabajadores]
        df_t_data["Min. Tardanza"]  = [get_v(t.id, 'min_tardanza', 0)    for t in trabajadores]
        df_t_data["Hrs Extras 25%"] = [get_v(t.id, 'hrs_extras_25', 0.0) for t in trabajadores]
        df_t_data["Hrs Extras 35%"] = [get_v(t.id, 'hrs_extras_35', 0.0) for t in trabajadores]
        df_tiempos = pd.DataFrame(df_t_data)

        # ── SECCIÓN B: INGRESOS VARIABLES ─────────────────────────────────────
        dict_i = {"Num. Doc.": docs, "Nombres y Apellidos": nombres,
                  "Sueldo Base": [t.sueldo_base for t in trabajadores],
                  "Asig. Fam.": ["Sí" if t.asig_fam else "No" for t in trabajadores]}
        for c in conceptos_ing:
            dict_i[c.nombre] = [conceptos_vals[t.id].get(c.nombre, 0.0) for t in trabajadores]
        df_ingresos = pd.DataFrame(dict_i)

        # ── SECCIÓN C: DESCUENTOS ─────────────────────────────────────────────
        dict_d = {"Num. Doc.": docs, "Nombres y Apellidos": nombres}
        for c in conceptos_desc:
            dict_d[c.nombre] = [conceptos_vals[t.id].get(c.nombre, 0.0) for t in trabajadores]
        df_descuentos = pd.DataFrame(dict_d)

        doc_to_id = {t.num_doc: t.id for t in trabajadores}

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
                    doc    = fila_t["Num. Doc."]
                    trab_id = doc_to_id.get(doc)
                    if not trab_id:
                        continue

                    # Construir suspensiones_json desde columnas de grilla
                    susp_dict = _suspensiones_from_row(fila_t)
                    total_falt = susp_dict.get("07", 0)   # para campo legado dias_faltados

                    # Conceptos dinámicos
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
                        v_exist.dias_faltados   = total_falt
                        v_exist.min_tardanza    = int(fila_t["Min. Tardanza"] or 0)
                        v_exist.hrs_extras_25   = float(fila_t["Hrs Extras 25%"] or 0.0)
                        v_exist.hrs_extras_35   = float(fila_t["Hrs Extras 35%"] or 0.0)
                        v_exist.suspensiones_json = json.dumps(susp_dict)
                        v_exist.conceptos_json  = json.dumps(conceptos_data)
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
                st.success(f"Variables de **{periodo_key}** guardadas correctamente.")
                st.rerun()
            except Exception as e:
                db.rollback()
                st.error(f"Error al guardar: {e}")

    finally:
        db.close()
