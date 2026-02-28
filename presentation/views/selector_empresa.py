import streamlit as st
import datetime
from infrastructure.database.connection import get_db
from infrastructure.database.models import Empresa, Usuario
from infrastructure.services.sunat_api import consultar_dni_sunat

def render():
    st.title("🗄️ Panel de Control Multi-Empresa")
    st.markdown("Seleccione el cliente (empresa) con el que desea trabajar en esta sesión.")
    st.markdown("---")

    # Mostrar mensajes diferidos (sobreviven al st.rerun())
    if st.session_state.get('_msg_empresa'):
        st.success(st.session_state.pop('_msg_empresa'))

    db = next(get_db())
    editando_id = st.session_state.get('_editando_empresa_id')
    creando_nueva = st.session_state.get('_creando_nueva_empresa', False)

    # ── MODO CREACIÓN DE NUEVA EMPRESA ──────────────────────────────────────────
    if creando_nueva:
        st.subheader("🏢 Registro de Nueva Empresa Cliente")
        st.markdown("Ingrese el RUC para realizar la búsqueda automática en las bases de datos de SUNAT.")
        st.markdown("---")

        col_f, _ = st.columns([2, 1])
        with col_f:
            with st.container(border=True):
                c_ruc, c_bus = st.columns([3, 1])
                ruc_nuevo = c_ruc.text_input("RUC (11 dígitos)*", max_chars=11, key="n_ruc")
                
                # Estado para autocompletar
                if c_bus.button("🔍 Buscar SUNAT", use_container_width=True):
                    if len(ruc_nuevo) == 11:
                        # Reutilizamos la lógica de consulta (ajustada para RUC si el API lo permite)
                        with st.spinner("Consultando SUNAT..."):
                            res = consultar_dni_sunat(ruc_nuevo)
                            if res["success"]:
                                st.session_state["_tmp_razon"] = res["nombres"]
                                st.toast("✅ Datos encontrados correctamente", icon="🏢")
                            else:
                                st.error(res["mensaje"])
                    else:
                        st.error("El RUC debe tener 11 dígitos.")

                razon_social = st.text_input("Razón Social*", value=st.session_state.get("_tmp_razon", ""))
                
                regimenes = ["Régimen General", "Régimen Especial - Micro Empresa", "Régimen Especial - Pequeña Empresa"]
                regimen_sel = st.selectbox("Régimen Laboral*", regimenes)

                fecha_acogimiento_sel = None
                if regimen_sel != "Régimen General":
                    fecha_acogimiento_sel = st.date_input("Fecha de Acogimiento al Régimen MYPE*", value=datetime.date.today())
                
                representante = st.text_input("Representante Legal")
                correo = st.text_input("Correo Electrónico")
                domicilio = st.text_area("Domicilio Fiscal")

            st.markdown("---")
            cb1, cb2 = st.columns(2)
            if cb1.button("💾 Registrar e Inscribir", type="primary", use_container_width=True):
                if len(ruc_nuevo) != 11 or not razon_social:
                    st.error("RUC y Razón Social son obligatorios.")
                else:
                    try:
                        nueva = Empresa(
                            ruc=ruc_nuevo, razon_social=razon_social,
                            regimen_laboral=regimen_sel, fecha_acogimiento=fecha_acogimiento_sel,
                            representante_legal=representante, correo_electronico=correo,
                            domicilio=domicilio
                        )
                        db.add(nueva)
                        db.commit()
                        st.session_state.pop('_creando_nueva_empresa', None)
                        st.session_state.pop('_tmp_razon', None)
                        st.session_state['_msg_empresa'] = f"✅ Empresa **{razon_social}** registrada exitosamente."
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al registrar: {e}")

            if cb2.button("← Cancelar", use_container_width=True):
                st.session_state.pop('_creando_nueva_empresa', None)
                st.session_state.pop('_tmp_razon', None)
                st.rerun()
        return

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
    st.subheader("Empresas Registradas")
    
    # Filtro de seguridad: Si no es admin/acceso_total, filtrar por asignación
    usuario_actual = db.query(Usuario).filter_by(username=st.session_state.get('usuario_logueado')).first()
    
    if usuario_actual and usuario_actual.acceso_total:
        empresas_db = db.query(Empresa).all()
    elif usuario_actual:
        empresas_db = usuario_actual.empresas_asignadas
    else:
        empresas_db = []

    if usuario_actual and usuario_actual.rol in ("admin", "supervisor"):
        col_t, col_b = st.columns([3, 1])
        col_b.button("➕ Crear Nueva Empresa", type="primary", use_container_width=True, 
                     on_click=lambda: st.session_state.update({"_creando_nueva_empresa": True}))

    if not empresas_db:
        st.info("No hay empresas registradas bajo su perfil.")
    else:
        # Mostrar en cuadrícula (grid) para estilo profesional
        for i in range(0, len(empresas_db), 2):
            cols = st.columns(2)
            for j in range(2):
                if i + j < len(empresas_db):
                    emp = empresas_db[i + j]
                    with cols[j].container(border=True):
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            st.markdown(f"#### {emp.razon_social}")
                            st.caption(f"**RUC:** {emp.ruc}  |  **Régimen:** {emp.regimen_laboral}")
                        with c2:
                            if st.button("✏️", key=f"edit_emp_{emp.id}", help="Editar datos de empresa"):
                                st.session_state['_editando_empresa_id'] = emp.id
                                st.rerun()

                        if st.button("🚀 Seleccionar", key=f"sel_{emp.id}", use_container_width=True):
                            st.session_state['empresa_activa_id'] = emp.id
                            st.session_state['empresa_activa_nombre'] = emp.razon_social
                            st.session_state['empresa_activa_ruc'] = emp.ruc
                            st.session_state['empresa_activa_regimen'] = emp.regimen_laboral
                            st.session_state['empresa_acogimiento'] = emp.fecha_acogimiento
                            st.session_state['empresa_activa_domicilio'] = emp.domicilio or ''
                            st.session_state['empresa_activa_representante'] = emp.representante_legal or ''
                            st.session_state['empresa_activa_correo'] = emp.correo_electronico or ''
                            st.rerun()
