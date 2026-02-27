import streamlit as st
import pandas as pd
import datetime
from infrastructure.database.connection import get_db
from infrastructure.database.models import Trabajador


def determinar_regimen_trabajador(fecha_ingreso, regimen_empresa, fecha_acogimiento):
    """Lógica legal de protección de derechos adquiridos"""
    if regimen_empresa == "Régimen General" or not fecha_acogimiento:
        return "Régimen General"
    if fecha_ingreso < fecha_acogimiento:
        return "Régimen General (Derechos Adquiridos)"
    return regimen_empresa


def consultar_dni_automatico(dni):
    """Simulación de API de Reniec/Sunat — reemplazar con API real"""
    base_datos_ficticia = {
        "12345678": {"nombres": "SOTO MENDOZA, RICARDO DANIEL", "nacimiento": datetime.date(1985, 5, 20)},
        "87654321": {"nombres": "ALVAREZ RUIZ, MARIA ELENA", "nacimiento": datetime.date(1992, 10, 15)},
    }
    return base_datos_ficticia.get(dni, None)


def _render_form_trabajador(t=None, key_prefix="nuevo"):
    """
    Renderiza el formulario de trabajador.
    - t=None  → formulario de Alta (campos vacíos con defaults)
    - t=Obj   → formulario de Edición (campos pre-cargados con datos del objeto)
    Retorna un dict con los datos si el usuario presionó Guardar, o None.
    """
    # ── Valores iniciales ──────────────────────────────────────────────────────
    regimen_empresa = st.session_state.get('empresa_activa_regimen', 'Régimen General')
    es_micro_empresa = "Micro Empresa" in regimen_empresa

    if t is None:
        t_doc_val, n_doc_val = "DNI", ""
        ap_pat_val, ap_mat_val, nombres_val = "", "", ""
        f_nac_val = datetime.date(1990, 1, 1)
        cargo_val, f_ingreso_val = "", datetime.date.today()
        s_base_val, situacion_val = 1025.0, "ACTIVO"
        s_pension_val, t_comision_val, cuspp_val = "ONP", "FLUJO", ""
        banco_val, n_cuenta_val, cci_val = "BCP", "", ""
        a_fam_val, eps_val = False, False
        seguro_social_val = "ESSALUD"
    else:
        opciones_doc = ["DNI", "CE", "PTP"]
        t_doc_val = t.tipo_doc if t.tipo_doc in opciones_doc else "DNI"
        n_doc_val = t.num_doc or ""
        ap_pat_val = getattr(t, 'apellido_paterno', '') or ''
        ap_mat_val = getattr(t, 'apellido_materno', '') or ''
        nombres_val = t.nombres or ""
        f_nac_val = t.fecha_nac or datetime.date(1990, 1, 1)
        cargo_val = t.cargo or ""
        f_ingreso_val = t.fecha_ingreso or datetime.date.today()
        s_base_val = float(t.sueldo_base or 1025.0)
        situacion_val = t.situacion or "ACTIVO"
        s_pension_val = t.sistema_pension or "ONP"
        t_comision_val = t.comision_afp or "FLUJO"
        cuspp_val = t.cuspp or ""
        banco_val = t.banco or "BCP"
        n_cuenta_val = t.cuenta_bancaria or ""
        cci_val = t.cci or ""
        a_fam_val = bool(t.asig_fam)
        eps_val = bool(t.eps)
        seguro_social_val = getattr(t, 'seguro_social', None) or "ESSALUD"

    # ── Sección 1: Identidad ───────────────────────────────────────────────────
    st.markdown("##### 1. Identidad y Datos Básicos")
    c1, c2, c5 = st.columns([1, 1.5, 1.5])

    opciones_doc = ["DNI", "CE", "PTP"]
    es_edicion = (t is not None)
    t_doc = c1.selectbox("Tipo Doc.", opciones_doc,
                         index=opciones_doc.index(t_doc_val),
                         key=f"{key_prefix}_tdoc", disabled=es_edicion)
    n_doc = c2.text_input("Nro. Documento", value=n_doc_val, max_chars=12,
                          key=f"{key_prefix}_ndoc", disabled=es_edicion)
    f_nac = c5.date_input("Fecha Nacimiento*", value=f_nac_val,
                          key=f"{key_prefix}_fnac")

    # Apellidos y nombres separados (requeridos para PLAME / AFPnet)
    r1, r2, r3 = st.columns([2, 2, 3])
    ap_pat = r1.text_input("Apellido Paterno*", value=ap_pat_val.upper(),
                           key=f"{key_prefix}_appat")
    ap_mat = r2.text_input("Apellido Materno*", value=ap_mat_val.upper(),
                           key=f"{key_prefix}_apmat")

    # Auto-búsqueda solo en Alta
    nombres_auto = nombres_val
    if not es_edicion and t_doc == "DNI" and len(n_doc) == 8:
        resultado = consultar_dni_automatico(n_doc)
        if resultado:
            nombres_auto = resultado["nombres"]
            st.toast(f"✅ Datos de {n_doc} encontrados", icon="👤")

    nombres = r3.text_input("Nombres (sin apellidos)*", value=nombres_auto.upper(),
                            key=f"{key_prefix}_nombres")

    # Nombre completo para compatibilidad con el resto del sistema
    nombre_completo = f"{ap_pat} {ap_mat} {nombres}".strip()

    # ── Sección 2: Información Laboral ─────────────────────────────────────────
    st.markdown("##### 2. Información Laboral")
    cl1, cl2, cl3, cl4 = st.columns(4)
    cargo = cl1.text_input("Cargo / Puesto", value=cargo_val, key=f"{key_prefix}_cargo")
    f_ingreso = cl2.date_input("Fecha de Ingreso*", value=f_ingreso_val,
                               key=f"{key_prefix}_fingreso")
    s_base = cl3.number_input("Sueldo Mensual (S/)*", min_value=1025.0, step=50.0,
                              value=s_base_val, key=f"{key_prefix}_sbase")
    opciones_sit = ["ACTIVO", "CESADO", "SUSPENDIDO"]
    situacion = cl4.selectbox("Situación", opciones_sit,
                              index=opciones_sit.index(situacion_val) if situacion_val in opciones_sit else 0,
                              key=f"{key_prefix}_situacion")

    # ── Sección 3: Régimen Pensionario ─────────────────────────────────────────
    st.markdown("##### 3. Régimen Pensionario")
    p1, p2, p3 = st.columns(3)
    opciones_pension = ["ONP", "AFP INTEGRA", "AFP PRIMA", "AFP PROFUTURO", "AFP HABITAT", "NO AFECTO"]
    s_pension = p1.selectbox("Sistema de Pensión", opciones_pension,
                             index=opciones_pension.index(s_pension_val) if s_pension_val in opciones_pension else 0,
                             key=f"{key_prefix}_pension")
    es_afp = s_pension.startswith("AFP")
    opciones_com = ["FLUJO", "MIXTA"]
    t_comision = p2.selectbox("Tipo de Comisión", opciones_com,
                              index=opciones_com.index(t_comision_val) if t_comision_val in opciones_com else 0,
                              disabled=not es_afp, key=f"{key_prefix}_comision")
    cuspp = p3.text_input("CUSPP", value=cuspp_val if es_afp else "",
                          disabled=not es_afp, key=f"{key_prefix}_cuspp")
    if es_afp:
        st.markdown(
            "<a href='https://servicios.sbs.gob.pe/ReporteSituacionPrevisional/Afil_Consulta.aspx' "
            "target='_blank' style='font-size:0.8em;color:#7F8C8D;text-decoration:none;'>"
            "🔍 <i>Verificar CUSPP en SBS — Superintendencia de Banca y Seguros</i></a>",
            unsafe_allow_html=True
        )

    # ── Sección 3b: Seguro de Salud ────────────────────────────────────────────
    st.markdown("##### 3b. Seguro de Salud del Empleador")
    if es_micro_empresa:
        opciones_seguro = ["ESSALUD", "SIS"]
        seg_idx = opciones_seguro.index(seguro_social_val) if seguro_social_val in opciones_seguro else 0
        seguro_social = st.radio(
            "Régimen de Seguro de Salud",
            opciones_seguro, index=seg_idx, horizontal=True,
            key=f"{key_prefix}_seguro",
            help="ESSALUD: 9% del sueldo bruto. SIS: S/ 15.00 fijo mensual (solo Micro Empresa)."
        )
        if seguro_social == "ESSALUD":
            st.caption("📋 ESSALUD — Aporte patronal: **9%** del total de remuneraciones.")
        else:
            st.caption("📋 SIS (Seguro Integral de Salud) — Aporte patronal fijo: **S/ 15.00** por mes.")
    else:
        seguro_social = "ESSALUD"
        st.caption("📋 ESSALUD — Aporte patronal: **9%** del total de remuneraciones (régimen estándar).")

    # ── Sección 4: Información de Pago ────────────────────────────────────────
    st.markdown("##### 4. Información de Pago")
    b1, b2, b3 = st.columns(3)
    opciones_banco = ["BCP", "BBVA", "INTERBANK", "SCOTIABANK", "BANBIF", "EFECTIVO/CHEQUE"]
    banco = b1.selectbox("Banco", opciones_banco,
                         index=opciones_banco.index(banco_val) if banco_val in opciones_banco else 0,
                         key=f"{key_prefix}_banco")
    es_banco = banco != "EFECTIVO/CHEQUE"
    n_cuenta = b2.text_input("Número de Cuenta", value=n_cuenta_val if es_banco else "",
                             disabled=not es_banco, key=f"{key_prefix}_ncuenta")
    cci = b3.text_input("CCI (20 dígitos)", value=cci_val if es_banco else "",
                        max_chars=20, disabled=not es_banco, key=f"{key_prefix}_cci")

    # ── Sección 5: Opciones ────────────────────────────────────────────────────
    st.markdown("---")
    col_opt1, col_opt2 = st.columns(2)
    a_fam = col_opt1.checkbox("Asignación Familiar", value=a_fam_val, key=f"{key_prefix}_afam")
    eps_afecto = col_opt2.checkbox("Afecto a EPS", value=eps_val, key=f"{key_prefix}_eps")

    label_btn = "💾 Guardar Cambios" if es_edicion else "💾 Registrar e Inscribir en la Nube"
    if st.button(label_btn, type="primary", use_container_width=True, key=f"{key_prefix}_btn"):
        if not n_doc or not nombres or s_base < 1025:
            st.error("❌ Complete los campos obligatorios: Documento, Nombres y Sueldo ≥ S/ 1,025.")
            return None
        return {
            "tipo_doc": t_doc,
            "num_doc": n_doc,
            "apellido_paterno": ap_pat.upper(),
            "apellido_materno": ap_mat.upper(),
            "nombres": nombre_completo.upper(),   # campo legado (nombre completo)
            "fecha_nac": f_nac,
            "cargo": cargo,
            "fecha_ingreso": f_ingreso,
            "sueldo_base": s_base,
            "situacion": situacion,
            "sistema_pension": s_pension,
            "comision_afp": t_comision if es_afp else "NO APLICA",
            "cuspp": cuspp if es_afp else "",
            "banco": banco,
            "cuenta_bancaria": n_cuenta if es_banco else "",
            "cci": cci if es_banco else "",
            "asig_fam": a_fam,
            "eps": eps_afecto,
            "seguro_social": seguro_social,
        }
    return None


