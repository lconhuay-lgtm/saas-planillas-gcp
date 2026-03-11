import streamlit as st
import pandas as pd
from datetime import date
from infrastructure.database.connection import SessionLocal
from infrastructure.database.models import Trabajador, RegistroVacaciones
from core.use_cases.calculo_kardex import calcular_saldo_vacacional

def render():
    st.title("🌴 Kardex de Vacaciones")
    st.markdown("Gestión de cuenta corriente de periodos vacacionales (Gozados y Vendidos).")
    
    empresa_id = st.session_state.get('empresa_activa_id')
    if not empresa_id:
        st.error("Seleccione una empresa para gestionar el Kardex.")
        return

    db = SessionLocal()
    try:
        # Solo trabajadores en planilla (no locadores)
        trabajadores = db.query(Trabajador).filter_by(
            empresa_id=empresa_id, 
            tipo_contrato='PLANILLA'
        ).all()
        
        if not trabajadores:
            st.warning("No hay trabajadores en planilla registrados para esta empresa.")
            return

        opciones = {f"{t.num_doc} - {t.nombres}": t.id for t in trabajadores}
        sel_t_label = st.selectbox("Seleccione Trabajador:", list(opciones.keys()))
        t_id = opciones[sel_t_label]
        
        trabajador = db.query(Trabajador).filter_by(id=t_id).first()
        registros = db.query(RegistroVacaciones).filter_by(trabajador_id=t_id).all()
        
        resumen = calcular_saldo_vacacional(trabajador, registros)
        
        tab1, tab2, tab3 = st.tabs(["📊 Resumen y Saldo", "➕ Registrar Movimiento", "📋 Historial"])
        
        with tab1:
            st.subheader(f"Estado de Cuenta: {trabajador.nombres}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Días Devengados", f"{resumen['devengados']} d")
            c2.metric("Días Consumidos", f"{resumen['consumidos']} d")
            c3.metric("Saldo Actual", f"{resumen['saldo']} d", delta_color="normal")
            
            st.info(f"Cuota Anual configurada: **{trabajador.dias_vacaciones_anuales} días**. "
                    f"Meses de servicio computados: {resumen['meses_servicio']}.")

        with tab2:
            st.subheader("Nuevo Registro de Vacaciones")
            with st.form("form_vac"):
                col_f1, col_f2 = st.columns(2)
                f_ini = col_f1.date_input("Fecha Inicio", value=date.today())
                f_fin = col_f2.date_input("Fecha Fin", value=date.today())
                
                dias_cal = (f_fin - f_ini).days + 1
                st.caption(f"Días calendario seleccionados: {dias_cal}")
                
                c_g, c_v = st.columns(2)
                goz = c_g.number_input("Días Gozados", min_value=0, value=dias_cal)
                ven = c_v.number_input("Días Vendidos", min_value=0, value=0)
                
                per_ori = st.text_input("Periodo de Origen", placeholder="Ej: 2024-2025")
                obs = st.text_area("Observaciones")
                
                if st.form_submit_button("Guardar Registro"):
                    if f_ini > f_fin:
                        st.error("La fecha de inicio no puede ser posterior a la de fin.")
                    else:
                        nuevo = RegistroVacaciones(
                            trabajador_id=t_id,
                            fecha_inicio=f_ini,
                            fecha_fin=f_fin,
                            dias_gozados=goz,
                            dias_vendidos=ven,
                            periodo_origen=per_ori,
                            observaciones=obs
                        )
                        db.add(nuevo)
                        db.commit()
                        st.success("Registro guardado exitosamente.")
                        st.rerun()

        with tab3:
            st.subheader("Historial de Vacaciones")
            if not registros:
                st.info("No hay movimientos registrados.")
            else:
                hist_data = [{
                    "ID": r.id,
                    "Inicio": r.fecha_inicio,
                    "Fin": r.fecha_fin,
                    "Gozados": r.dias_gozados,
                    "Vendidos": r.dias_vendidos,
                    "Periodo": r.periodo_origen,
                    "Estado": r.estado
                } for r in registros]
                df_hist = pd.DataFrame(hist_data)
                st.dataframe(df_hist, use_container_width=True, hide_index=True)
                
                id_del = st.number_input("ID a eliminar para corrección:", min_value=0, step=1)
                if st.button("Eliminar Registro Seleccionado", type="secondary"):
                    reg_del = db.query(RegistroVacaciones).filter_by(id=id_del, trabajador_id=t_id).first()
                    if reg_del:
                        db.delete(reg_del)
                        db.commit()
                        st.toast("Registro eliminado")
                        st.rerun()
                    else:
                        st.error("ID no válido.")

    finally:
        db.close()
