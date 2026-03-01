import streamlit as st
import pandas as pd
import datetime
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, portrait
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from infrastructure.database.connection import get_db
from infrastructure.database.models import Trabajador, PlanillaMensual


def determinar_regimen_trabajador(fecha_ingreso, regimen_empresa, fecha_acogimiento):
    """Lógica legal de protección de derechos adquiridos"""
    if regimen_empresa == "Régimen General" or not fecha_acogimiento:
        return "Régimen General"
    if fecha_ingreso < fecha_acogimiento:
        return "Régimen General (Derechos Adquiridos)"
    return regimen_empresa


def generar_pdf_ficha_trabajador(t, empresa_nombre, empresa_ruc, regimen_empresa):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=portrait(A4), rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    elements = []

    C_NAVY = colors.HexColor("#0F2744")
    C_STEEL = colors.HexColor("#1E4D8C")
    C_LIGHT = colors.HexColor("#F0F4F9")

    st_title = ParagraphStyle('T', fontName="Helvetica-Bold", fontSize=15, textColor=C_NAVY, spaceAfter=5)
    st_sub = ParagraphStyle('S', fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#64748B"), spaceAfter=20)
    st_sec = ParagraphStyle('Sec', fontName="Helvetica-Bold", fontSize=11, textColor=C_STEEL, spaceAfter=10, spaceBefore=15)

    elements.append(Paragraph(f"{empresa_nombre.upper()}", st_title))
    elements.append(Paragraph(f"RUC: {empresa_ruc or '—'}  |  Régimen: {regimen_empresa or '—'}", st_sub))
    elements.append(Paragraph("FICHA DE REGISTRO DE PERSONAL", ParagraphStyle('H1', fontName="Helvetica-Bold", fontSize=13, alignment=TA_CENTER, spaceAfter=20)))

    # 1. Datos Personales
    elements.append(Paragraph("1. DATOS PERSONALES", st_sec))
    f_nac = t.fecha_nac.strftime('%d/%m/%Y') if t.fecha_nac else "—"
    data_per = [
        ["Documento:", f"{t.tipo_doc} - {t.num_doc}", "Fecha Nacimiento:", f_nac],
        ["Nombres:", t.nombres, "Apellidos:", f"{getattr(t, 'apellido_paterno', '')} {getattr(t, 'apellido_materno', '')}".strip()],
    ]
    t_per = Table(data_per, colWidths=[100, 160, 110, 140])
    t_per.setStyle(TableStyle([('FONTNAME', (0,0), (-1,-1), 'Helvetica'), ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'), ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('BACKGROUND', (0,0), (0,-1), C_LIGHT), ('BACKGROUND', (2,0), (2,-1), C_LIGHT), ('PADDING', (0,0), (-1,-1), 6)]))
    elements.append(t_per)

    # 2. Datos Laborales
    elements.append(Paragraph("2. DATOS LABORALES", st_sec))
    f_ing = t.fecha_ingreso.strftime('%d/%m/%Y') if t.fecha_ingreso else "—"
    tipo_c = "Locador de Servicio" if getattr(t, 'tipo_contrato', '') == 'LOCADOR' else "Planilla (5ta Cat.)"
    data_lab = [
        ["Tipo Contrato:", tipo_c, "Situación:", t.situacion],
        ["Cargo / Puesto:", t.cargo or "—", "Fecha Ingreso:", f_ing],
        ["Sueldo/Honorario:", f"S/ {float(t.sueldo_base or 0):,.2f}", "", ""],
    ]
    t_lab = Table(data_lab, colWidths=[100, 160, 110, 140])
    t_lab.setStyle(TableStyle([('FONTNAME', (0,0), (-1,-1), 'Helvetica'), ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'), ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('BACKGROUND', (0,0), (0,-1), C_LIGHT), ('BACKGROUND', (2,0), (2,-1), C_LIGHT), ('PADDING', (0,0), (-1,-1), 6)]))
    elements.append(t_lab)

    # 3. Bancarios y Previsionales
    elements.append(Paragraph("3. DATOS PREVISIONALES Y BANCARIOS", st_sec))
    data_ban = [
        ["Banco:", t.banco or "—", "Cuenta:", t.cuenta_bancaria or "—"],
        ["CCI:", t.cci or "—", "Sist. Pensión:", t.sistema_pension or "—"],
        ["CUSPP:", t.cuspp or "—", "Comisión AFP:", getattr(t, 'comision_afp', '—') or "—"],
        ["Seguro Social:", getattr(t, 'seguro_social', '—') or "—", "Asig. Familiar:", "Sí" if t.asig_fam else "No"],
    ]
    t_ban = Table(data_ban, colWidths=[100, 160, 110, 140])
    t_ban.setStyle(TableStyle([('FONTNAME', (0,0), (-1,-1), 'Helvetica'), ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'), ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('BACKGROUND', (0,0), (0,-1), C_LIGHT), ('BACKGROUND', (2,0), (2,-1), C_LIGHT), ('PADDING', (0,0), (-1,-1), 6)]))
    elements.append(t_ban)

    elements.append(Spacer(1, 60))
    elements.append(Paragraph("_" * 40, ParagraphStyle('F', alignment=TA_CENTER)))
    elements.append(Paragraph(f"Firma del Trabajador<br/>DNI: {t.num_doc}", ParagraphStyle('F2', alignment=TA_CENTER, fontName="Helvetica", fontSize=10)))

    doc.build(elements)
    buffer.seek(0)
    return buffer


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
        tipo_contrato_val = "PLANILLA"
        suspension_4ta_val = False
    else:
        opciones_doc = ["DNI", "CE", "PTP"]
        t_doc_val = t.tipo_doc if t.tipo_doc in opciones_doc else "DNI"
        n_doc_val = t.num_doc or ""
        ap_pat_val = getattr(t, 'apellido_paterno', '') or ''
        ap_mat_val = getattr(t, 'apellido_materno', '') or ''
        # Extraer solo primeros nombres (sin apellidos) para evitar duplicación al editar
        _full = t.nombres or ""
        _prefix = f"{ap_pat_val} {ap_mat_val}".strip().upper()
        if _prefix and _full.upper().startswith(_prefix):
            nombres_val = _full[len(_prefix):].strip()
        else:
            nombres_val = _full
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
        tipo_contrato_val = getattr(t, 'tipo_contrato', 'PLANILLA') or 'PLANILLA'
        suspension_4ta_val = bool(getattr(t, 'tiene_suspension_4ta', False) or False)

    # ── Tipo de Contratación ───────────────────────────────────────────────────
    opciones_contrato = ["Planilla (5ta Categoría)", "Locador de Servicio (4ta Categoría)"]
    idx_contrato = 1 if tipo_contrato_val == "LOCADOR" else 0
    tipo_contrato_sel = st.radio(
        "Tipo de Contratación",
        opciones_contrato,
        index=idx_contrato,
        horizontal=True,
        key=f"{key_prefix}_tipo_contrato",
        help="Planilla: empleado con vínculo laboral (5ta Cat.). Locador: contrato de servicios (4ta Cat.).",
    )
    es_locador = tipo_contrato_sel == "Locador de Servicio (4ta Categoría)"
    if es_locador:
        st.info("ℹ️ Modo **Locador de Servicio**: los campos de Pensión, Seguro, Asignación Familiar y EPS no aplican y quedan deshabilitados.")
    st.markdown("---")

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
                          min_value=datetime.date(1920, 1, 1),
                          max_value=datetime.date.today(),
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
                               min_value=datetime.date(1960, 1, 1),
                               max_value=datetime.date.today(),
                               key=f"{key_prefix}_fingreso")
    label_sueldo = "Honorario Base Mensual (S/)*" if es_locador else "Sueldo Mensual (S/)*"
    min_sueldo = 0.01 if es_locador else 1025.0
    s_base = cl3.number_input(label_sueldo, min_value=min_sueldo, step=50.0,
                              value=max(min_sueldo, s_base_val), key=f"{key_prefix}_sbase")
    opciones_sit = ["ACTIVO", "CESADO", "SUSPENDIDO"]
    situacion = cl4.selectbox("Situación", opciones_sit,
                              index=opciones_sit.index(situacion_val) if situacion_val in opciones_sit else 0,
                              key=f"{key_prefix}_situacion")

    # ── Sección 3: Régimen Pensionario ─────────────────────────────────────────
    st.markdown("##### 3. Régimen Pensionario")
    if es_locador:
        st.caption("⚠️ Los locadores **no tienen vínculo pensionario** con la empresa. AFP/ONP no aplica.")
        s_pension = "NO APLICA"
        t_comision = "NO APLICA"
        cuspp = ""
    else:
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
    if es_locador:
        st.caption("⚠️ Los locadores **no tienen seguro de salud** a cargo de la empresa. EsSalud/SIS no aplica.")
        seguro_social = "NO APLICA"
    elif es_micro_empresa:
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
    if es_locador:
        st.caption("⚠️ **Asignación Familiar** y **EPS** no aplican a locadores de servicio (no hay beneficios sociales).")
        a_fam = False
        eps_afecto = False
        tiene_suspension_4ta_val = st.checkbox(
            "🧾 Suspensión de Retenciones 4ta Categoría",
            value=suspension_4ta_val,
            key=f"{key_prefix}_susp4ta",
            help="Marque si el locador presenta constancia de suspensión de retenciones ante SUNAT. La retención del 8% quedará en S/ 0.00."
        )
    else:
        col_opt1, col_opt2 = st.columns(2)
        a_fam = col_opt1.checkbox("Asignación Familiar", value=a_fam_val, key=f"{key_prefix}_afam")
        eps_afecto = col_opt2.checkbox("Afecto a EPS", value=eps_val, key=f"{key_prefix}_eps")
        tiene_suspension_4ta_val = False

    label_btn = "💾 Guardar Cambios" if es_edicion else "💾 Registrar e Inscribir en la Nube"
    if st.button(label_btn, type="primary", use_container_width=True, key=f"{key_prefix}_btn"):
        if not n_doc or not nombres:
            st.error("❌ Complete los campos obligatorios: Documento y Nombres.")
            return None
        if not es_locador and s_base < 1025:
            st.error("❌ El Sueldo Mensual de un empleado de planilla debe ser ≥ S/ 1,025 (RMV).")
            return None
        es_afp_final = not es_locador and s_pension.startswith("AFP")
        return {
            "tipo_doc": t_doc,
            "num_doc": n_doc,
            "apellido_paterno": ap_pat.upper(),
            "apellido_materno": ap_mat.upper(),
            "nombres": nombre_completo.upper(),
            "fecha_nac": f_nac,
            "cargo": cargo,
            "fecha_ingreso": f_ingreso,
            "sueldo_base": s_base,
            "situacion": situacion,
            "tipo_contrato": "LOCADOR" if es_locador else "PLANILLA",
            "sistema_pension": s_pension,
            "comision_afp": t_comision if es_afp_final else "NO APLICA",
            "cuspp": cuspp if es_afp_final else "",
            "banco": banco,
            "cuenta_bancaria": n_cuenta if es_banco else "",
            "cci": cci if es_banco else "",
            "asig_fam": a_fam,
            "eps": eps_afecto,
            "seguro_social": seguro_social,
            "tiene_suspension_4ta": tiene_suspension_4ta_val,
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
            # --- Lógica de Ficha PDF ---
            ficha_id = st.session_state.get('_generar_ficha_id')
            if ficha_id:
                t_ficha = db.query(Trabajador).filter_by(id=ficha_id).first()
                if t_ficha:
                    st.info(f"📄 Generando ficha de **{t_ficha.nombres}**...")
                    buf_ficha = generar_pdf_ficha_trabajador(
                        t_ficha, empresa_nombre, 
                        st.session_state.get('empresa_activa_ruc', ''), 
                        regimen_empresa
                    )
                    col_fd1, col_fd2 = st.columns([1, 4])
                    col_fd1.download_button(
                        "📥 Descargar PDF", data=buf_ficha, 
                        file_name=f"Ficha_{t_ficha.num_doc}.pdf", mime="application/pdf", type="primary"
                    )
                    if col_fd2.button("✖️ Cerrar"):
                        st.session_state.pop('_generar_ficha_id', None)
                        st.rerun()
                    st.markdown("---")
            # ---------------------------

            st.caption(f"{len(trabajadores_db)} trabajador(es) registrado(s)")
            for t in trabajadores_db:
                determinar_regimen_trabajador(t.fecha_ingreso, regimen_empresa, fecha_acogimiento)
                with st.container(border=True):
                    c1, c2, c3, c4, c_pdf, c5, c6 = st.columns([2.5, 1.5, 1.3, 1.3, 0.5, 0.5, 0.5])
                    tipo_badge = "📋 Locador" if getattr(t, 'tipo_contrato', 'PLANILLA') == 'LOCADOR' else "🏢 Planilla"
                    c1.markdown(f"**{t.nombres}** `{tipo_badge}`")
                    c2.markdown(f"Doc: `{t.num_doc}`")
                    c3.markdown(f"{t.cargo or '—'}")
                    c4.markdown(f"S/ {t.sueldo_base:,.2f}")
                    
                    if c_pdf.button("📄", key=f"pdf_{t.id}", help="Generar Ficha PDF"):
                        st.session_state['_generar_ficha_id'] = t.id
                        st.rerun()

                    if c5.button("✏️", key=f"edit_{t.id}", help="Editar trabajador"):
                        st.session_state['_editando_trabajador_id'] = t.id
                        st.rerun()

                    # Botón eliminar (solo si no hay planilla cerrada con este trabajador)
                    confirmar_key = f"_confirmar_elim_{t.id}"
                    if st.session_state.get(confirmar_key):
                        # Modo confirmación
                        with st.container(border=True):
                            st.warning(f"⚠️ ¿Eliminar a **{t.nombres}** (`{t.num_doc}`)? Esta acción no se puede deshacer.")
                            bc1, bc2 = st.columns(2)
                            if bc1.button("✅ Sí, eliminar", key=f"confirm_si_{t.id}", type="primary"):
                                try:
                                    db.delete(t)
                                    db.commit()
                                    st.session_state.pop(confirmar_key, None)
                                    st.session_state['_msg_trabajador'] = f"🗑️ Trabajador **{t.nombres}** eliminado correctamente."
                                    st.rerun()
                                except Exception as e_del:
                                    st.error(f"❌ Error al eliminar: {e_del}")
                            if bc2.button("❌ Cancelar", key=f"confirm_no_{t.id}"):
                                st.session_state.pop(confirmar_key, None)
                                st.rerun()
                    else:
                        if c6.button("🗑️", key=f"del_{t.id}", help="Eliminar trabajador"):
                            # Verificar si aparece en alguna planilla cerrada
                            try:
                                import json as _jdel
                                planillas_cerradas = db.query(PlanillaMensual).filter_by(
                                    empresa_id=empresa_id, estado='CERRADA'
                                ).all()
                                en_cerrada = any(
                                    any(str(row.get('DNI', '')) == str(t.num_doc)
                                        for row in _jdel.loads(p.resultado_json or '[]'))
                                    for p in planillas_cerradas
                                )
                                if en_cerrada:
                                    st.error(
                                        f"❌ No se puede eliminar a **{t.nombres}**: aparece en una o más planillas cerradas. "
                                        "Cambie su situación a 'CESADO' en su lugar."
                                    )
                                else:
                                    st.session_state[confirmar_key] = True
                                    st.rerun()
                            except Exception as e_chk:
                                st.error(f"Error al verificar planillas: {e_chk}")

    with tab_nuevo:
        datos = _render_form_trabajador(key_prefix="nuevo")
        if datos:
            try:
                # Verificar que el DNI no esté ya registrado en esta empresa
                existente = db.query(Trabajador).filter_by(
                    empresa_id=empresa_id, num_doc=datos['num_doc']
                ).first()
                if existente:
                    st.error(
                        f"❌ Ya existe un trabajador con el documento **{datos['num_doc']}** "
                        f"(`{existente.nombres}`) registrado en esta empresa."
                    )
                else:
                    nuevo_t = Trabajador(empresa_id=empresa_id, **datos)
                    db.add(nuevo_t)
                    db.commit()
                    st.session_state['_msg_trabajador'] = (
                        f"✅ ¡Trabajador **{datos['nombres']}** registrado e inscrito en la nube exitosamente!"
                    )
                    st.rerun()
            except Exception as e:
                st.error(f"❌ Error al guardar: {e}")
