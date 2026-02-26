# infrastructure/services/sunat_api.py
import requests

def consultar_dni_sunat(dni: str) -> dict:
    """
    Consulta un DNI usando una arquitectura con respaldo (Failover).
    Intenta primero con APIsPERU. Si falla, usa apis.net.pe.
    Retorna un diccionario con 'success' (bool), 'nombres' (str) y 'mensaje' (str).
    """
    if len(dni) != 8 or not dni.isdigit():
        return {"success": False, "nombres": "", "mensaje": "El DNI debe tener 8 dígitos numéricos."}

    # --- INTENTO 1: API PRINCIPAL (APIsPERU) ---
    try:
        # ⚠️ IMPORTANTE: Coloca aquí tu token real de APIsPERU
        TOKEN_APISPERU = "TU_TOKEN_AQUI_REEMPLAZAME" 
        url_principal = f"https://dniruc.apisperu.com/api/v1/dni/{dni}?token={TOKEN_APISPERU}"
        
        response = requests.get(url_principal, headers={'Accept': 'application/json'}, timeout=5)
        
        if response.status_code == 200:
            datos = response.json()
            if datos.get("success") is not False: # APIsPERU devuelve success=False si el token falla
                 nombres_completos = f"{datos.get('nombres', '')} {datos.get('apellidoPaterno', '')} {datos.get('apellidoMaterno', '')}".strip()
                 return {"success": True, "nombres": nombres_completos, "mensaje": "Obtenido desde API Principal"}
    except Exception as e:
        pass # Silenciamos el error para intentar con el respaldo

    # --- INTENTO 2: API DE RESPALDO (apis.net.pe) ---
    try:
        url_respaldo = f"https://api.apis.net.pe/v1/dni?numero={dni}"
        response = requests.get(url_respaldo, timeout=5)
        
        if response.status_code == 200:
            datos = response.json()
            nombres_completos = f"{datos.get('nombres', '')} {datos.get('apellidoPaterno', '')} {datos.get('apellidoMaterno', '')}".strip()
            return {"success": True, "nombres": nombres_completos, "mensaje": "Obtenido desde API de Respaldo"}
        elif response.status_code == 404:
            return {"success": False, "nombres": "", "mensaje": "DNI no encontrado en bases de datos."}
            
    except Exception as e:
        return {"success": False, "nombres": "", "mensaje": f"Fallo de conexión en ambas APIs: {e}"}

    return {"success": False, "nombres": "", "mensaje": "Error desconocido al consultar el DNI."}