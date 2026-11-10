from datetime import date, timedelta
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
        return {
            'devengados': 0.0, 'consumidos': 0.0, 'saldo': 0.0, 'meses_servicio': 0,
            'dias_sueltos': 0, 'fecha_efectivo_ini': trabajador.fecha_ingreso,
            'fecha_efectivo_fin': fecha_final, 'nivel_alerta': '🟢 OK', 'meses_para_vencimiento': 0,
        }

    # Meses completos de servicio + días sueltos del mes en curso. A diferencia de
    # Gratificación/CTS (que la ley trata como meses calendario, ver
    # core/use_cases/calculo_beneficios_sociales.py), las vacaciones truncas se pagan
    # por "dozavos y treintavos" (D.S. 012-92-TR Art. 23): el resto de días NO se
    # redondea a un mes completo ni se descarta — se paga proporcional al día. Un
    # redondeo binario (ej. >=15 días = mes completo) generaría un salto de hasta 2.5
    # días de golpe por un solo día de diferencia en la fecha de cese, sin sustento legal.
    #
    # +1 día: fecha_final es el ÚLTIMO DÍA TRABAJADO (inclusive), pero relativedelta
    # mide tiempo transcurrido de forma EXCLUSIVA del punto de partida (como un
    # cronómetro). Sin este ajuste, un mes calendario de 30 días trabajado por
    # completo (ej. 01/09 al 30/09) se contaría como "29 días sueltos" en vez de "1
    # mes completo" — un trabajador que cesa el último día del mes perdería un día
    # de cómputo frente a uno que renuncia el primer día del mes siguiente.
    delta = relativedelta(fecha_final + timedelta(days=1), trabajador.fecha_ingreso)
    total_meses = (delta.years * 12) + delta.months
    dias_sueltos = delta.days

    # Días devengados: dozavos por cada mes completo + treintavos por los días sueltos
    cuota_anual = getattr(trabajador, 'dias_vacaciones_anuales', 30)
    devengados = round(
        (cuota_anual / 12.0) * total_meses + (cuota_anual / 360.0) * dias_sueltos, 2
    )

    # Días consumidos (Gozados + Vendidos) de registros APROBADOS
    gozados = sum(r.dias_gozados for r in registros_vacaciones if r.estado == "APROBADO")
    vendidos = sum(r.dias_vendidos for r in registros_vacaciones if r.estado == "APROBADO")
    consumidos = gozados + vendidos
    
    # --- Lógica de Alerta de Vencimiento (Prevención Indemnización D.L. 713) ---
    saldo = round(devengados - consumidos, 2)
    nivel_alerta = "🟢 OK"
    meses_para_vencimiento = 0
    
    # La indemnización se genera si al mes 24 no se gozó el periodo ganado al mes 12.
    if saldo >= cuota_anual:
        fi = trabajador.fecha_ingreso
        meses_antiguedad = (fecha_calculo.year - fi.year) * 12 + fecha_calculo.month - fi.month
        
        # El vencimiento legal ocurre cada 12 meses a partir del mes 24 (24, 36, 48...)
        if meses_antiguedad >= 12:
            meses_para_vencimiento = 12 - (meses_antiguedad % 12)
            
            if meses_para_vencimiento <= 3:
                nivel_alerta = "🔴 PELIGRO INMINENTE"
            elif meses_para_vencimiento <= 6:
                nivel_alerta = "🟡 RIESGO MODERADO"

    return {
        'devengados': devengados,
        'consumidos': float(consumidos),
        'saldo': saldo,
        'meses_servicio': total_meses,
        'dias_sueltos': dias_sueltos,
        'fecha_efectivo_ini': trabajador.fecha_ingreso,
        'fecha_efectivo_fin': fecha_final,
        'nivel_alerta': nivel_alerta,
        'meses_para_vencimiento': meses_para_vencimiento
    }