def render():
    empresa_id = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')
    regimen_empresa = st.session_state.get('empresa_activa_regimen', 'Régimen General')
    fecha_acogimiento = st.session_state.get('empresa_acogimiento', None)

    if not empresa_id:
        st.error("⚠️ Seleccione una empresa en el Panel de Control para continuar.")
        return

    st.title("👥 Maestro de Personal")
    st.markdown(f"**Empresa:** {empresa_nombre} | **Régimen:** {regimen_empresa}")
    st.markdown("---")

    # Mostrar mensajes diferidos (sobreviven al st.rerun())
    if st.session_state.get('_msg_trabajador'):
        msg = st.session_state.pop('_msg_trabajador')
        st.success(msg)

    db = next(get_db())
    editando_id = st.session_state.get('_editando_trabajador_id')

    # ── MODO EDICIÓN ────────────────────────────────────────────────────────────
    if editando_id:
        t_edit = db.query(Trabajador).filter_by(id=editando_id).first()
        if not t_edit:
            st.session_state.pop('_editando_trabajador_id', None)
            st.rerun()

        st.subheader(f"✏️ Editando trabajador: {t_edit.nombres}")
        st.caption(f"DNI/CE: {t_edit.num_doc}  —  Solo se pueden editar datos laborales y de contacto.")
        st.markdown("---")

        datos = _render_form_trabajador(t=t_edit, key_prefix="edit")
        if datos:
            try:
                campos_editables = {k: v for k, v in datos.items() if k not in ("tipo_doc", "num_doc")}
                for campo, valor in campos_editables.items():
                    setattr(t_edit, campo, valor)
                db.commit()
                st.session_state.pop('_editando_trabajador_id', None)
                st.session_state['_msg_trabajador'] = f"✅ Trabajador **{t_edit.nombres}** actualizado correctamente."
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al actualizar: {e}")

        st.markdown("---")
        if st.button("← Volver al Directorio sin guardar", key="btn_cancelar_edit"):
            st.session_state.pop('_editando_trabajador_id', None)
            st.rerun()
        return  # No renderizar las tabs en modo edición

    # ── MODO NORMAL: TABS ───────────────────────────────────────────────────────
    tab_lista, tab_nuevo = st.tabs(["📋 Directorio de Personal", "➕ Alta de Trabajador"])

    with tab_lista:
        trabajadores_db = db.query(Trabajador).filter(Trabajador.empresa_id == empresa_id).all()
        if not trabajadores_db:
            st.info("No hay trabajadores registrados. Use la pestaña 'Alta de Trabajador'.")
        else:
            st.caption(f"{len(trabajadores_db)} trabajador(es) registrado(s)")
            for t in trabajadores_db:
                reg = determinar_regimen_trabajador(t.fecha_ingreso, regimen_empresa, fecha_acogimiento)
                with st.container(border=True):
                    c1, c2, c3, c4, c5 = st.columns([2.5, 1.5, 1.5, 1.5, 0.8])
                    c1.markdown(f"**{t.nombres}**")
                    c2.markdown(f"Doc: `{t.num_doc}`")
                    c3.markdown(f"{t.cargo or '—'}")
                    c4.markdown(f"S/ {t.sueldo_base:,.2f}")
                    if c5.button("✏️", key=f"edit_{t.id}", help="Editar trabajador"):
                        st.session_state['_editando_trabajador_id'] = t.id
                        st.rerun()

    with tab_nuevo:
        datos = _render_form_trabajador(key_prefix="nuevo")
        if datos:
            try:
                nuevo_t = Trabajador(empresa_id=empresa_id, **datos)
                db.add(nuevo_t)
                db.commit()
                st.session_state['_msg_trabajador'] = (
                    f"✅ ¡Trabajador **{datos['nombres']}** registrado e inscrito en la nube exitosamente!"
                )
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al guardar: {e}")
