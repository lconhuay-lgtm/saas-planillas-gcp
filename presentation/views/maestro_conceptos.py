import streamlit as st
import pandas as pd
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Concepto, PlanillaMensual
from core.domain.catalogos_sunat import CATALOGO_T22_INGRESOS
import json

# Codigos SUNAT de conceptos obligatorios por Ley
_CODIGO_SUELDO   = "0121"
_CODIGO_ASIG_FAM = "0201"
_CODIGO_GRATI    = "0406"
_CODIGO_BONO_9   = "0312"

CONCEPTOS_OBLIGATORIOS = [
    {"nombre": "SUELDO BASICO",                         "codigo": _CODIGO_SUELDO,   "tipo": "INGRESO",   "afp": True,  "5ta": True,  "ess": True,  "cts": True,  "gra": True},
    {"nombre": "ASIGNACION FAMILIAR",                   "codigo": _CODIGO_ASIG_FAM, "tipo": "INGRESO",   "afp": True,  "5ta": True,  "ess": True,  "cts": True,  "gra": True},
    {"nombre": "GRATIFICACION (JUL/DIC)",               "codigo": _CODIGO_GRATI,    "tipo": "INGRESO",   "afp": False, "5ta": True,  "ess": False, "cts": False, "gra": False},
    {"nombre": "BONIFICACION EXTRAORDINARIA LEY 29351 (9%)", "codigo": _CODIGO_BONO_9, "tipo": "INGRESO", "afp": False, "5ta": True,  "ess": False, "cts": False, "gra": False},
]
NOMBRES_OBLIGATORIOS = {c["nombre"] for c in CONCEPTOS_OBLIGATORIOS}

# Lista ordenada de opciones para el selectbox (catálogo T22)
_OPCIONES_CATALOGO = [
    f"{cod} — {info['desc']} [{info['tipo']}]"
    for cod, info in sorted(CATALOGO_T22_INGRESOS.items())
]
_COD_POR_OPCION = {
    f"{cod} — {info['desc']} [{info['tipo']}]": cod
    for cod, info in sorted(CATALOGO_T22_INGRESOS.items())
}
# Mapa inverso: código → opción de catálogo (para preseleccionar)
_OPCION_POR_COD = {v: k for k, v in _COD_POR_OPCION.items()}


def sembrar_conceptos_por_defecto(empresa_id: int, db):
    if db.query(Concepto).filter_by(empresa_id=empresa_id).count() > 0:
        return
    for c in CONCEPTOS_OBLIGATORIOS:
        db.add(Concepto(
            empresa_id=empresa_id, nombre=c["nombre"], tipo=c["tipo"],
            codigo_sunat=c["codigo"],
            afecto_afp=c["afp"], afecto_5ta=c["5ta"], afecto_essalud=c["ess"],
            computable_cts=c["cts"], computable_grati=c["gra"],
        ))
    db.commit()


