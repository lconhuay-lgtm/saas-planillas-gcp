"""
Motor de cálculo para Locadores de Servicio (Renta de 4ta Categoría).

Por mandato del principio de "Primacía de la Realidad", los locadores NO
tienen vínculo laboral con la empresa. Por lo tanto:
  - No aplica AFP / ONP / EsSalud.
  - No aplica beneficios sociales (gratificaciones, CTS, asignación familiar).
  - No aplica horas extras ni tardanzas.
  - Solo se aplica Retención del 8% si el pago bruto supera el tope legal.
"""


def calcular_recibo_honorarios(
    locador,
    variables: dict,
    dias_del_mes: int,
    tasa_4ta: float = 8.0,
    tope_4ta: float = 1500.0,
) -> dict:
    """
    Calcula el recibo por honorarios de un locador (4ta categoría).

    Args:
        locador: objeto Trabajador con campo ``sueldo_base`` (honorario mensual pactado).
        variables: dict con las claves:
            - ``dias_no_prestados`` (int): días sin prestar servicios a descontar.
            - ``otros_pagos`` (float): bonos u otros pagos adicionales.
            - ``otros_descuentos`` (float): penalidades u otros descuentos.
        dias_del_mes: número real de días del mes de cálculo (28, 30 ó 31).
        tasa_4ta: porcentaje de retención (por defecto 8 %).
        tope_4ta: monto mínimo de pago bruto para aplicar retención (por defecto S/ 1 500).

    Returns:
        dict con el desglose completo del recibo:
            honorario_base, dias_no_prestados, monto_descuento,
            otros_pagos, pago_bruto, retencion_4ta, otros_descuentos, neto_a_pagar.
    """
    honorario_base    = float(getattr(locador, 'sueldo_base', 0.0) or 0.0)
    dias_no_prestados = int(variables.get('dias_no_prestados', 0) or 0)
    otros_pagos       = float(variables.get('otros_pagos', 0.0) or 0.0)
    otros_descuentos  = float(variables.get('otros_descuentos', 0.0) or 0.0)

    # Descuento proporcional por días no prestados
    monto_descuento = 0.0
    if dias_del_mes > 0 and dias_no_prestados > 0:
        monto_descuento = (honorario_base / dias_del_mes) * dias_no_prestados

    pago_bruto = max(0.0, honorario_base - monto_descuento + otros_pagos)

    # Retención 8% solo si pago_bruto supera el tope legal
    retencion_4ta = round(pago_bruto * (tasa_4ta / 100.0), 2) if pago_bruto > tope_4ta else 0.0

    neto_a_pagar = pago_bruto - retencion_4ta - otros_descuentos

    return {
        'honorario_base':    round(honorario_base, 2),
        'dias_no_prestados': dias_no_prestados,
        'monto_descuento':   round(monto_descuento, 2),
        'otros_pagos':       round(otros_pagos, 2),
        'pago_bruto':        round(pago_bruto, 2),
        'retencion_4ta':     retencion_4ta,
        'otros_descuentos':  round(otros_descuentos, 2),
        'neto_a_pagar':      round(neto_a_pagar, 2),
    }
