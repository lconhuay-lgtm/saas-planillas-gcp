import io
import zipfile
import json
import pandas as pd
from sqlalchemy.orm import Session
from infrastructure.database.models import Empresa, Trabajador, VariablesMes, PlanillaMensual, Concepto, ParametroLegal

def generar_txt_e14(db: Session, empresa_id: int, mes: int, anio: int) -> str:
    """Genera archivo .JOR (Jornada Laboral)"""
    periodo_key = f"{str(mes).zfill(2)}-{anio}"
    empresa = db.query(Empresa).filter_by(id=empresa_id).first()
    horas_base_diaria = getattr(empresa, 'horas_jornada_diaria', 8.0) or 8.0
    
    # Filtrar solo trabajadores de PLANILLA (No Locadores)
    trabajadores = db.query(Trabajador).filter_by(
        empresa_id=empresa_id, 
        situacion='ACTIVO',
        tipo_contrato='PLANILLA'
    ).all()
    lineas = []
    
    for t in trabajadores:
        # Intentar obtener horas reales de VariablesMes
        v = db.query(VariablesMes).filter_by(trabajador_id=t.id, periodo_key=periodo_key).first()
        
        # Lógica: Si no hay variables guardadas, se asumen 30 días laborados comerciales
        # Si hay variables, se calcula en base a inasistencias
        h_ord = 240
        if v:
            susp = json.loads(v.suspensiones_json or '{}')
            faltas = sum(susp.values()) if isinstance(susp, dict) else 0
            dias_reales = max(0, 30 - faltas)
            h_ord = int(dias_reales * horas_base_diaria)
            h_ext = int((v.hrs_extras_25 or 0) + (v.hrs_extras_35 or 0))
        else:
            h_ord = int(30 * horas_base_diaria)
            h_ext = 0
            
        tipo_doc = getattr(t, 'tipo_documento', '01') or '01'
        # Limpieza de seguridad: eliminar espacios que puedan existir en la BD
        num_doc_limpio = "".join(str(t.num_doc).split())
        
        # Validación de seguridad para CE/DNI
        if len(num_doc_limpio) > 8 and tipo_doc == '01':
            tipo_doc = '04' # Auto-corrección a Carnet de Extranjería si es largo
        lineas.append(f"{tipo_doc}|{num_doc_limpio}|{h_ord}|0|{h_ext}|0|")
        
    return "\r\n".join(lineas)

def generar_txt_e15_e16(db: Session, empresa_id: int, periodo_key: str):
    """Genera archivos .SUB y .NOT (Suspensiones)"""
    variables = db.query(VariablesMes).join(Trabajador).filter(
        VariablesMes.empresa_id == empresa_id,
        VariablesMes.periodo_key == periodo_key
    ).all()
    
    txt_e15 = [] # .SUB (Subsidios/E15)
    txt_e16 = [] # .NOT (Otras suspensiones/E16)
    
    for v in variables:
        t = v.trabajador
        tipo_doc = getattr(t, 'tipo_documento', '01') or '01'
        num_doc_limpio = "".join(str(t.num_doc).split())
        try:
            susp_list = json.loads(v.suspensiones_json or '{}')
            # Si el JSON es un dict simple de código:días (estándar actual de la app)
            if isinstance(susp_list, dict):
                for cod, dias in susp_list.items():
                    if int(dias) > 0:
                        # Clasificación según catálogo SUNAT
                        # E15: 01, 02, 03, 04, 21, 22
                        if cod in ['01', '02', '03', '04', '21', '22']:
                            txt_e15.append(f"{tipo_doc}|{num_doc_limpio}|{cod}|0|{dias}|")
                        else:
                            txt_e16.append(f"{tipo_doc}|{num_doc_limpio}|{cod}|{dias}|")
        except:
            continue
            
    return "\r\n".join(txt_e15), "\r\n".join(txt_e16)