def render():
    empresa_id     = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')
    if not empresa_id:
        st.error("Acceso denegado. Seleccione una empresa.")
        return

    st.title("Maestro de Conceptos Remunerativos")
    st.markdown(f"Empresa: **{empresa_nombre}**")
    st.markdown("---")

    db = SessionLocal()
    try:
        sembrar_conceptos_por_defecto(empresa_id, db)

        # Mensajes diferidos (sobreviven al st.rerun)
        if st.session_state.get('msg_exito_concepto'):
            st.success(st.session_state.pop('msg_exito_concepto'))

        tab1, tab2 = st.tabs(["📋 Conceptos de la Empresa", "➕ Crear Nuevo Concepto"])

        # ── TAB 1: LISTADO + EDICIÓN INTELIGENTE ─────────────────────────────
        with tab1:
            conceptos_db = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
            if not conceptos_db:
                st.info("Sin conceptos. Recargue la página.")
                return

            # Advertencia para conceptos sin código SUNAT
            sin_codigo = [c for c in conceptos_db if not getattr(c, 'codigo_sunat', None)]
            if sin_codigo:
                nombres_sc = ", ".join(c.nombre for c in sin_codigo)
                st.warning(
                    f"⚠️ **{len(sin_codigo)} concepto(s) sin código SUNAT oficial** — no podrán "
                    f"incluirse en la exportación PLAME hasta que se asignen: {nombres_sc}"
                )

            # ── Sección A: Tabla de afectaciones (edición rápida de booleans) ──
            st.subheader("Catálogo de Conceptos Activos")
            st.caption("Edite las marcas de afectación directamente en la tabla y presione Guardar.")

            rows = []
            for c in conceptos_db:
                rows.append({
                    "_id": c.id,
                    "Cód. SUNAT": getattr(c, 'codigo_sunat', '') or '',
                    "Nombre del Concepto": c.nombre,
                    "Tipo": c.tipo,
                    "Afecto AFP/ONP": c.afecto_afp,
                    "Afecto 5ta Cat.": c.afecto_5ta,
                    "Afecto EsSalud": c.afecto_essalud,
                    "Computable CTS": c.computable_cts,
                    "Computable Grati": c.computable_grati,
                    "Prorrateable (Asist.)": getattr(c, 'prorrateable_por_asistencia', False),
                })
            df_c = pd.DataFrame(rows)
            df_v = df_c.drop(columns=["_id"])

            df_edit = st.data_editor(
                df_v, num_rows="fixed", use_container_width=True, hide_index=True,
                disabled=["Cód. SUNAT", "Nombre del Concepto", "Tipo"],
                column_config={
                    "Afecto AFP/ONP":   st.column_config.CheckboxColumn(),
                    "Afecto 5ta Cat.":  st.column_config.CheckboxColumn(),
                    "Afecto EsSalud":   st.column_config.CheckboxColumn(),
                    "Computable CTS":   st.column_config.CheckboxColumn(),
                    "Computable Grati": st.column_config.CheckboxColumn(),
                    "Prorrateable (Asist.)": st.column_config.CheckboxColumn(),
                },
                key="editor_conceptos",
            )

            if st.button("💾 Guardar Cambios de Afectaciones", type="primary"):
                try:
                    cmap = {c.nombre: c for c in conceptos_db}
                    for _, row in df_edit.iterrows():
                        c = cmap.get(row["Nombre del Concepto"])
                        if c:
                            c.afecto_afp     = bool(row["Afecto AFP/ONP"])
                            c.afecto_5ta     = bool(row["Afecto 5ta Cat."])
                            c.afecto_essalud = bool(row["Afecto EsSalud"])
                            c.computable_cts   = bool(row["Computable CTS"])
                            c.computable_grati = bool(row["Computable Grati"])
                            c.prorrateable_por_asistencia = bool(row.get("Prorrateable (Asist.)", False))
                    db.commit()
                    st.session_state['msg_exito_concepto'] = "✅ Reglas tributarias actualizadas correctamente."
                    st.rerun()
                except Exception as e:
                    db.rollback()
                    st.error(f"Error: {e}")

            st.markdown("---")

            # ── Sección B: Edición inteligente — reasignar código SUNAT ──────
            with st.expander("✏️ Editar Concepto — Reasignar Código SUNAT", expanded=False):
              st.info(
                "Seleccione un concepto existente y asígnele (o cambie) su código del "
                "catálogo oficial SUNAT (Tabla 22 PLAME). Las afectaciones se autocompletarán."
              )

              # Selectbox para elegir concepto existente
              nombres_existentes = [c.nombre for c in conceptos_db]
              concepto_a_editar = st.selectbox(
                "Concepto a editar:",
                nombres_existentes,
                key="sel_concepto_editar",
              )

              obj_editar = next((c for c in conceptos_db if c.nombre == concepto_a_editar), None)

              if obj_editar:
                # Preseleccionar el código actual en el catálogo (si existe)
                cod_actual = getattr(obj_editar, 'codigo_sunat', None) or ''
                idx_default = 0
                if cod_actual and cod_actual in _OPCION_POR_COD:
                    opcion_actual = _OPCION_POR_COD[cod_actual]
                    if opcion_actual in _OPCIONES_CATALOGO:
                        idx_default = _OPCIONES_CATALOGO.index(opcion_actual)

                col_izq, col_der = st.columns(2)

                with col_izq:
                    st.markdown("**Catálogo SUNAT (Tabla 22)**")
                    catalogo_sel = st.selectbox(
                        "Seleccione código SUNAT:",
                        _OPCIONES_CATALOGO,
                        index=idx_default,
                        key="sel_cat_editar",
                    )
                    cod_nuevo  = _COD_POR_OPCION[catalogo_sel]
                    info_nuevo = CATALOGO_T22_INGRESOS[cod_nuevo]

                    st.markdown("**Afectaciones automáticas según SUNAT:**")
                    st.checkbox("Afecto AFP/ONP",       value=info_nuevo["afp"],     disabled=True, key="e_cb_afp")
                    st.checkbox("Afecto 5ta Categoría", value=info_nuevo["quinta"],  disabled=True, key="e_cb_5ta")
                    st.checkbox("Afecto EsSalud",       value=info_nuevo["essalud"], disabled=True, key="e_cb_ess")
                    st.caption(f"Tipo SUNAT: **{info_nuevo['tipo']}**  |  Código: **{cod_nuevo}**")

                with col_der:
                    st.markdown("**Nombre y Beneficios Sociales**")
                    nombre_edit = st.text_input(
                        "Nombre del concepto:",
                        value=obj_editar.nombre,
                        key="edit_nombre_concepto",
                        help="Puede personalizar el nombre para su empresa.",
                    )
                    es_oblig = obj_editar.nombre in NOMBRES_OBLIGATORIOS
                    if es_oblig:
                        st.caption("⚠️ Concepto obligatorio — nombre protegido.")
                    comp_cts_edit   = st.checkbox(
                        "Computable para CTS",
                        value=bool(obj_editar.computable_cts),
                        key="e_cb_cts",
                    )
                    comp_grati_edit = st.checkbox(
                        "Computable para Gratificación",
                        value=bool(obj_editar.computable_grati),
                        key="e_cb_gra",
                    )
                    prorrateable_edit = st.checkbox(
                        "Prorrateable por asistencia", 
                        value=bool(getattr(obj_editar, 'prorrateable_por_asistencia', False)), 
                        key="e_cb_pror"
                    )

                if st.button("🔄 Actualizar Concepto", type="primary", use_container_width=True):
                    try:
                        nombre_final = (obj_editar.nombre if es_oblig
                                        else (nombre_edit.strip().upper() or obj_editar.nombre))

                        if nombre_final != obj_editar.nombre:
                            dup = db.query(Concepto).filter_by(
                                empresa_id=empresa_id, nombre=nombre_final
                            ).first()
                            if dup:
                                st.error(f"Ya existe un concepto con el nombre '{nombre_final}'.")
                                st.stop()

                        obj_editar.nombre           = nombre_final
                        obj_editar.codigo_sunat     = cod_nuevo
                        obj_editar.tipo             = info_nuevo["tipo"]
                        obj_editar.afecto_afp       = info_nuevo["afp"]
                        obj_editar.afecto_5ta       = info_nuevo["quinta"]
                        obj_editar.afecto_essalud   = info_nuevo["essalud"]
                        obj_editar.computable_cts   = comp_cts_edit
                        obj_editar.computable_grati = comp_grati_edit
                        obj_editar.prorrateable_por_asistencia = prorrateable_edit
                        db.commit()
                        st.session_state['msg_exito_concepto'] = (
                            f"✅ Concepto **{nombre_final}** actualizado — "
                            f"Código SUNAT asignado: {cod_nuevo}."
                        )
                        st.rerun()
                    except Exception as e:
                        db.rollback()
                        st.error(f"Error al actualizar: {e}")

            st.markdown("---")
            # ── Sección C: Eliminación con Candado de Seguridad ──────────────
            with st.expander("🗑️ Eliminar Concepto", expanded=False):
                st.warning("⚠️ Esta acción es permanente. No podrá eliminar conceptos que ya hayan sido utilizados en planillas cerradas.")
                
                conceptos_borrables = [c.nombre for c in conceptos_db if c.nombre not in NOMBRES_OBLIGATORIOS]
                concepto_a_borrar = st.selectbox("Seleccione concepto a eliminar:", [""] + conceptos_borrables, key="sel_borrar")
                
                if concepto_a_borrar:
                    if st.button(f"Confirmar Eliminación de {concepto_a_borrar}", type="secondary", use_container_width=True):
                        try:
                            # 🔒 CANDADO: Verificar uso en planillas cerradas
                            planillas_historicas = db.query(PlanillaMensual).filter_by(empresa_id=empresa_id).all()
                            en_uso = False
                            for p in planillas_historicas:
                                try:
                                    # Buscamos el nombre del concepto en el snapshot de auditoría
                                    aud = json.loads(p.auditoria_json or '{}')
                                    for dni in aud:
                                        if concepto_a_borrar in aud[dni].get('ingresos', {}) or \
                                           concepto_a_borrar in aud[dni].get('descuentos', {}):
                                            en_uso = True
                                            break
                                    if en_uso: break
                                except: continue
                            
                            if en_uso:
                                st.error(f"🚫 No se puede eliminar '{concepto_a_borrar}': ya existen planillas calculadas o cerradas que utilizan este concepto. Se recomienda mantenerlo para integridad del histórico.")
                            else:
                                obj_del = db.query(Concepto).filter_by(empresa_id=empresa_id, nombre=concepto_a_borrar).first()
                                if obj_del:
                                    db.delete(obj_del)
                                    db.commit()
                                    st.session_state['msg_exito_concepto'] = f"🗑️ Concepto '{concepto_a_borrar}' eliminado correctamente."
                                    st.rerun()
                        except Exception as e_del:
                            db.rollback()
                            st.error(f"Error al eliminar: {e_del}")

        # ── TAB 2: NUEVO CONCEPTO ─────────────────────────────────────────────
        with tab2:
            st.subheader("Nuevo Concepto Vinculado al Catálogo SUNAT")
            st.info(
                "Seleccione el concepto oficial del catálogo SUNAT (Tabla 22 PLAME). "
                "Las afectaciones tributarias se autocompletarán según la norma."
            )

            concepto_sel = st.selectbox(
                "Concepto SUNAT (Tabla 22):", _OPCIONES_CATALOGO, key="sel_cat_sunat"
            )
            cod_sel  = _COD_POR_OPCION[concepto_sel]
            info_sel = CATALOGO_T22_INGRESOS[cod_sel]

            # Autocompletar afectaciones (readonly)
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Afectaciones (automáticas según SUNAT)**")
                afp_val  = info_sel["afp"]
                q_val    = info_sel["quinta"]
                ess_val  = info_sel["essalud"]
                tipo_val = info_sel["tipo"]
                st.checkbox("Afecto AFP/ONP",         value=afp_val,  disabled=True, key="cb_afp")
                st.checkbox("Afecto 5ta Categoría",   value=q_val,    disabled=True, key="cb_5ta")
                st.checkbox("Afecto EsSalud",          value=ess_val,  disabled=True, key="cb_ess")
                st.caption(f"Tipo SUNAT: **{tipo_val}**  |  Código: **{cod_sel}**")
            with col2:
                st.markdown("**Beneficios Sociales**")
                comp_cts   = st.checkbox("Computable para CTS",         value=False, key="cb_cts")
                comp_grati = st.checkbox("Computable para Gratificación", value=False, key="cb_gra")
                comp_pror = st.checkbox("Prorrateable por asistencia", value=False, key="cb_pror")
                nombre_custom = st.text_input(
                    "Nombre personalizado (opcional)",
                    value=info_sel["desc"].upper(),
                    key="nombre_custom_concepto",
                    help="Deje el nombre por defecto o personalícelo para su empresa.",
                )

            if st.button("➕ Crear Concepto", type="primary", use_container_width=True):
                nombre_final = nombre_custom.strip().upper() or info_sel["desc"].upper()
                existe = db.query(Concepto).filter_by(empresa_id=empresa_id, nombre=nombre_final).first()
                if existe:
                    st.error(f"El concepto '{nombre_final}' ya existe.")
                else:
                    try:
                        db.add(Concepto(
                            empresa_id=empresa_id, nombre=nombre_final,
                            tipo=tipo_val, codigo_sunat=cod_sel,
                            afecto_afp=afp_val, afecto_5ta=q_val, afecto_essalud=ess_val,
                            computable_cts=comp_cts, computable_grati=comp_grati,
                            prorrateable_por_asistencia=comp_pror
                        ))
                        db.commit()
                        st.session_state['msg_exito_concepto'] = (
                            f"✅ Concepto **{nombre_final}** creado exitosamente (SUNAT {cod_sel})."
                        )
                        st.rerun()
                    except Exception as e:
                        db.rollback()
                        st.error(f"Error: {e}")
    finally:
        db.close()
