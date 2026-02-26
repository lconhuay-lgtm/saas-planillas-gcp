def calcular_pensiones(sueldo_computable: float, trabajador, parametros: dict) -> dict:
    """
    Calcula la retención por pensiones (ONP o AFP).
    Retorna un diccionario con el desglose exacto.
    """
    if trabajador.sistema_pension == 'ONP':
        return {
            'tipo': 'ONP',
            'retencion_total': round(sueldo_computable * 0.13, 2),
            'desglose': {'aporte': round(sueldo_computable * 0.13, 2), 'comision': 0.0, 'prima': 0.0}
        }
    
    # Lógica para AFP
    tasa_afp = parametros['tasas_afp'].get(trabajador.sistema_pension)
    if not tasa_afp:
        raise ValueError(f"No hay tasas configuradas para la AFP: {trabajador.sistema_pension}")

    # Aporte obligatorio siempre es 10%
    aporte_obligatorio = sueldo_computable * 0.10
    
    # Prima de seguro tiene un tope máximo (S/ 16,200 aprox, actualizable trimestralmente)
    base_seguro = min(sueldo_computable, parametros['tope_seguro_afp'])
    prima_seguro = base_seguro * tasa_afp['prima']
    
    # Comisión
    tasa_comision = tasa_afp['flujo'] if trabajador.tipo_comision_afp == 'FLUJO' else tasa_afp['mixta']
    comision = sueldo_computable * tasa_comision
    
    retencion_total = aporte_obligatorio + prima_seguro + comision

    return {
        'tipo': 'AFP',
        'retencion_total': round(retencion_total, 2),
        'desglose': {
            'aporte': round(aporte_obligatorio, 2),
            'comision': round(comision, 2),
            'prima': round(prima_seguro, 2)
        }
    }

def calcular_essalud(sueldo_computable: float, trabajador, rmv: float) -> float:
    """ Calcula el aporte del empleador a EsSalud validando el mínimo vital y EPS """
    # La base imponible para EsSalud nunca puede ser menor a la RMV
    base_imponible = max(sueldo_computable, rmv)
    porcentaje = 0.0675 if trabajador.tiene_eps else 0.09
    return round(base_imponible * porcentaje, 2)