def generar_txt_e18(db: Session, empresa_id: int, periodo_key: str) -> str:
    """
    Genera el archivo .REM (Remuneraciones, Tributos y Descuentos).
    Aplica directrices de PLAME y mapeo retroactivo de códigos SUNAT 100% en memoria.
    """
    # 1. Consulta de solo lectura del histórico inmutable de la planilla
    planilla = db.query(PlanillaMensual).filter_by(
        empresa_id=empresa_id, periodo_key=periodo_key
    ).first()
    
    if not planilla:
        return ""

    # Cargar parámetros legales del periodo para reconstrucción de seguros en planillas antiguas
    param = db.query(ParametroLegal).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first()
    
    # Carga del JSON en memoria. No se altera la base de datos bajo ninguna circunstancia.
    auditoria = json.loads(planilla.auditoria_json or '{}')
    lineas = []
    
    # 2. Creación del Diccionario Traductor Dinámico (Base de datos actual)
    conceptos_bd = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
    # Normalizamos a mayúsculas y sin espacios a los extremos para cruce exacto
    cod_map = {c.nombre.strip().upper(): c.codigo_sunat for c in conceptos_bd if c.codigo_sunat}
    
    # 3. Diccionario Fallback de Rescate (Para planillas históricas o conceptos del motor base)
    fallback_map = {
        "SUELDO BASE": "0121",
        "ASIGNACIÓN FAMILIAR": "0201",
        "ASIGNACION FAMILIAR": "0201",
        "AFP - APORTE OBLIGATORIO": "0608",
        "AFP APORTE OBLIGATORIO": "0608",
        "AFP - COMISIÓN": "0601",
        "AFP COMISION": "0601",
        "AFP - PRIMA DE SEGURO": "0606",
        "AFP PRIMA DE SEGURO": "0606",
        "ONP - APORTE": "0607",
        "ONP APORTE": "0607",
        "RENTA 5TA CATEGORÍA": "0605",
        "RENTA 5TA CATEGORIA": "0605",
        "TARDANZAS": "0704",
        "PRÉSTAMO PERSONAL": "0706",
        "ADELANTO DE SUELDO": "0701"
    }
    
    # 4. Iteración sobre cada trabajador en la planilla cerrada
    for dni_original, data in auditoria.items():
        # Limpieza AGRESIVA del DNI en memoria (reemplaza cualquier espacio, no solo extremos)
        dni_limpio = "".join(str(dni_original).split())
        
        # Búsqueda segura del trabajador usando el DNI sanitizado temporalmente
        t = db.query(Trabajador).filter_by(num_doc=dni_limpio, empresa_id=empresa_id).first()
        
        # Se excluyen los locadores (Cuarta categoría se declara en otro archivo)
        if t and getattr(t, 'tipo_contrato', 'PLANILLA') == 'LOCADOR':
            continue
            
        tipo_doc = getattr(t, 'tipo_documento', '01') if t else '01'
        # Auto-corrección robusta para CE (04) si el DNI es largo y estaba como '01'
        if len(dni_limpio) > 8 and tipo_doc == '01':
            tipo_doc = '04'
        
        # 5. Consolidación de ingresos y descuentos en una sola lista iterativa
        # Usamos un diccionario temporal para evitar duplicidad si el usuario creó el concepto manualmente
        consolidado_conceptos = {}
        
        if 'ingresos' in data:
            for n, m in data['ingresos'].items():
                consolidado_conceptos[n.strip().upper()] = m
        
        if 'descuentos' in data:
            for n, m in data['descuentos'].items():
                nombre_d = n.strip().upper()
                monto_d = float(m)
                
                # RECONSTRUCCIÓN DINÁMICA DE SEGURO PARA PLANILLAS ANTIGUAS
                # Si el nombre empieza con "APORTE AFP" y no es un desglose ya existente
                if nombre_d.startswith("APORTE AFP") and "OBLIGATORIO" not in nombre_d and param:
                    sistema = nombre_d.replace("APORTE ", "") # "AFP INTEGRA"
                    prefijo = ""
                    if "HABITAT" in sistema: prefijo = "h_"
                    elif "INTEGRA" in sistema: prefijo = "i_"
                    elif "PRIMA" in sistema: prefijo = "p_"
                    elif "PROFUTURO" in sistema: prefijo = "pr_"
                    
                    if prefijo:
                        t_ap = getattr(param, prefijo + "ap", 10.0) / 100
                        t_pr = getattr(param, prefijo + "pr", 1.84) / 100
                        t_fl = getattr(param, prefijo + "fl", 1.55) / 100
                        t_mx = getattr(param, prefijo + "mx", 0.0) / 100
                        
                        # Determinar si el trabajador usaba mixta o flujo (desde el snapshot si es posible)
                        t_com = t_mx if data.get('comision_afp') == "MIXTA" else t_fl
                        t_total_afp = t_ap + t_pr + t_com
                        
                        # Desglosar proporcionalmente basado en la base imponible guardada
                        base_imponible = float(data.get('base_afp', 0) or (monto_d / t_total_afp if t_total_afp > 0 else 0))
                        if base_imponible > 0:
                            m_ap = round(base_imponible * t_ap, 2)
                            m_pr = round(min(base_imponible, param.tope_afp or 999999) * t_pr, 2)
                            m_co = round(monto_d - m_ap - m_pr, 2)
                            
                            consolidado_conceptos[f"APORTE OBLIGATORIO {sistema}"] = m_ap
                            consolidado_conceptos[f"PRIMA DE SEGURO {sistema}"] = m_pr
                            consolidado_conceptos[f"COMISIÓN {sistema}"] = m_co
                            continue # Evitar agregar el consolidado original
                
                consolidado_conceptos[nombre_d] = monto_d
        
        # Rescate de Quinta Categoría desde su propia llave del motor (Snapshot)
        if 'quinta' in data and isinstance(data['quinta'], dict):
            monto_q = data['quinta'].get('retencion', 0)
            if monto_q > 0:
                consolidado_conceptos["RENTA 5TA CATEGORÍA"] = monto_q

        rubros_a_exportar = list(consolidado_conceptos.items())
            
        # 6. Procesamiento y aplicación de reglas matemáticas SUNAT
        for nombre_concepto, monto in rubros_a_exportar:
            try:
                monto_float = float(monto)
            except ValueError:
                continue
                
            # Evitar enviar montos nulos o negativos a PLAME
            if monto_float <= 0:
                continue
                
            # Normalización del nombre del concepto para cruzarlo con los diccionarios
            nombre_limpio = nombre_concepto.strip().upper()
            
            # Determinación del código SUNAT: Prioridad absoluta a mapeo de sistema para conceptos core
            cod_sunat = None
            if nombre_limpio.startswith("SUELDO BASE") or "SUELDO BASICO" in nombre_limpio:
                cod_sunat = "0121"
            elif "APORTE" in nombre_limpio:
                # NOTA: 0607 (ONP) se excluye ya que PLAME lo autocalcula
                cod_sunat = "0608" if "AFP" in nombre_limpio else None
            elif "COMISIÓN" in nombre_limpio or "COMISION" in nombre_limpio:
                cod_sunat = "0601"
            elif "PRIMA" in nombre_limpio or "AFP SEGURO" in nombre_limpio or "SEGURO" in nombre_limpio:
                cod_sunat = "0606"
            elif "RENTA 5TA" in nombre_limpio or "RENTA DE QUINTA" in nombre_limpio or "RETENCION 5TA" in nombre_limpio:
                cod_sunat = "0605"
            elif "PRÉSTAMO" in nombre_limpio or "PRESTAMO" in nombre_limpio or "PREST." in nombre_limpio:
                cod_sunat = "0706" # Otros descuentos no deducibles
            else:
                # Si no es un concepto core del motor, buscar en el Maestro de Conceptos configurado por el usuario
                cod_sunat = cod_map.get(nombre_limpio) or fallback_map.get(nombre_limpio)
            
            # Impedir la exportación si el concepto no está mapeado (excepto ONP que se ignora a propósito)
            if not cod_sunat:
                if "ONP" in nombre_limpio:
                    continue
                raise ValueError(
                    f"Error de Integridad PLAME: El concepto '{nombre_concepto}' no tiene un código SUNAT "
                    f"asignado. Por favor, vincúlelo en el Maestro de Conceptos antes de volver a intentar la exportación."
                )
            
            # Formateo condicional según el código SUNAT resuelto
            if cod_sunat:
                cod_str = str(cod_sunat).strip()
                
                # Regla Estricta PLAME: Si el código pertenece a la serie 700 (Deducciones/Adelantos)
                # o a la serie 600 de RETENCIONES (Pensiones/5ta), el devengado DEBE ser 0.00 para no inflar bases.
                if cod_str.startswith("07") or cod_str.startswith("06"):
                    monto_devengado = 0.00
                    monto_pagado = monto_float
                else:
                    # Para ingresos (series 01, 02, 03, 04, 05, 09) se envían ambos montos
                    monto_devengado = monto_float
                    monto_pagado = monto_float
                    
                # Ensamblado del string final con terminación CRLF
                lineas.append(f"{tipo_doc}|{dni_limpio}|{cod_str}|{monto_devengado:.2f}|{monto_pagado:.2f}|")
                
    return "\r\n".join(lineas)

