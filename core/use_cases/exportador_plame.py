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
        num_doc_limpio = str(t.num_doc).replace(" ", "").strip()
        
        # Validación de seguridad para CE/DNI
        if len(num_doc_limpio) > 8 and tipo_doc == '01':
            tipo_doc = '04' # Auto-corrección a Carnet de Extranjería si es largo
        lineas.append(f"{tipo_doc}|{num_doc_limpio}|{h_ord}|0|{h_ext}|0|")
        
    return "\n".join(lineas)

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
        num_doc_limpio = str(t.num_doc).replace(" ", "").strip()
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
            
    return "\n".join(txt_e15), "\n".join(txt_e16)

def generar_txt_e18(db: Session, empresa_id: int, periodo_key: str) -> str:
    """Genera archivo .REM (Remuneraciones)"""
    planilla = db.query(PlanillaMensual).filter_by(
        empresa_id=empresa_id, periodo_key=periodo_key
    ).first()
    
    if not planilla:
        return ""
        
    auditoria = json.loads(planilla.auditoria_json or '{}')
    lineas = []
    
    # Cargar mapa de códigos SUNAT de los conceptos de la empresa
    conceptos = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
    cod_map = {c.nombre: c.codigo_sunat for c in conceptos}
    # Conceptos core obligatorios
    cod_map["Asignación Familiar"] = "0201"
    
    for dni, data in auditoria.items():
        # Limpiar DNI de la auditoría por si acaso
        dni_key = str(dni).replace(" ", "").strip()
        t = db.query(Trabajador).filter_by(num_doc=dni, empresa_id=empresa_id).first()
        
        # Omitir locadores si por error aparecen en la auditoría de planilla
        if t and getattr(t, 'tipo_contrato', 'PLANILLA') == 'LOCADOR':
            continue
        tipo_doc = getattr(t, 'tipo_documento', '01') or '01'
        
        ingresos = data.get('ingresos', {})
        for c_nom, monto in ingresos.items():
            cod_sunat = None
            if c_nom.startswith("Sueldo Base"):
                cod_sunat = "0121"
            else:
                cod_sunat = cod_map.get(c_nom)
            
            if not cod_sunat:
                raise ValueError(f"El concepto '{c_nom}' no tiene un Código SUNAT asignado. Debe configurarlo en el Maestro de Conceptos antes de exportar.")
            
            lineas.append(f"{tipo_doc}|{dni_key}|{cod_sunat}|{float(monto):.2f}|{float(monto):.2f}|")
                
    return "\n".join(lineas)

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
        
        buf.seek(0)
        return buf
    finally:
        db.close()
