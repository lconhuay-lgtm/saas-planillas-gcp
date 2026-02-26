from core.use_cases.calculo_afp_onp import calcular_pensiones, calcular_essalud
from core.use_cases.calculo_quinta_cat import calcular_retencion_quinta_categoria

def generar_planilla_trabajador(
    trabajador, 
    conceptos_mes: list, 
    parametros_legales: dict, 
    mes_actual: int
) -> dict:
    """
    Orquesta el cálculo completo de un trabajador para un mes específico.
    """
    total_ingresos = 0.0
    total_descuentos = 0.0
    base_afp_onp = 0.0
    base_quinta_cat = 0.0
    base_essalud = 0.0

    # 1. Clasificar y sumar conceptos dinámicos
    for concepto in conceptos_mes:
        if concepto['tipo_concepto'] == 'INGRESO':
            total_ingresos += concepto['monto']
            if concepto['afecto_afp_onp']: base_afp_onp += concepto['monto']
            if concepto['afecto_quinta_cat']: base_quinta_cat += concepto['monto']
            if concepto['afecto_essalud']: base_essalud += concepto['monto']
            
        elif concepto['tipo_concepto'] == 'DESCUENTO':
            total_descuentos += concepto['monto']

    # 2. Calcular Pensiones (AFP/ONP)
    retencion_pension = calcular_pensiones(base_afp_onp, trabajador, parametros_legales)
    total_descuentos += retencion_pension['retencion_total']

    # 3. Calcular 5ta Categoría (Asumiendo datos históricos pasados en un dict para simplificar)
    retencion_quinta = calcular_retencion_quinta_categoria(
        mes_actual=mes_actual,
        remuneracion_mes=base_quinta_cat,
        remuneraciones_previas_anio=trabajador.renta_quinta_retenida_previa, # Ojo: aquí vendría el cálculo real de BD
        retenciones_previas_anio=0.0,
        trabajador=trabajador,
        uit=parametros_legales['uit']
    )
    total_descuentos += retencion_quinta

    # 4. Aportes del Empleador (EsSalud)
    aporte_essalud = calcular_essalud(base_essalud, trabajador, parametros_legales['rmv'])

    # 5. Consolidar Sábana
    neto_a_pagar = total_ingresos - total_descuentos

    return {
        "trabajador_id": trabajador.id,
        "nombres": trabajador.nombres_apellidos,
        "total_ingresos": round(total_ingresos, 2),
        "total_descuentos": round(total_descuentos, 2),
        "neto_a_pagar": round(neto_a_pagar, 2),
        "detalle_pensiones": retencion_pension,
        "retencion_5ta": round(retencion_quinta, 2),
        "aportes_patronales": {
            "essalud": round(aporte_essalud, 2)
        }
    }