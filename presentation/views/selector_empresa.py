import streamlit as st
import datetime
from infrastructure.database.connection import get_db
from infrastructure.database.models import Empresa


def render():
    st.title("🗄️ Panel de Control Multi-Empresa")
    st.markdown("Seleccione el cliente (empresa) con el que desea trabajar en esta sesión.")
    st.markdown("---")

    # Mostrar mensajes diferidos (sobreviven al st.rerun())
    if st.session_state.get('_msg_empresa'):
        st.success(st.session_state.pop('_msg_empresa'))

    db = next(get_db())
    editando_id = st.session_state.get('_editando_empresa_id')

    # ── MODO EDICIÓN DE EMPRESA ─────────────────────────────────────────────────
    if editando_id:
        emp = db.query(Empresa).filter_by(id=editando_id).first()
        if not emp:
            st.session_state.pop('_editando_empresa_id', None)
            st.rerun()

        st.subheader(f"✏️ Editando: {emp.razon_social}")
        st.caption(f"RUC: {emp.ruc}  —  El RUC no puede modificarse.")
        st.markdown("---")

        col_form, _ = st.columns([2, 1])
        with col_form:
            razon_social = st.text_input("Razón Social*", value=emp.razon_social or "")
            regimenes = ["Régimen General", "Régimen Especial - Micro Empresa", "Régimen Especial - Pequeña Empresa"]
            reg_idx = regimenes.index(emp.regimen_laboral) if emp.regimen_laboral in regimenes else 0
            regimen_sel = st.selectbox("Régimen Laboral*", regimenes, index=reg_idx)
            st.markdown(
                "<a href='https://apps.trabajo.gob.pe/consultas-remype/app/index.html' target='_blank' "
                "style='font-size:0.85em;color:#7F8C8D;text-decoration:none;'>"
                "🔍 <i>Verificar acreditación REMYPE (MTPE)</i></a>",
                unsafe_allow_html=True
            )
            st.markdown("<br/>", unsafe_allow_html=True)

            fecha_acogimiento_sel = emp.fecha_acogimiento
            if regimen_sel != "Régimen General":
                fecha_acogimiento_sel = st.date_input(
                    "Fecha de Acogimiento al Régimen MYPE*",
                    value=emp.fecha_acogimiento or datetime.date.today()
                )
                st.caption("⚠️ Los trabajadores que ingresaron ANTES de esta fecha conservarán los beneficios del Régimen General.")
                st.markdown("<br/>", unsafe_allow_html=True)
            else:
                fecha_acogimiento_sel = None

            representante = st.text_input("Representante Legal", value=emp.representante_legal or "")
            correo = st.text_input("Correo Electrónico", value=emp.correo_electronico or "")
            domicilio = st.text_area("Domicilio Fiscal", value=emp.domicilio or "")

            st.markdown("---")
            col_g, col_c = st.columns(2)
            if col_g.button("💾 Guardar Cambios", type="primary", use_container_width=True):
                if not razon_social:
                    st.error("La Razón Social es obligatoria.")
                elif regimen_sel != "Régimen General" and not fecha_acogimiento_sel:
                    st.error("Debe indicar la Fecha de Acogimiento al REMYPE.")
                else:
                    try:
                        emp.razon_social = razon_social
                        emp.regimen_laboral = regimen_sel
                        emp.fecha_acogimiento = fecha_acogimiento_sel
                        emp.representante_legal = representante
                        emp.correo_electronico = correo
                        emp.domicilio = domicilio
                        db.commit()
                        # Actualizar session_state si es la empresa activa
                        if st.session_state.get('empresa_activa_id') == editando_id:
                            st.session_state['empresa_activa_nombre'] = razon_social
                            st.session_state['empresa_activa_regimen'] = regimen_sel
                            st.session_state['empresa_acogimiento'] = fecha_acogimiento_sel
                        st.session_state.pop('_editando_empresa_id', None)
                        st.session_state['_msg_empresa'] = f"✅ Empresa **{razon_social}** actualizada correctamente."
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al actualizar: {e}")

            if col_c.button("← Cancelar", use_container_width=True):
                st.session_state.pop('_editando_empresa_id', None)
                st.rerun()
        return  # No renderizar lista+formulario en modo edición

    # ── VISTA NORMAL ─────────────────────────────────────────────────────────────
    col_lista, col_form = st.columns([2, 1])

    with col_lista:
        st.subheader("Empresas Registradas")
        empresas_db = db.query(Empresa).all()

        if not empresas_db:
            st.info("No hay empresas registradas. Utilice el panel derecho para crear la primera.")
        else:
            for emp in empresas_db:
                with st.container(border=True):
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        st.markdown(f"#### {emp.razon_social}")
                        st.markdown(f"**RUC:** {emp.ruc} | **Régimen:** {emp.regimen_laboral}")
                    with c2:
                        if st.button("✏️ Editar", key=f"edit_emp_{emp.id}", use_container_width=True):
                            st.session_state['_editando_empresa_id'] = emp.id
                            st.rerun()

                    if st.button("▶ Seleccionar Empresa", key=f"sel_{emp.id}", use_container_width=True):
                        st.session_state['empresa_activa_id'] = emp.id
                        st.session_state['empresa_activa_nombre'] = emp.razon_social
                        st.session_state['empresa_activa_ruc'] = emp.ruc
                        st.session_state['empresa_activa_regimen'] = emp.regimen_laboral
                        st.session_state['empresa_acogimiento'] = emp.fecha_acogimiento
                        st.rerun()

    with col_form:
        st.subheader("Nueva Empresa")

        ruc = st.text_input("RUC (11 dígitos)*", max_chars=11)
        razon_social = st.text_input("Razón Social*")

        regimenes = ["Régimen General", "Régimen Especial - Micro Empresa", "Régimen Especial - Pequeña Empresa"]
        regimen_sel = st.selectbox("Régimen Laboral*", regimenes)

        st.markdown(
            "<a href='https://apps.trabajo.gob.pe/consultas-remype/app/index.html' target='_blank' "
            "style='font-size:0.85em;color:#7F8C8D;text-decoration:none;'>"
            "🔍 <i>Verificar acreditación REMYPE (MTPE)</i></a>",
            unsafe_allow_html=True
        )
        st.markdown("<br/>", unsafe_allow_html=True)

        fecha_acogimiento_sel = None
        if regimen_sel != "Régimen General":
            fecha_acogimiento_sel = st.date_input("Fecha de Acogimiento al Régimen MYPE*")
            st.caption("⚠️ Los trabajadores que ingresaron ANTES de esta fecha conservarán los beneficios del Régimen General de forma irrenunciable.")
            st.markdown("<br/>", unsafe_allow_html=True)

        representante = st.text_input("Representante Legal")
        correo = st.text_input("Correo Electrónico")
        domicilio = st.text_area("Domicilio Fiscal")

        st.markdown("*Campos obligatorios*")

        if st.button("➕ Registrar Empresa", type="primary", use_container_width=True):
            if len(ruc) != 11 or not ruc.isdigit():
                st.error("El RUC debe tener exactamente 11 dígitos numéricos.")
            elif not razon_social:
                st.error("La Razón Social es obligatoria.")
            elif regimen_sel != "Régimen General" and not fecha_acogimiento_sel:
                st.error("Debe indicar la Fecha de Acogimiento al REMYPE.")
            else:
                existe = db.query(Empresa).filter(Empresa.ruc == ruc).first()
                if existe:
                    st.error("Ya existe una empresa con este RUC.")
                else:
                    try:
                        nueva_emp = Empresa(
                            ruc=ruc,
                            razon_social=razon_social,
                            representante_legal=representante,
                            correo_electronico=correo,
                            domicilio=domicilio,
                            regimen_laboral=regimen_sel,
                            fecha_acogimiento=fecha_acogimiento_sel
                        )
                        db.add(nueva_emp)
                        db.commit()
                        st.session_state['_msg_empresa'] = f"✅ Empresa **{razon_social}** registrada exitosamente."
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al registrar: {e}")
