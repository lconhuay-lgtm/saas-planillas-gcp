def obtener_factores_regimen(regimen_trabajador):
    """
    Retorna los factores de multiplicación para beneficios sociales.
    """
    if regimen_trabajador == "Régimen General" or "Derechos Adquiridos" in regimen_trabajador:
        return {"grati": 1.0, "cts": 1.0, "vacaciones": 30, "asig_fam": 1.0}
    
    elif regimen_trabajador == "Régimen Especial - Pequeña Empresa":
        return {"grati": 0.5, "cts": 0.5, "vacaciones": 15, "asig_fam": 1.0}
    
    elif regimen_trabajador == "Régimen Especial - Micro Empresa":
        return {"grati": 0.0, "cts": 0.0, "vacaciones": 15, "asig_fam": 0.0}
    
    return {"grati": 1.0, "cts": 1.0, "vacaciones": 30, "asig_fam": 1.0}

def determinar_regimen_trabajador(fecha_ingreso, regimen_empresa, fecha_acogimiento):
    """
    Régimen aplicable al trabajador, protegiendo derechos adquiridos: quien ingresó
    antes de que la empresa se acogiera al régimen MYPE conserva el Régimen General.
    """
    if regimen_empresa == "Régimen General" or not fecha_acogimiento:
        return "Régimen General"
    if fecha_ingreso < fecha_acogimiento:
        return "Régimen General (Derechos Adquiridos)"
    return regimen_empresa
