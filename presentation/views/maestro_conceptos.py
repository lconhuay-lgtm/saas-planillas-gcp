import streamlit as st
import pandas as pd
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Concepto

# Conceptos obligatorios por Ley peruana — no se pueden eliminar
CONCEPTOS_OBLIGATORIOS = [
    {
        "nombre": "SUELDO BASICO",
        "tipo": "INGRESO",
        "afecto_afp": True, "afecto_5ta": True, "afecto_essalud": True,
        "computable_cts": True, "computable_grati": True,
    },
    {
        "nombre": "ASIGNACION FAMILIAR",
        "tipo": "INGRESO",
        "afecto_afp": True, "afecto_5ta": True, "afecto_essalud": True,
        "computable_cts": True, "computable_grati": True,
    },
    {
        "nombre": "GRATIFICACION (JUL/DIC)",
        "tipo": "INGRESO",
        "afecto_afp": False, "afecto_5ta": True, "afecto_essalud": False,
        "computable_cts": False, "computable_grati": False,
    },
    {
        "nombre": "BONIFICACION EXTRAORDINARIA LEY 29351 (9%)",
        "tipo": "INGRESO",
        "afecto_afp": False, "afecto_5ta": True, "afecto_essalud": False,
        "computable_cts": False, "computable_grati": False,
    },
]
NOMBRES_OBLIGATORIOS = {c["nombre"] for c in CONCEPTOS_OBLIGATORIOS}


def sembrar_conceptos_por_defecto(empresa_id: int, db):
    """
    Si la empresa no tiene conceptos en la BD, inserta los 4 obligatorios de Ley.
    """
    existentes = db.query(Concepto).filter_by(empresa_id=empresa_id).count()
    if existentes > 0:
        return

    for c in CONCEPTOS_OBLIGATORIOS:
        nuevo = Concepto(
            empresa_id=empresa_id,
            nombre=c["nombre"],
            tipo=c["tipo"],
            afecto_afp=c["afecto_afp"],
            afecto_5ta=c["afecto_5ta"],
            afecto_essalud=c["afecto_essalud"],
            computable_cts=c["computable_cts"],
            computable_grati=c["computable_grati"],
        )
        db.add(nuevo)
    db.commit()


def concepto_to_dict(c: Concepto) -> dict:
    """Convierte un objeto Concepto de SQLAlchemy a dict para el DataFrame."""
    return {
        "_id": c.id,
        "Nombre del Concepto": c.nombre,
        "Tipo": c.tipo,
        "Afecto AFP/ONP": c.afecto_afp,
        "Afecto 5ta Cat.": c.afecto_5ta,
        "Afecto EsSalud": c.afecto_essalud,
        "Computable CTS": c.computable_cts,
        "Computable Grati": c.computable_grati,
    }


