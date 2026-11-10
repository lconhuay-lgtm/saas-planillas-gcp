import streamlit as st
import datetime

from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Trabajador, LiquidacionCese
from core.use_cases.calculo_liquidacion_cese import (
    calcular_liquidacion, _periodo_cts_de_fecha, _obtener_grati_referencia_cts, rmv_vigente,
)
from core.domain.exceptions import ReglaNegocioError
from core.use_cases.generador_pdf_liquidacion import generar_pdf_liquidacion
from core.use_cases.envio_correos import enviar_liquidacion_por_correo, encriptar_pdf_en_memoria
from core.use_cases.generador_asiento_liquidacion import generar_asiento_liquidacion
from core.use_cases.generador_asiento_contable import AsientoContableError


def render():
    empresa_id      = st.session_state.get('empresa_activa_id')
    empresa_nombre  = st.session_state.get('empresa_activa_nombre')
    regimen_empresa = st.session_state.get('empresa_activa_regimen', 'Régimen General')
    fecha_acogimiento = st.session_state.get('empresa_acogimiento', None)
    factor_grati_empresa = st.session_state.get('empresa_factor_grati', None)

    if not empresa_id:
        st.error("⚠️ Seleccione una empresa en el Panel de Control para continuar.")
        return

    st.title("📄 Liquidación por Cese")
    st.markdown(f"**Empresa:** {empresa_nombre} | **Régimen:** {regimen_empresa}")
    st.markdown("---")

    if st.session_state.get('_msg_liquidacion'):
        st.success(st.session_state.pop('_msg_liquidacion'))

    db = SessionLocal()
    try:
        trabajadores = (
            db.query(Trabajador)
            .filter(
                Trabajador.empresa_id == empresa_id,
                Trabajador.tipo_contrato != 'LOCADOR',
            )
            .order_by(Trabajador.nombres)
            .all()
        )

        if not trabajadores:
            st.warning("No hay trabajadores de planilla registrados.")
            return

        # ── Selector de trabajador ───────────────────────────────────────────
        opciones_trab = {f"{t.nombres} — DNI {t.num_doc}": t for t in trabajadores}

        # Preselección al llegar desde el botón "Generar Liquidación Ahora" de Traslado
        _preseleccionar_id = st.session_state.pop('_liq_preseleccionar_trabajador_id', None)
        if _preseleccionar_id:
            _match = next((label for label, tw in opciones_trab.items() if tw.id == _preseleccionar_id), None)
            if _match:
                st.session_state['liq_sel_trab'] = _match

        sel = st.selectbox("Trabajador", list(opciones_trab.keys()), key="liq_sel_trab")
        t = opciones_trab[sel]

        col1, col2 = st.columns(2)
        fecha_ingreso_val = t.fecha_ingreso or datetime.date.today()
        fecha_cese_val    = getattr(t, 'fecha_cese', None) or datetime.date.today()

        with col1:
            st.markdown("##### Datos del trabajador")
            st.write(f"**Sueldo Base:** S/ {t.sueldo_base:,.2f}")
            st.write(f"**Asig. Familiar:** {'Sí' if t.asig_fam else 'No'}")
            st.write(f"**Fecha Ingreso:** {fecha_ingreso_val.strftime('%d/%m/%Y')}")

        with col2:
            st.markdown("##### Parámetros de cese")
            fecha_cese_inp = st.date_input(
                "Fecha de cese", value=fecha_cese_val, min_value=fecha_ingreso_val,
                max_value=datetime.date.today() + datetime.timedelta(days=365),
                key="liq_fecha_cese",
            )
            incluye_sueldo_mes = st.checkbox(
                "Incluir sueldo proporcional del mes de cese", value=False,
                key="liq_incluye_sueldo",
                help="Déjelo SIN marcar si esta empresa corre planilla regular para el mes de "
                     "cese — esa planilla ya paga el sueldo prorrateado. Actívelo solo si NO se "
                     "va a procesar planilla regular ese mes, para no pagarlo dos veces.",
            )
            bono_cese_input = st.number_input(
                "Bono / Incentivo por Cese (S/) — opcional", min_value=0.0, step=50.0, value=0.0,
                key="liq_bono_cese",
                help="Monto pactado con el trabajador, adicional a lo que exige la ley (código "
                     "SUNAT 0906). Totalmente exento — no afecto a AFP/ONP, 5ta ni EsSalud.",
            )

        # ── Gratificación de referencia para el 1/6 de CTS ───────────────────────
        # No es la gratificación trunca (esa es un beneficio nuevo por el cese) sino
        # la gratificación ORDINARIA ya pagada del semestre que cae dentro del
        # periodo de CTS (julio para MAY-OCT, diciembre para NOV-ABR).
        periodo_cts_prev, anio_dep_cts_prev = _periodo_cts_de_fecha(fecha_cese_inp)
        try:
            rmv_prev = rmv_vigente(db, empresa_id, fecha_cese_inp)
        except ReglaNegocioError as e_rmv:
            st.error(f"❌ {e_rmv}")
            return
        grati_ref_detectada = _obtener_grati_referencia_cts(
            db, t, empresa_id, periodo_cts_prev, anio_dep_cts_prev,
            regimen_empresa, fecha_acogimiento, factor_grati_empresa, rmv_prev,
        )
        _fuente_txt = {
            'planilla': '✅ detectado de la planilla ya procesada',
            'estimado': '⚠️ estimado (no se encontró el pago real registrado) — verifique antes de continuar',
        }[grati_ref_detectada['fuente']]
        st.markdown("##### Gratificación de referencia para el 1/6 de CTS")
        st.caption(
            f"Periodo de referencia: **{grati_ref_detectada['periodo_key_ref']}** — {_fuente_txt}. "
            f"Corríjalo si el monto real pagado fue distinto."
        )
        grati_ref_input = st.number_input(
            "Monto de gratificación de referencia (S/)", min_value=0.0, step=10.0,
            value=float(grati_ref_detectada['monto']),
            key=f"liq_grati_ref_{t.id}_{fecha_cese_inp.isoformat()}",
        )

        st.markdown("---")

        if st.button("🧮 Calcular Liquidación", type="primary", use_container_width=True):
            if fecha_cese_inp < fecha_ingreso_val:
                st.error("La fecha de cese no puede ser anterior a la fecha de ingreso.")
            else:
                try:
                    liq = calcular_liquidacion(
                        db, t, empresa_id, fecha_cese_inp, regimen_empresa,
                        fecha_acogimiento=fecha_acogimiento, factor_override=factor_grati_empresa,
                        incluye_sueldo_mes_cese=incluye_sueldo_mes, monto_bono_cese=bono_cese_input,
                        grati_referencia_cts=grati_ref_input,
                    )
                except ReglaNegocioError as e_regla:
                    st.error(f"❌ {e_regla}")
                    liq = None
                if liq is not None:
                    st.session_state['_liq_calculada'] = liq
                    st.session_state['_liq_trabajador_id'] = t.id

        liq = st.session_state.get('_liq_calculada')
        if liq and st.session_state.get('_liq_trabajador_id') == t.id:
            st.success(f"**Total neto a pagar al trabajador: S/ {liq['total_neto']:,.2f}**")
            if liq.get('aviso_5ta'):
                st.warning(f"⚠️ {liq['aviso_5ta']}")
            st.markdown("---")
            st.markdown("#### Desglose de Liquidación")

            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("##### Conceptos (ingresos)")
                items = []
                if liq['incluye_sueldo_mes_cese']:
                    items.append((f"Sueldo proporcional ({liq['dias_laborados_mes_cese']} días)", liq['monto_sueldo_proporcional']))
                items += [
                    (f"Vacaciones truncas ({liq['dias_vacaciones_pendientes']:.0f} días)", liq['monto_vacaciones_truncas']),
                    (f"Gratificación trunca ({liq['meses_grati']} mes(es), {liq['periodo_grati_ref']})", liq['monto_grati_trunca']),
                    ("Bonificación Extraordinaria (Ley 30334)", liq['monto_bono_9']),
                    (f"CTS trunca ({liq['meses_cts']} meses, {liq['periodo_cts_ref']})", liq['monto_cts_trunca']),
                ]
                if liq['monto_bono_cese'] > 0:
                    items.append(("Bono/Incentivo por Cese (exento)", liq['monto_bono_cese']))
                for concepto, monto in items:
                    mc1, mc2 = st.columns([3, 1])
                    mc1.write(concepto)
                    mc2.write(f"S/ {monto:,.2f}")
                _fuente_cts_txt = {
                    'planilla': 'detectada de planilla', 'estimado': 'estimada', 'manual': 'ingresada manualmente',
                }.get(liq.get('grati_referencia_cts_fuente'), '')
                st.caption(
                    f"ℹ️ 1/6 de gratificación usado en la base de CTS: S/ {liq['grati_referencia_cts']:,.2f} "
                    f"({liq['grati_referencia_cts_periodo']}, {_fuente_cts_txt})"
                )
                st.markdown("---")
                tc1, tc2 = st.columns([3, 1])
                tc1.markdown("**TOTAL BRUTO**")
                tc2.markdown(f"**S/ {liq['total_bruto']:,.2f}**")

                st.markdown("##### Deducciones")
                if liq['monto_pension_afp_onp'] > 0:
                    dc1, dc2 = st.columns([3, 1])
                    dc1.write(f"{liq['sistema_pension']} (sobre vacaciones truncas{'  y sueldo prop.' if liq['incluye_sueldo_mes_cese'] else ''})")
                    dc2.write(f"S/ {liq['monto_pension_afp_onp']:,.2f}")
                if liq['monto_prestamos_pendientes'] > 0:
                    dc1, dc2 = st.columns([3, 1])
                    dc1.write("Préstamos/adelantos pendientes")
                    dc2.write(f"S/ {liq['monto_prestamos_pendientes']:,.2f}")
                if liq['monto_retencion_5ta'] > 0:
                    dc1, dc2 = st.columns([3, 1])
                    dc1.write("Retención 5ta Categoría (vacaciones + grati trunca + bono)")
                    dc2.write(f"S/ {liq['monto_retencion_5ta']:,.2f}")
                st.markdown("---")
                nc1, nc2 = st.columns([3, 1])
                nc1.markdown("**TOTAL NETO A PAGAR**")
                nc2.markdown(f"**S/ {liq['total_neto']:,.2f}**")

                if liq['monto_essalud_vacaciones'] > 0:
                    st.caption(
                        f"ℹ️ Aporte patronal EsSalud sobre vacaciones truncas (no afecta el "
                        f"neto del trabajador): S/ {liq['monto_essalud_vacaciones']:,.2f}"
                    )

            with col_b:
                st.markdown("##### Bases de cálculo (auditoría)")
                st.write(f"Régimen aplicable al trabajador: {liq['detalle_grati']['regimen_trab']}")
                st.write(f"Base computable grati/CTS: S/ {liq['detalle_grati']['base_computable']:,.2f}")
                st.write(f"Factor gratificación: {liq['detalle_grati']['factor_grati']*100:.0f}%")
                st.write(f"Factor CTS: {liq['detalle_cts']['factor_cts']*100:.0f}%")
                st.write(f"Base CTS (incl. 1/6 grati): S/ {liq['base_cts']:,.2f}")
                fecha_cts_txt = liq['fecha_ultimo_deposito_cts'].strftime('%d/%m/%Y') if liq['fecha_ultimo_deposito_cts'] else "Sin depósitos registrados"
                st.write(f"Último depósito CTS registrado: {fecha_cts_txt}")
                st.write(f"Saldo de vacaciones (Kardex): {liq['dias_vacaciones_pendientes']:.0f} días")

            st.markdown("---")
            if st.button("💾 Guardar Liquidación (Borrador)", type="primary", use_container_width=True, key="btn_guardar_liq"):
                try:
                    nueva_liq = LiquidacionCese(
                        empresa_id=empresa_id,
                        trabajador_id=t.id,
                        generado_por=st.session_state.get('usuario_logueado'),
                        fecha_ingreso_snapshot=liq['fecha_ingreso'],
                        fecha_cese_snapshot=liq['fecha_cese'],
                        sueldo_base_snapshot=liq['sueldo_base'],
                        incluye_sueldo_mes_cese=liq['incluye_sueldo_mes_cese'],
                        monto_sueldo_proporcional=liq['monto_sueldo_proporcional'],
                        dias_laborados_mes_cese=liq['dias_laborados_mes_cese'],
                        dias_vacaciones_pendientes=liq['dias_vacaciones_pendientes'],
                        monto_vacaciones_truncas=liq['monto_vacaciones_truncas'],
                        vac_devengados=liq['vac_devengados'],
                        vac_consumidos=liq['vac_consumidos'],
                        vac_meses_completos=liq['vac_meses_completos'],
                        vac_dias_sueltos=liq['vac_dias_sueltos'],
                        periodo_grati_ref=liq['periodo_grati_ref'],
                        meses_grati=liq['meses_grati'],
                        monto_grati_trunca=liq['monto_grati_trunca'],
                        monto_bono_9=liq['monto_bono_9'],
                        grati_base_computable=liq['grati_base_computable'],
                        grati_factor=liq['grati_factor'],
                        grati_fecha_efectivo_ini=liq['grati_fecha_efectivo_ini'],
                        grati_fecha_efectivo_fin=liq['grati_fecha_efectivo_fin'],
                        periodo_cts_ref=liq['periodo_cts_ref'],
                        meses_cts=liq['meses_cts'],
                        base_cts=liq['base_cts'],
                        monto_cts_trunca=liq['monto_cts_trunca'],
                        cts_remuneracion_base=liq['cts_remuneracion_base'],
                        cts_factor=liq['cts_factor'],
                        cts_dias_sueltos=liq['cts_dias_sueltos'],
                        cts_fecha_efectivo_ini=liq['cts_fecha_efectivo_ini'],
                        cts_fecha_efectivo_fin=liq['cts_fecha_efectivo_fin'],
                        fecha_ultimo_deposito_cts=liq['fecha_ultimo_deposito_cts'],
                        grati_referencia_cts=liq['grati_referencia_cts'],
                        grati_referencia_cts_fuente=liq['grati_referencia_cts_fuente'],
                        grati_referencia_cts_periodo=liq['grati_referencia_cts_periodo'],
                        monto_prestamos_pendientes=liq['monto_prestamos_pendientes'],
                        monto_retencion_5ta=liq['monto_retencion_5ta'],
                        sistema_pension_snapshot=liq['sistema_pension'],
                        monto_pension_afp_onp=liq['monto_pension_afp_onp'],
                        monto_aporte_afp=liq['monto_aporte_afp'],
                        monto_prima_afp=liq['monto_prima_afp'],
                        monto_comision_afp=liq['monto_comision_afp'],
                        monto_essalud_vacaciones=liq['monto_essalud_vacaciones'],
                        monto_bono_cese=liq['monto_bono_cese'],
                        total_bruto=liq['total_bruto'],
                        total_neto=liq['total_neto'],
                        estado='BORRADOR',
                    )
                    db.add(nueva_liq)
                    db.commit()
                    st.session_state.pop('_liq_calculada', None)
                    st.session_state.pop('_liq_trabajador_id', None)
                    st.session_state['_msg_liquidacion'] = (
                        f"✅ Liquidación de **{t.nombres}** guardada como BORRADOR "
                        f"(Total Neto: S/ {liq['total_neto']:,.2f})."
                    )
                    st.rerun()
                except Exception as e_liq:
                    db.rollback()
                    st.error(f"❌ Error al guardar: {e_liq}")

        # ── Historial de liquidaciones ya generadas ──────────────────────────
        st.markdown("---")
        st.markdown("#### 🗂️ Liquidaciones Generadas")

        usuario_rol = st.session_state.get('usuario_rol')
        usuario_actual = st.session_state.get('usuario_logueado')
        puede_aprobar = usuario_rol in ('admin', 'supervisor')

        historial = (
            db.query(LiquidacionCese)
            .filter_by(empresa_id=empresa_id)
            .order_by(LiquidacionCese.fecha_generacion.desc())
            .all()
        )
        if not historial:
            st.caption("Todavía no se ha guardado ninguna liquidación en esta empresa.")
        else:
            for h in historial:
                th = db.query(Trabajador).filter_by(id=h.trabajador_id).first()
                nombre_h = th.nombres if th else f"(trabajador id {h.trabajador_id})"
                badge = {"BORRADOR": "🟡", "APROBADA": "🔵", "PAGADA": "✅"}.get(h.estado, "⚪")
                with st.container(border=True):
                    hc1, hc2, hc3, hc4, hc5, hc6 = st.columns([2.1, 1.1, 1.1, 0.9, 0.6, 0.6])
                    hc1.markdown(f"**{nombre_h}**")
                    hc2.write(f"Cese: {h.fecha_cese_snapshot.strftime('%d/%m/%Y')}")
                    hc3.write(f"Neto: S/ {h.total_neto:,.2f}")
                    hc4.markdown(f"{badge} {h.estado}")
                    if th:
                        empresa_info_pdf = {
                            'nombre': empresa_nombre,
                            'ruc': st.session_state.get('empresa_activa_ruc', ''),
                            'domicilio': st.session_state.get('empresa_activa_domicilio', ''),
                            'representante': st.session_state.get('empresa_activa_representante', ''),
                        }
                        buf_liq = generar_pdf_liquidacion(empresa_info_pdf, th, h)
                        hc5.download_button(
                            "📄", data=buf_liq, file_name=f"LIQUIDACION_{th.num_doc}_{h.id}.pdf",
                            mime="application/pdf", key=f"pdf_liq_{h.id}", help="Descargar PDF",
                        )
                        if getattr(th, 'correo_electronico', None):
                            if hc6.button("📧", key=f"mail_liq_{h.id}", help=f"Enviar por correo a {th.correo_electronico}"):
                                buf_para_enviar = generar_pdf_liquidacion(empresa_info_pdf, th, h)
                                pdf_encriptado = encriptar_pdf_en_memoria(buf_para_enviar, th.num_doc)
                                with st.spinner("Enviando..."):
                                    resultado_envio = enviar_liquidacion_por_correo(
                                        th.correo_electronico, th.nombres, empresa_nombre, pdf_encriptado,
                                    )
                                if resultado_envio is True:
                                    st.success(f"✅ Enviado a {th.correo_electronico}")
                                else:
                                    st.error(f"❌ Error al enviar: {resultado_envio}")
                        else:
                            hc6.caption("Sin correo")

                    # ── Workflow de aprobación (BORRADOR → APROBADA → PAGADA) ──
                    if h.estado == "PAGADA":
                        fecha_pago_txt = h.fecha_pago.strftime('%d/%m/%Y') if h.fecha_pago else '—'
                        st.caption(f"✅ Pagada el {fecha_pago_txt}. Documento cerrado — ya no admite cambios.")

                    elif not puede_aprobar:
                        st.caption("🔒 Solo un Administrador o Supervisor puede aprobar o marcar el pago.")

                    elif h.estado == "BORRADOR":
                        wc1, wc2 = st.columns(2)
                        if wc1.button("✅ Aprobar", key=f"aprobar_{h.id}", type="primary", use_container_width=True):
                            h.estado = "APROBADA"
                            h.aprobado_por = usuario_actual
                            h.fecha_aprobacion = datetime.datetime.now()
                            db.commit()
                            st.rerun()
                        confirmar_del_key = f"_confirmar_elim_liq_{h.id}"
                        if st.session_state.get(confirmar_del_key):
                            st.warning("⚠️ ¿Eliminar este borrador? Esta acción no se puede deshacer.")
                            wd1, wd2 = st.columns(2)
                            if wd1.button("Sí, eliminar", key=f"conf_si_liq_{h.id}", type="primary", use_container_width=True):
                                db.delete(h)
                                db.commit()
                                st.session_state.pop(confirmar_del_key, None)
                                st.rerun()
                            if wd2.button("Cancelar", key=f"conf_no_liq_{h.id}", use_container_width=True):
                                st.session_state.pop(confirmar_del_key, None)
                                st.rerun()
                        else:
                            if wc2.button("🗑️ Eliminar Borrador", key=f"del_liq_{h.id}", use_container_width=True):
                                st.session_state[confirmar_del_key] = True
                                st.rerun()

                    elif h.estado == "APROBADA":
                        st.caption(f"🔵 Aprobada por **{h.aprobado_por}** el {h.fecha_aprobacion.strftime('%d/%m/%Y %H:%M')}.")
                        marcar_pago_key = f"_marcando_pagada_{h.id}"
                        if st.session_state.get(marcar_pago_key):
                            fecha_pago_sel = st.date_input(
                                "Fecha en que se realizó el pago", value=datetime.date.today(),
                                max_value=datetime.date.today(), key=f"fp_input_{h.id}",
                            )
                            wp1, wp2 = st.columns(2)
                            if wp1.button("Confirmar Pago", key=f"conf_pago_{h.id}", type="primary", use_container_width=True):
                                h.estado = "PAGADA"
                                h.fecha_pago = fecha_pago_sel
                                db.commit()
                                st.session_state.pop(marcar_pago_key, None)
                                st.rerun()
                            if wp2.button("Cancelar", key=f"canc_pago_{h.id}", use_container_width=True):
                                st.session_state.pop(marcar_pago_key, None)
                                st.rerun()
                        else:
                            wc1, wc2 = st.columns(2)
                            if wc1.button("💰 Marcar como Pagada", key=f"pagar_{h.id}", type="primary", use_container_width=True):
                                st.session_state[marcar_pago_key] = True
                                st.rerun()
                            if wc2.button("↩️ Volver a Borrador", key=f"desaprobar_{h.id}", use_container_width=True):
                                h.estado = "BORRADOR"
                                h.aprobado_por = None
                                h.fecha_aprobacion = None
                                db.commit()
                                st.rerun()

                    # ── Asiento Contable (disponible desde APROBADA en adelante) ──
                    if h.estado in ("APROBADA", "PAGADA"):
                        try:
                            buf_asiento = generar_asiento_liquidacion(db, empresa_id, h.id)
                            st.download_button(
                                "📒 Descargar Asiento Contable (Excel)", data=buf_asiento,
                                file_name=f"ASIENTO_LIQUIDACION_{h.id}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key=f"asiento_liq_{h.id}", use_container_width=True,
                            )
                        except AsientoContableError as e_asiento:
                            st.warning(f"📒 Asiento Contable: {e_asiento.mensaje}")
                            if e_asiento.cuentas_faltantes:
                                st.caption("Cuentas por configurar: " + ", ".join(e_asiento.cuentas_faltantes))
    finally:
        db.close()
