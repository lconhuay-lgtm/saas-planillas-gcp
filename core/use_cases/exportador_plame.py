import io
import zipfile
import json
import pandas as pd
from sqlalchemy.orm import Session
from infrastructure.database.models import Empresa, Trabajador, VariablesMes, PlanillaMensual, Concepto

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
    Lee el snapshot de la planilla, aplica regla de devengados 0.00 para series 06 y 07,
    e inyecta obligatoriamente 0605 y 0601 si están ausentes.
    """
    planilla = db.query(PlanillaMensual).filter_by(
        empresa_id=empresa_id, periodo_key=periodo_key
    ).first()
    
    if not planilla:
        return ""
        
    auditoria = json.loads(planilla.auditoria_json or '{}')
    lineas = []
    
    # 1. Diccionarios de Mapeo
    conceptos_bd = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
    cod_map = {c.nombre.strip().upper(): c.codigo_sunat for c in conceptos_bd if c.codigo_sunat}
    
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
        "PRESTAMO PERSONAL": "0706",
        "ADELANTO DE SUELDO": "0701"
    }
    
    # 2. Iteración sobre trabajadores del snapshot
    for dni_original, data in auditoria.items():
        dni_limpio = "".join(str(dni_original).split())
        t = db.query(Trabajador).filter_by(num_doc=dni_limpio, empresa_id=empresa_id).first()
        
        if t and getattr(t, 'tipo_contrato', 'PLANILLA') == 'LOCADOR':
            continue
            
        tipo_doc = getattr(t, 'tipo_documento', '01') if t else '01'
        if len(dni_limpio) > 8 and tipo_doc == '01':
            tipo_doc = '04'
        
        # 3. Consolidación de ingresos y descuentos (Unificación de nodos del JSON)
        rubros_a_exportar = []
        if 'ingresos' in data:
            rubros_a_exportar.extend(data['ingresos'].items())
        if 'descuentos' in data:
            rubros_a_exportar.extend(data['descuentos'].items())
            
        # EXTRAER PENSIONES (AFP/ONP) DESDE EL NODO ESPECÍFICO DEL JSON
        pensiones = data.get('detalle_pensiones', {})
        if pensiones:
            tipo_pen = pensiones.get('tipo', '')
            desglose = pensiones.get('desglose', {})
            if tipo_pen == 'AFP':
                if 'aporte' in desglose:
                    rubros_a_exportar.append(("AFP - APORTE OBLIGATORIO", desglose['aporte']))
                if 'comision' in desglose:
                    rubros_a_exportar.append(("AFP - COMISIÓN", desglose['comision']))
                if 'prima' in desglose:
                    rubros_a_exportar.append(("AFP - PRIMA DE SEGURO", desglose['prima']))
            elif tipo_pen == 'ONP':
                if 'aporte' in desglose:
                    rubros_a_exportar.append(("ONP - APORTE", desglose['aporte']))
                    
        # EXTRAER QUINTA CATEGORÍA DESDE SU NODO ESPECÍFICO (COMPATIBILIDAD HISTÓRICA)
        monto_q = 0
        if 'quinta' in data and isinstance(data['quinta'], dict):
            monto_q = data['quinta'].get('retencion', 0)
        elif 'retencion_5ta' in data:
            monto_q = data['retencion_5ta']
            
        if float(monto_q) > 0:
            rubros_a_exportar.append(("RENTA 5TA CATEGORÍA", monto_q))
                
        # Rastreador de códigos procesados para inyecciones obligatorias
        codigos_procesados = set()
            
        for nombre_concepto, monto in rubros_a_exportar:
            nombre_limpio = str(nombre_concepto).strip().upper()

            try:
                monto_float = float(monto)
            except ValueError:
                continue
            
            # Asignación de código SUNAT
            cod_sunat = None
            if nombre_limpio.startswith("SUELDO BASE") or "SUELDO BASICO" in nombre_limpio:
                cod_sunat = "0121"
            else:
                cod_sunat = cod_map.get(nombre_limpio) or fallback_map.get(nombre_limpio)
            
            # PLAME autocalcula ONP, se omite de la exportación
            if cod_sunat == "0607":
                continue
            
            if cod_sunat:
                cod_str = str(cod_sunat).strip()
                
                # Ignorar montos <= 0 EXCEPTO para 0601 y 0605 que PLAME exige reportar obligatoriamente
                if monto_float <= 0 and cod_str not in ["0601", "0605"]:
                    continue
                    
                codigos_procesados.add(cod_str)
                
                # REGLA ESTRICTA: Series 0600 (Retenciones) y 0700 (Deducciones) llevan devengado 0.00
                if cod_str.startswith("07") or cod_str.startswith("06"):
                    monto_devengado = 0.00
                    monto_pagado = monto_float
                else:
                    # Ingresos (Serie 100-500)
                    monto_devengado = monto_float
                    monto_pagado = monto_float
                    
                lineas.append(f"{tipo_doc}|{dni_limpio}|{cod_str}|{monto_devengado:.2f}|{monto_pagado:.2f}|")
                
        # 4. INYECCIÓN POST-PROCESAMIENTO PARA PLAME
        # Renta de 5ta (0605) es obligatoria para todos
        if "0605" not in codigos_procesados:
            lineas.append(f"{tipo_doc}|{dni_limpio}|0605|0.00|0.00|")
            
        # Comisión AFP (0601) es obligatoria SOLO si el trabajador pertenece al Sistema Privado de Pensiones
        sistema_pension = str(getattr(t, 'sistema_pension', '')).upper() if t else ""
        if "AFP" in sistema_pension and "0601" not in codigos_procesados:
            lineas.append(f"{tipo_doc}|{dni_limpio}|0601|0.00|0.00|")
                
    # Retorno con salto de línea estándar de Windows para lectura correcta en PLAME
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
