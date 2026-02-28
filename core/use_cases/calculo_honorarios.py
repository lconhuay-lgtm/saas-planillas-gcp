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
    anio_calc: int = 0,
    mes_calc: int = 0,
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
        anio_calc: año del periodo de cálculo (para aplicar Base 30 con fecha_ingreso).
        mes_calc: mes del periodo de cálculo (para aplicar Base 30 con fecha_ingreso).

    Returns:
        dict con el desglose completo del recibo:
            honorario_base, dias_no_prestados, dias_laborados, monto_descuento,
            otros_pagos, pago_bruto, retencion_4ta, otros_descuentos, neto_a_pagar,
            observaciones.
    """
    honorario_base    = float(getattr(locador, 'sueldo_base', 0.0) or 0.0)
    dias_no_prestados = int(variables.get('dias_no_prestados', 0) or 0)
    otros_pagos       = float(variables.get('otros_pagos', 0.0) or 0.0)
    otros_descuentos  = float(variables.get('otros_descuentos', 0.0) or 0.0)

    # ── Mes Comercial Mixto (Base 30) con fecha_ingreso ─────────────────────
    fecha_ingreso_loc = getattr(locador, 'fecha_ingreso', None)
    ingreso_este_mes  = False
    dias_vinculados   = 30  # base 30: mes completo por defecto

    if fecha_ingreso_loc and anio_calc and mes_calc:
        try:
            fi = fecha_ingreso_loc  # datetime.date desde SQLAlchemy
            ingreso_este_mes = (fi.year == anio_calc and fi.month == mes_calc)
            if ingreso_este_mes:
                # Días desde la fecha de ingreso hasta fin del mes (sobre el calendario real)
                dias_vinculados = dias_del_mes - fi.day + 1
        except Exception:
            pass

    dias_efectivos = max(0, dias_vinculados - dias_no_prestados)

    # Descuento proporcional — Base 30 (Mes Comercial Mixto)
    monto_descuento = 0.0
    if dias_no_prestados == 0 and (not ingreso_este_mes or dias_vinculados >= dias_del_mes):
        # Trabajó todos los días disponibles (incluye ingreso día 1) → honorario íntegro
        pass
    else:
        valor_dia = honorario_base / 30.0
        monto_descuento = max(0.0, honorario_base - (valor_dia * dias_efectivos))

    pago_bruto = max(0.0, honorario_base - monto_descuento + otros_pagos)

    # Retención 8% solo si pago_bruto supera el tope legal
    # Si el locador tiene constancia de suspensión SUNAT, la retención es 0
    tiene_suspension = bool(getattr(locador, 'tiene_suspension_4ta', False) or False)
    if tiene_suspension:
        retencion_4ta = 0.0
    else:
        retencion_4ta = round(pago_bruto * (tasa_4ta / 100.0), 2) if pago_bruto > tope_4ta else 0.0

    neto_a_pagar = pago_bruto - retencion_4ta - otros_descuentos

    obs_loc = []
    if ingreso_este_mes and fecha_ingreso_loc:
        try:
            obs_loc.append(f"Ingresó a laborar el {fecha_ingreso_loc.strftime('%d/%m/%Y')}")
        except Exception:
            pass
    if dias_no_prestados > 0:
        obs_loc.append(f"No prestó servicios {dias_no_prestados} día(s)")
    if tiene_suspension:
        obs_loc.append("Constancia de suspensión SUNAT activa")

    return {
        'honorario_base':       round(honorario_base, 2),
        'dias_no_prestados':    dias_no_prestados,
        'dias_laborados':       dias_efectivos,
        'monto_descuento':      round(monto_descuento, 2),
        'otros_pagos':          round(otros_pagos, 2),
        'pago_bruto':           round(pago_bruto, 2),
        'retencion_4ta':        retencion_4ta,
        'otros_descuentos':     round(otros_descuentos, 2),
        'neto_a_pagar':         round(neto_a_pagar, 2),
        'tiene_suspension_4ta': tiene_suspension,
        'observaciones':        " | ".join(obs_loc),
    }
