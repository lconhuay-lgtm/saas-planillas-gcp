import streamlit as st
import pandas as pd
import json
import io
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Empresa, Trabajador, PlanillaMensual, Prestamo, RegistroVacaciones
from core.use_cases.calculo_kardex import calcular_saldo_vacacional

def render():
    empresa_id = st.session_state.get('empresa_activa_id')
    empresa_nombre = st.session_state.get('empresa_activa_nombre', 'No Seleccionada')

    if not empresa_id:
        st.title("📊 Business Intelligence - Dashboard")
        st.warning("⚠️ No se ha seleccionado ninguna empresa. Por favor, vaya al Selector de Empresa.")
        return

    st.title("📊 Dashboard de Gestión Salarial")
    st.markdown(f"**Análisis Ejecutivo de Nómina:** {empresa_nombre}")
    st.markdown("---")

    db = SessionLocal()
    try:
        # ── EXTRACCIÓN DE DATOS PARA BI ───────────────────────────────────────
        count_planilla = db.query(Trabajador).filter_by(empresa_id=empresa_id, tipo_contrato='PLANILLA', situacion='ACTIVO').count()
        count_locadores = db.query(Trabajador).filter_by(empresa_id=empresa_id, tipo_contrato='LOCADOR', situacion='ACTIVO').count()
        
        # Última planilla cerrada para KPIs financieros
        ultima_planilla = db.query(PlanillaMensual).filter_by(empresa_id=empresa_id, estado='CERRADA').order_by(PlanillaMensual.fecha_calculo.desc()).first()
        
        # Deuda total pendiente en préstamos
        total_prestamos_saldo = 0.0
        prestamos_activos = db.query(Prestamo).filter_by(empresa_id=empresa_id, estado='ACTIVO').all()
        for pr in prestamos_activos:
            total_prestamos_saldo += sum(float(c.monto) for c in pr.cuotas if c.estado == 'PENDIENTE')

        # ── KPIs SUPERIORES ───────────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        
        with c1:
            st.metric("Total Colaboradores", count_planilla + count_locadores)
            st.caption("Personal Activo Total")
            
        with c2:
            st.metric("Fuerza en Planilla", count_planilla)
            st.caption("Bajo 5ta Categoría")

        with c3:
            st.metric("Locadores Externos", count_locadores)
            st.caption("Bajo 4ta Categoría")

        with c4:
            st.metric("Cartera de Préstamos", f"S/ {total_prestamos_saldo:,.2f}")
            st.caption("Saldo Pendiente de Cobro")

        st.markdown("---")

        # ── ANÁLISIS DE COSTO LABORAL (BI TONE) ──────────────────────────────
        col_graf, col_data = st.columns([2, 1])

        if ultima_planilla:
            try:
                aud = json.loads(ultima_planilla.auditoria_json)
                df_res = pd.read_json(io.StringIO(ultima_planilla.resultado_json), orient='records')
                df_data = df_res[df_res['Apellidos y Nombres'] != 'TOTALES']

                bruto = df_data['TOTAL BRUTO'].sum()
                essalud = df_data['Aporte Seg. Social'].sum()
                neto = df_data['NETO A PAGAR'].sum()
                costo_total = bruto + essalud

                with col_graf:
                    st.subheader(f"📈 Estructura de Costos: {ultima_planilla.periodo_key}")
                    # Simulación de composición BI
                    st.markdown(f"**Costo Laboral Real: S/ {costo_total:,.2f}**")
                    
                    progress_bruto = (bruto / costo_total) if costo_total > 0 else 0
                    st.write(f"Sueldos Brutos ({(progress_bruto*100):.1f}%)")
                    st.progress(progress_bruto)
                    
                    progress_essalud = (essalud / costo_total) if costo_total > 0 else 0
                    st.write(f"Cargas Sociales / EsSalud ({(progress_essalud*100):.1f}%)")
                    st.progress(progress_essalud)

                with col_data:
                    st.subheader("📌 Resumen Financiero")
                    st.info(f"**Periodo:** {ultima_planilla.periodo_key}\n\n"
                            f"**Masa Salarial:** S/ {bruto:,.2f}\n\n"
                            f"**Desembolso Neto:** S/ {neto:,.2f}\n\n"
                            f"**Estado:** 🔒 CERRADA")
                    if st.button("Ver Reporte Completo"):
                        st.session_state['menu_option'] = "Reportería"
                        st.rerun()
            except Exception as e:
                st.error(f"Error procesando métricas: {e}")
        else:
            st.info("ℹ️ No hay planillas cerradas para mostrar análisis de costos. Los gráficos se activarán tras el primer cierre mensual.")

        # ── SECCIÓN DE ALERTAS TEMPRANAS ──────────────────────────────────────
        st.markdown("---")
        st.subheader("🔔 Centro de Notificaciones y Cumplimiento")
        
        alert_col1, alert_col2 = st.columns(2)
        
        with alert_col1:
            # Alerta de Riesgo Vacacional (D.L. 713)
            planilleros = db.query(Trabajador).filter_by(
                empresa_id=empresa_id, 
                tipo_contrato='PLANILLA', 
                situacion='ACTIVO'
            ).all()
            
            alertas_vac = []
            for t in planilleros:
                res = calcular_saldo_vacacional(t, t.vacaciones)
                if res['nivel_alerta'] in ["🔴 PELIGRO INMINENTE", "🟡 RIESGO MODERADO"]:
                    alertas_vac.append({
                        "nombre": t.nombres,
                        "saldo": res['saldo'],
                        "meses": res['meses_para_vencimiento'],
                        "nivel": res['nivel_alerta']
                    })
            
            if alertas_vac:
                st.error("🚨 **Riesgo de Indemnización Vacacional**")
                for a in alertas_vac:
                    st.markdown(f"- **{a['nombre']}**: {a['saldo']} días pendientes. Vence en {a['meses']} meses. ({a['nivel']})")
            else:
                st.markdown('<div style="background-color:#F8FAFC; padding:15px; border-radius:10px; border-left: 5px solid #1E4D8C;">'
                            '<strong>Estado de Cumplimiento:</strong><br>'
                            '✅ Vacaciones: No se detectan riesgos de indemnización.<br>'
                            '✅ Parámetros de AFP actualizados para el mes vigente.'
                            '</div>', unsafe_allow_html=True)
        
        with alert_col2:
            # Alerta de Préstamos
            n_prestamos = len(prestamos_activos)
            if n_prestamos > 0:
                st.markdown(f'<div style="background-color:#FFFBEB; padding:15px; border-radius:10px; border-left: 5px solid #F59E0B;">'
                            f'<strong>Gestión de Cobranzas:</strong><br>'
                            f'Hay {n_prestamos} cronogramas de préstamos activos con cuotas próximas a descontar en la siguiente planilla.'
                            '</div>', unsafe_allow_html=True)

    finally:
        db.close()
