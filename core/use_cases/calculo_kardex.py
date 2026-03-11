from datetime import date
from dateutil.relativedelta import relativedelta

def calcular_saldo_vacacional(trabajador, registros_vacaciones, fecha_calculo=None):
    """
    Calcula el saldo de vacaciones acumulado al día de hoy o fecha específica.
    Regla: Días devengados por meses completos de servicio.
    """
    if not fecha_calculo:
        fecha_calculo = date.today()
    
    # Si el trabajador está cesado, el cálculo es hasta su fecha de cese
    fecha_final = trabajador.fecha_cese if trabajador.fecha_cese else fecha_calculo
    
    if not trabajador.fecha_ingreso or trabajador.fecha_ingreso > fecha_final:
        return {'devengados': 0.0, 'consumidos': 0.0, 'saldo': 0.0, 'meses_servicio': 0}

    # Calcular meses completos de servicio
    delta = relativedelta(fecha_final, trabajador.fecha_ingreso)
    total_meses = (delta.years * 12) + delta.months
    
    # Días devengados (proporcional a su cuota anual configurada)
    cuota_anual = getattr(trabajador, 'dias_vacaciones_anuales', 30)
    devengados = round((cuota_anual / 12.0) * total_meses, 2)
    
    # Días consumidos (Gozados + Vendidos) de registros APROBADOS
    gozados = sum(r.dias_gozados for r in registros_vacaciones if r.estado == "APROBADO")
    vendidos = sum(r.dias_vendidos for r in registros_vacaciones if r.estado == "APROBADO")
    consumidos = gozados + vendidos
    
    return {
        'devengados': devengados,
        'consumidos': float(consumidos),
        'saldo': round(devengados - consumidos, 2),
        'meses_servicio': total_meses
    }
