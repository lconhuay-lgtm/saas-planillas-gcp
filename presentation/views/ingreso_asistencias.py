import json
import streamlit as st
import pandas as pd
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Trabajador, Concepto, VariablesMes

MESES = ["01 - Enero", "02 - Febrero", "03 - Marzo", "04 - Abril", "05 - Mayo", "06 - Junio",
         "07 - Julio", "08 - Agosto", "09 - Septiembre", "10 - Octubre", "11 - Noviembre", "12 - Diciembre"]

CONCEPTOS_FIJOS = {"SUELDO BASICO", "ASIGNACION FAMILIAR"}


def render():
    empresa_id = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')

    if not empresa_id:
        st.error("Acceso denegado. Seleccione una empresa en el Dashboard.")
        return

    st.title("Ingreso de Asistencias y Variables")
    st.markdown(f"**Empresa:** {empresa_nombre}")

    col_m, col_a = st.columns([2, 1])
    mes_seleccionado = col_m.selectbox("Mes", MESES, key="asis_mes")
    anio_seleccionado = col_a.selectbox("Año", [2025, 2026, 2027, 2028], index=1, key="asis_anio")
    periodo_key = f"{mes_seleccionado[:2]}-{anio_seleccionado}"

    st.markdown("---")

    db = SessionLocal()
    try:
        # 1. Leer trabajadores activos de la BD
        trabajadores = (
            db.query(Trabajador)
            .filter_by(empresa_id=empresa_id, situacion="ACTIVO")
            .all()
        )
        if not trabajadores:
            st.warning("No hay trabajadores activos registrados. Vaya al Maestro de Personal.")
            return

        # 2. Leer conceptos de la empresa de la BD
        conceptos = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
        conceptos_ingresos = [c for c in conceptos if c.tipo == "INGRESO" and c.nombre not in CONCEPTOS_FIJOS]
        conceptos_descuentos = [c for c in conceptos if c.tipo == "DESCUENTO"]

        # 3. Leer variables existentes para este periodo desde la BD
        variables_existentes = {
            v.trabajador_id: v
            for v in db.query(VariablesMes).filter_by(
                empresa_id=empresa_id, periodo_key=periodo_key
            ).all()
        }

        # Pre-parsear JSON de conceptos dinámicos por trabajador
        conceptos_vals = {}
        for t in trabajadores:
            v = variables_existentes.get(t.id)
            conceptos_vals[t.id] = json.loads(v.conceptos_json) if v else {}

        hay_datos_previos = bool(variables_existentes)
        if hay_datos_previos:
            st.info(f"Datos previos cargados para el periodo **{periodo_key}**.")
        else:
            st.success(f"Nueva hoja de variables para el periodo **{periodo_key}**.")

        # 4. Construir DataFrames para los data_editor
        ids = [t.id for t in trabajadores]
        docs = [t.num_doc for t in trabajadores]
        nombres = [t.nombres for t in trabajadores]

        def get_v(t_id, field, default):
            v = variables_existentes.get(t_id)
            return getattr(v, field, default) if v else default

        # ─── SECCIÓN A: TIEMPOS ───────────────────────────────────────────
        df_tiempos = pd.DataFrame({
            "Trabajador_ID": ids,
            "Num. Doc.": docs,
            "Nombres y Apellidos": nombres,
            "Días Faltados": [get_v(t.id, 'dias_faltados', 0) for t in trabajadores],
            "Min. Tardanza": [get_v(t.id, 'min_tardanza', 0) for t in trabajadores],
            "Hrs Extras 25%": [get_v(t.id, 'hrs_extras_25', 0.0) for t in trabajadores],
            "Hrs Extras 35%": [get_v(t.id, 'hrs_extras_35', 0.0) for t in trabajadores],
        })

        # ─── SECCIÓN B: INGRESOS VARIABLES ────────────────────────────────
        dict_ingresos = {
            "Num. Doc.": docs,
            "Nombres y Apellidos": nombres,
            "Sueldo Base": [t.sueldo_base for t in trabajadores],
            "Asig. Fam.": ["Sí" if t.asig_fam else "No" for t in trabajadores],
        }
        for c in conceptos_ingresos:
            dict_ingresos[c.nombre] = [conceptos_vals[t.id].get(c.nombre, 0.0) for t in trabajadores]
        df_ingresos = pd.DataFrame(dict_ingresos)

        # ─── SECCIÓN C: DESCUENTOS DIRECTOS ───────────────────────────────
        dict_descuentos = {
            "Num. Doc.": docs,
            "Nombres y Apellidos": nombres,
        }
        for c in conceptos_descuentos:
            dict_descuentos[c.nombre] = [conceptos_vals[t.id].get(c.nombre, 0.0) for t in trabajadores]
        df_descuentos = pd.DataFrame(dict_descuentos)

        # Mapa doc → trabajador_id para el guardado
        doc_to_trab_id = {t.num_doc: t.id for t in trabajadores}

        # 5. Renderizar pestañas con data_editor
        col_config_tiempos = {
            "Trabajador_ID": None,  # Ocultar columna técnica
            "Días Faltados": st.column_config.NumberColumn(min_value=0, max_value=31, step=1),
            "Min. Tardanza": st.column_config.NumberColumn(min_value=0, step=1),
            "Hrs Extras 25%": st.column_config.NumberColumn(min_value=0.0, step=0.5, format="%.1f"),
            "Hrs Extras 35%": st.column_config.NumberColumn(min_value=0.0, step=0.5, format="%.1f"),
        }
        col_config_moneda = {
            c.nombre: st.column_config.NumberColumn(min_value=0.0, step=50.0, format="S/ %.2f")
            for c in (conceptos_ingresos + conceptos_descuentos)
        }

        tab_t, tab_i, tab_d = st.tabs([
            "Tiempos y Asistencias", "Ingresos Variables", "Descuentos Directos"
        ])

        with tab_t:
            df_tiempos_edit = st.data_editor(
                df_tiempos,
                disabled=["Num. Doc.", "Nombres y Apellidos"],
                num_rows="fixed", use_container_width=True, hide_index=True,
                column_config=col_config_tiempos, key="ed_tiempos"
            )

        with tab_i:
            df_ingresos_edit = st.data_editor(
                df_ingresos,
                disabled=["Num. Doc.", "Nombres y Apellidos", "Sueldo Base", "Asig. Fam."],
                num_rows="fixed", use_container_width=True, hide_index=True,
                column_config=col_config_moneda, key="ed_ingresos"
            )

        with tab_d:
            if not conceptos_descuentos:
                st.info("No hay conceptos de descuento. Agrégelos en el Maestro de Conceptos.")
                df_descuentos_edit = df_descuentos
            else:
                df_descuentos_edit = st.data_editor(
                    df_descuentos,
                    disabled=["Num. Doc.", "Nombres y Apellidos"],
                    num_rows="fixed", use_container_width=True, hide_index=True,
                    column_config=col_config_moneda, key="ed_descuentos"
                )

        st.markdown("---")

        # 6. GUARDAR EN NEON
        if st.button(f"Guardar Variables de {periodo_key}", type="primary", use_container_width=True):
            try:
                for _, fila_t in df_tiempos_edit.iterrows():
                    doc = fila_t["Num. Doc."]
                    trab_id = doc_to_trab_id.get(doc)
                    if not trab_id:
                        continue

                    # Construir dict de conceptos dinámicos para este trabajador
                    conceptos_data = {}

                    # Ingresos variables
                    filas_i = df_ingresos_edit[df_ingresos_edit["Num. Doc."] == doc]
                    if not filas_i.empty:
                        fila_i = filas_i.iloc[0]
                        for c in conceptos_ingresos:
                            val = float(fila_i.get(c.nombre, 0.0))
                            if val > 0:
                                conceptos_data[c.nombre] = val

                    # Descuentos directos
                    if not df_descuentos_edit.empty and "Num. Doc." in df_descuentos_edit.columns:
                        filas_d = df_descuentos_edit[df_descuentos_edit["Num. Doc."] == doc]
                        if not filas_d.empty:
                            fila_d = filas_d.iloc[0]
                            for c in conceptos_descuentos:
                                val = float(fila_d.get(c.nombre, 0.0))
                                if val > 0:
                                    conceptos_data[c.nombre] = val

                    # Upsert en VariablesMes
                    v_existente = variables_existentes.get(trab_id)
                    if v_existente:
                        v_existente.dias_faltados = int(fila_t["Días Faltados"])
                        v_existente.min_tardanza = int(fila_t["Min. Tardanza"])
                        v_existente.hrs_extras_25 = float(fila_t["Hrs Extras 25%"])
                        v_existente.hrs_extras_35 = float(fila_t["Hrs Extras 35%"])
                        v_existente.conceptos_json = json.dumps(conceptos_data)
                    else:
                        nueva = VariablesMes(
                            empresa_id=empresa_id,
                            trabajador_id=trab_id,
                            periodo_key=periodo_key,
                            dias_faltados=int(fila_t["Días Faltados"]),
                            min_tardanza=int(fila_t["Min. Tardanza"]),
                            hrs_extras_25=float(fila_t["Hrs Extras 25%"]),
                            hrs_extras_35=float(fila_t["Hrs Extras 35%"]),
                            conceptos_json=json.dumps(conceptos_data),
                        )
                        db.add(nueva)

                db.commit()
                st.success(f"Variables de **{periodo_key}** guardadas en la nube correctamente.")
                st.rerun()

            except Exception as e:
                db.rollback()
                st.error(f"Error al guardar en la BD: {e}")

    finally:
        db.close()