def render():
    empresa_id = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')

    if not empresa_id:
        st.error("Acceso denegado. Seleccione una empresa en el Dashboard.")
        return

    st.title("Maestro de Conceptos Remunerativos")
    st.markdown(f"Defina los ingresos y descuentos personalizados para: **{empresa_nombre}**")
    st.markdown("---")

    db = SessionLocal()

    try:
        # 1. Sembrar conceptos por defecto si la empresa es nueva
        sembrar_conceptos_por_defecto(empresa_id, db)

        # 2. Mostrar mensaje de éxito si viene de una operación anterior
        if st.session_state.get('msg_exito_concepto'):
            st.success(st.session_state.pop('msg_exito_concepto'))

        tab1, tab2 = st.tabs(["Conceptos de la Empresa", "Crear Nuevo Concepto"])

        # PESTAÑA 1: LISTADO + EDICION EN GRILLA
        with tab1:
            st.subheader("Catalogo de Conceptos Activos")
            st.markdown(
                "Los conceptos obligatorios de Ley ya estan cargados. "
                "Puede ajustar sus reglas tributarias o agregar nuevos desde la pestana Crear."
            )

            conceptos_db = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
            if not conceptos_db:
                st.info("No hay conceptos. Recargue la pagina.")
                return

            df_conceptos = pd.DataFrame([concepto_to_dict(c) for c in conceptos_db])
            df_visual = df_conceptos.drop(columns=["_id"])

            df_editado = st.data_editor(
                df_visual,
                num_rows="fixed",
                use_container_width=True,
                hide_index=True,
                disabled=["Nombre del Concepto", "Tipo"],
                column_config={
                    "Afecto AFP/ONP": st.column_config.CheckboxColumn("Afecto AFP/ONP"),
                    "Afecto 5ta Cat.": st.column_config.CheckboxColumn("Afecto 5ta Cat."),
                    "Afecto EsSalud": st.column_config.CheckboxColumn("Afecto EsSalud"),
                    "Computable CTS": st.column_config.CheckboxColumn("Computable CTS"),
                    "Computable Grati": st.column_config.CheckboxColumn("Computable Grati"),
                },
                key="editor_conceptos"
            )

            if st.button("Guardar Cambios en Grilla", type="primary"):
                try:
                    conceptos_map = {c.nombre: c for c in conceptos_db}
                    for _, row in df_editado.iterrows():
                        nombre = row["Nombre del Concepto"]
                        c = conceptos_map.get(nombre)
                        if c:
                            c.afecto_afp = bool(row["Afecto AFP/ONP"])
                            c.afecto_5ta = bool(row["Afecto 5ta Cat."])
                            c.afecto_essalud = bool(row["Afecto EsSalud"])
                            c.computable_cts = bool(row["Computable CTS"])
                            c.computable_grati = bool(row["Computable Grati"])
                    db.commit()
                    st.success("Reglas tributarias actualizadas correctamente en la nube.")
                    st.rerun()
                except Exception as e:
                    db.rollback()
                    st.error(f"Error al guardar: {e}")

        # PESTAÑA 2: FORMULARIO PARA NUEVO CONCEPTO
        with tab2:
            st.subheader("Configurador de Reglas Laborales y Tributarias")

            with st.form("form_nuevo_concepto"):
                col1, col2 = st.columns([1, 1])

                with col1:
                    st.markdown("**1. Datos Basicos**")
                    nombre = st.text_input("Nombre del Concepto", placeholder="Ej: Bono de Productividad...")
                    tipo = st.selectbox("Tipo de Concepto", ["INGRESO", "DESCUENTO"])

                with col2:
                    st.markdown("**2. Afectaciones Tributarias**")
                    afecto_afp = st.checkbox("Afecto a Retencion AFP/ONP", value=True)
                    afecto_5ta = st.checkbox("Afecto a Impuesto 5ta Categoria", value=True)
                    afecto_essalud = st.checkbox("Afecto a Aporte EsSalud (9%)", value=True)

                    st.markdown("**3. Beneficios Sociales**")
                    comp_cts = st.checkbox("Base Computable para CTS", value=False)
                    comp_grati = st.checkbox("Base Computable para Gratificacion", value=False)

                st.markdown("---")
                submit = st.form_submit_button("Crear Concepto", type="primary", use_container_width=True)

                if submit:
                    nombre_upper = nombre.strip().upper()
                    if not nombre_upper:
                        st.error("El nombre del concepto es obligatorio.")
                    else:
                        existe = db.query(Concepto).filter_by(
                            empresa_id=empresa_id, nombre=nombre_upper
                        ).first()
                        if existe:
                            st.error(f"El concepto '{nombre_upper}' ya existe en esta empresa.")
                        else:
                            try:
                                nuevo = Concepto(
                                    empresa_id=empresa_id,
                                    nombre=nombre_upper,
                                    tipo=tipo,
                                    afecto_afp=afecto_afp,
                                    afecto_5ta=afecto_5ta,
                                    afecto_essalud=afecto_essalud,
                                    computable_cts=comp_cts,
                                    computable_grati=comp_grati,
                                )
                                db.add(nuevo)
                                db.commit()
                                st.session_state['msg_exito_concepto'] = (
                                    f"Concepto '{nombre_upper}' registrado en la nube."
                                )
                                st.rerun()
                            except Exception as e:
                                db.rollback()
                                st.error(f"Error al guardar: {e}")

    finally:
        db.close()
