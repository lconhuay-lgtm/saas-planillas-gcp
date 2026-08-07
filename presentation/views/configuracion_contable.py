"""
Configuración de Cuentas Contables — cuentas "de sistema" (no son Conceptos) usadas
para armar el Excel del Asiento de Planilla (importación a SISCONT). Una fila por
empresa. Los conceptos dinámicos (Sueldo Base, Asignación Familiar, y los que cree
cada empresa) usan en cambio el campo "Cuenta Contable" en Maestro de Conceptos.
"""
import streamlit as st

from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import ConfiguracionContable


def render():
    empresa_id = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre')

    if not empresa_id:
        st.error("⚠️ Seleccione una empresa para continuar.")
        return

    st.title("📒 Configuración de Cuentas Contables")
    st.markdown(f"**Empresa:** {empresa_nombre}")
    st.caption(
        "Estas cuentas se usan para armar el Excel de importación del Asiento de "
        "Planilla a SISCONT. No afectan ningún cálculo de sueldos ni de retenciones — "
        "son solo la referencia contable de cada monto."
    )
    st.markdown("---")

    usuario_rol = st.session_state.get('usuario_rol')
    if usuario_rol not in ('admin', 'supervisor'):
        st.info("🔒 Solo un Administrador o Supervisor puede editar la configuración contable.")
        return

    if st.session_state.get('_msg_config_contable'):
        st.success(st.session_state.pop('_msg_config_contable'))

    db = SessionLocal()
    try:
        cfg = db.query(ConfiguracionContable).filter_by(empresa_id=empresa_id).first()

        def _v(campo):
            return (getattr(cfg, campo, '') or '') if cfg else ''

        with st.form("form_config_contable"):
            st.markdown("##### Remuneraciones y horas")
            c1, c2 = st.columns(2)
            c_he25 = c1.text_input("Horas Extras 25%", value=_v('cuenta_horas_extra_25'))
            c_he35 = c2.text_input("Horas Extras 35%", value=_v('cuenta_horas_extra_35'))
            c_dvac = c1.text_input("Descanso Vacacional", value=_v('cuenta_descanso_vacacional'))
            c_dmed = c2.text_input("Descanso Médico", value=_v('cuenta_descanso_medico'))
            c_lgoce = c1.text_input("Licencia con Goce", value=_v('cuenta_licencia_goce'))

            st.markdown("---")
            st.markdown("##### EsSalud")
            c3, c4 = st.columns(2)
            c_ess_gasto = c3.text_input("EsSalud — Gasto (débito)", value=_v('cuenta_essalud_gasto'))
            c_ess_pasivo = c4.text_input("EsSalud — Por Pagar (crédito)", value=_v('cuenta_essalud_pasivo'))

            st.markdown("---")
            st.markdown("##### Pensiones y retenciones")
            c5, c6 = st.columns(2)
            c_onp = c5.text_input("ONP", value=_v('cuenta_onp'))
            c_5ta = c6.text_input("Retención 5ta Categoría", value=_v('cuenta_retencion_5ta'))
            c_habitat = c5.text_input("AFP Habitat", value=_v('cuenta_afp_habitat'))
            c_integra = c6.text_input("AFP Integra", value=_v('cuenta_afp_integra'))
            c_prima = c5.text_input("AFP Prima", value=_v('cuenta_afp_prima'))
            c_profuturo = c6.text_input("AFP Profuturo", value=_v('cuenta_afp_profuturo'))

            st.markdown("---")
            st.markdown("##### Pagos y cuentas por cobrar")
            c7, c8 = st.columns(2)
            c_remun_pagar = c7.text_input("Remuneraciones por Pagar (neto)", value=_v('cuenta_remuneraciones_por_pagar'))
            c_prestamos = c8.text_input("Préstamos al Personal (por cobrar)", value=_v('cuenta_prestamos_personal'))

            guardar = st.form_submit_button("💾 Guardar Configuración", type="primary", use_container_width=True)

        if guardar:
            try:
                if not cfg:
                    cfg = ConfiguracionContable(empresa_id=empresa_id)
                    db.add(cfg)
                cfg.cuenta_horas_extra_25 = c_he25.strip()
                cfg.cuenta_horas_extra_35 = c_he35.strip()
                cfg.cuenta_descanso_vacacional = c_dvac.strip()
                cfg.cuenta_descanso_medico = c_dmed.strip()
                cfg.cuenta_licencia_goce = c_lgoce.strip()
                cfg.cuenta_essalud_gasto = c_ess_gasto.strip()
                cfg.cuenta_essalud_pasivo = c_ess_pasivo.strip()
                cfg.cuenta_onp = c_onp.strip()
                cfg.cuenta_afp_habitat = c_habitat.strip()
                cfg.cuenta_afp_integra = c_integra.strip()
                cfg.cuenta_afp_prima = c_prima.strip()
                cfg.cuenta_afp_profuturo = c_profuturo.strip()
                cfg.cuenta_retencion_5ta = c_5ta.strip()
                cfg.cuenta_remuneraciones_por_pagar = c_remun_pagar.strip()
                cfg.cuenta_prestamos_personal = c_prestamos.strip()
                db.commit()
                st.session_state['_msg_config_contable'] = "✅ Configuración contable actualizada correctamente."
                st.rerun()
            except Exception as e:
                db.rollback()
                st.error(f"❌ Error al guardar: {e}")
    finally:
        db.close()
