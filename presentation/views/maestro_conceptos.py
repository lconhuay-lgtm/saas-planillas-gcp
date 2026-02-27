import streamlit as st
import pandas as pd
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Concepto
from core.domain.catalogos_sunat import CATALOGO_T22_INGRESOS

# Codigos SUNAT de conceptos obligatorios por Ley
_CODIGO_SUELDO   = "0121"
_CODIGO_ASIG_FAM = "0201"
_CODIGO_GRATI    = "0401"
_CODIGO_BONO_9   = "0305"

CONCEPTOS_OBLIGATORIOS = [
    {"nombre": "SUELDO BASICO",                         "codigo": _CODIGO_SUELDO,   "tipo": "INGRESO",   "afp": True,  "5ta": True,  "ess": True,  "cts": True,  "gra": True},
    {"nombre": "ASIGNACION FAMILIAR",                   "codigo": _CODIGO_ASIG_FAM, "tipo": "INGRESO",   "afp": True,  "5ta": True,  "ess": True,  "cts": True,  "gra": True},
    {"nombre": "GRATIFICACION (JUL/DIC)",               "codigo": _CODIGO_GRATI,    "tipo": "INGRESO",   "afp": False, "5ta": True,  "ess": False, "cts": False, "gra": False},
    {"nombre": "BONIFICACION EXTRAORDINARIA LEY 29351 (9%)", "codigo": _CODIGO_BONO_9, "tipo": "INGRESO", "afp": False, "5ta": True,  "ess": False, "cts": False, "gra": False},
]
NOMBRES_OBLIGATORIOS = {c["nombre"] for c in CONCEPTOS_OBLIGATORIOS}

# Lista ordenada de opciones para el selectbox
_OPCIONES_CATALOGO = [
    f"{cod} — {info['desc']} [{info['tipo']}]"
    for cod, info in sorted(CATALOGO_T22_INGRESOS.items())
]
_COD_POR_OPCION = {
    f"{cod} — {info['desc']} [{info['tipo']}]": cod
    for cod, info in sorted(CATALOGO_T22_INGRESOS.items())
}


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

        if st.session_state.get('msg_exito_concepto'):
            st.success(st.session_state.pop('msg_exito_concepto'))

        tab1, tab2 = st.tabs(["Conceptos de la Empresa", "Crear Nuevo Concepto"])

        # ── TAB 1: LISTADO ────────────────────────────────────────────────────
        with tab1:
            st.subheader("Catálogo de Conceptos Activos")
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
                },
                key="editor_conceptos",
            )

            if st.button("Guardar Cambios", type="primary"):
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
                    db.commit()
                    st.success("Reglas tributarias actualizadas.")
                    st.rerun()
                except Exception as e:
                    db.rollback()
                    st.error(f"Error: {e}")

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
                nombre_custom = st.text_input(
                    "Nombre personalizado (opcional)",
                    value=info_sel["desc"].upper(),
                    key="nombre_custom_concepto",
                    help="Deje el nombre por defecto o personalícelo para su empresa.",
                )

            if st.button("Crear Concepto", type="primary", use_container_width=True):
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
                        ))
                        db.commit()
                        st.session_state['msg_exito_concepto'] = f"Concepto '{nombre_final}' creado (SUNAT {cod_sel})."
                        st.rerun()
                    except Exception as e:
                        db.rollback()
                        st.error(f"Error: {e}")
    finally:
        db.close()
