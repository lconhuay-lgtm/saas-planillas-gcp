def calcular_retencion_quinta_categoria(
    mes_actual: int, 
    remuneracion_mes: float, 
    remuneraciones_previas_anio: float, 
    retenciones_previas_anio: float, 
    trabajador, # Instancia de la clase Trabajador
    uit: float
) -> float:
    """
    Aplica el procedimiento oficial de SUNAT para retención de 5ta Categoría.
    """
    # 1. Proyección de la Renta Anual
    meses_restantes = 12 - mes_actual
    remuneracion_proyectada = remuneracion_mes * meses_restantes
    
    # Gratificaciones proyectadas (Julio y Diciembre)
    # Si el régimen es MYPE Microempresa, no hay grati. Si es Pequeña, es la mitad.
    grati_proyectada = 0.0
    if trabajador.empresa_regimen == 'GENERAL':
        if mes_actual <= 7:
            grati_proyectada = remuneracion_mes * 2 # Falta Julio y Diciembre
        elif mes_actual <= 12:
            grati_proyectada = remuneracion_mes * 1 # Falta solo Diciembre
            
    # Renta Bruta Anual
    renta_bruta_anual = (
        remuneraciones_previas_anio + 
        remuneracion_mes + 
        remuneracion_proyectada + 
        grati_proyectada
    )
    
    # 2. Deducción de 7 UIT
    renta_neta_anual = renta_bruta_anual - (7 * uit)
    if renta_neta_anual <= 0:
        return 0.0  # No está afecto a retención

    # 3. Cálculo del Impuesto Anual (Tramos SUNAT)
    impuesto_anual = 0.0
    tramos = [
        (5 * uit, 0.08),
        (15 * uit, 0.14), # De 5 a 20 UIT (15 UIT de diferencia)
        (15 * uit, 0.17), # De 20 a 35 UIT 
        (10 * uit, 0.20), # De 35 a 45 UIT
        (float('inf'), 0.30) # Más de 45 UIT
    ]
    
    saldo_afecto = renta_neta_anual
    for limite, tasa in tramos:
        if saldo_afecto > 0:
            monto_tramo = min(saldo_afecto, limite)
            impuesto_anual += monto_tramo * tasa
            saldo_afecto -= monto_tramo

    # 4. Cálculo de la Retención Mensual (Los Divisores de SUNAT)
    # Se restan las retenciones de meses anteriores y las de empleadores previos
    impuesto_a_retener = impuesto_anual - retenciones_previas_anio - trabajador.renta_quinta_retenida_previa
    
    if impuesto_a_retener <= 0:
        return 0.0

    if mes_actual in [1, 2, 3]:
        retencion_mes = impuesto_anual / 12
    elif mes_actual == 4:
        retencion_mes = impuesto_a_retener / 9
    elif mes_actual in [5, 6, 7]:
        retencion_mes = impuesto_a_retener / 8
    elif mes_actual == 8:
        retencion_mes = impuesto_a_retener / 5
    elif mes_actual in [9, 10, 11]:
        retencion_mes = impuesto_a_retener / 4
    elif mes_actual == 12:
        retencion_mes = impuesto_a_retener / 1
    else:
        retencion_mes = 0.0
        
    return round(retencion_mes, 2)