def generar_zip_plame(empresa_id: int, mes: int, anio: int) -> io.BytesIO:
    """Orquestador principal de PLAME"""
    from infrastructure.database.connection import SessionLocal
    db = SessionLocal()
    try:
        empresa = db.query(Empresa).filter_by(id=empresa_id).first()
        ruc = empresa.ruc
        periodo_key = f"{str(mes).zfill(2)}-{anio}"
        prefijo = f"0601{anio}{str(mes).zfill(2)}{ruc}"
        
        txt_jor = generar_txt_e14(db, empresa_id, mes, anio)
        txt_sub, txt_not = generar_txt_e15_e16(db, empresa_id, periodo_key)
        txt_rem = generar_txt_e18(db, empresa_id, periodo_key)
        
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{prefijo}.jor", txt_jor)
            zf.writestr(f"{prefijo}.sub", txt_sub)
            zf.writestr(f"{prefijo}.not", txt_not)
            zf.writestr(f"{prefijo}.rem", txt_rem)
            # El archivo de suspensiones/días subsidiados para el PDT PLAME suele usar la extensión .snl
            # Consolidamos txt_sub y txt_not si el validador lo requiere en un solo archivo .snl
            txt_snl = ""
            if txt_sub: txt_snl += txt_sub
            if txt_not: 
                if txt_snl: txt_snl += "\r\n"
                txt_snl += txt_not
            if txt_snl:
                zf.writestr(f"{prefijo}.snl", txt_snl)
        
        buf.seek(0)
        return buf
    finally:
        db.close()
