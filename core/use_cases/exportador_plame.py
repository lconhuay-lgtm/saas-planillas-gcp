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
    """Genera archivo .REM con asignación directa y tríada de AFP obligatoria en cero."""
    planilla = db.query(PlanillaMensual).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first()
    if not planilla: return ""
        
    auditoria = json.loads(planilla.auditoria_json or '{}')
    lineas = []
    
    conceptos_bd = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
    cod_map = {c.nombre.strip().upper(): c.codigo_sunat for c in conceptos_bd if c.codigo_sunat}
    
    # El código de gratificación depende del mes: Julio=0301, Diciembre=0302
    _mes_plame = int(periodo_key[:2])
    _cod_grati = "0301" if _mes_plame == 7 else ("0302" if _mes_plame == 12 else None)

    fallback_map = {
        "SUELDO BASE": "0121", "SUELDO BASICO": "0121",
        "ASIGNACIÓN FAMILIAR": "0201", "ASIGNACION FAMILIAR": "0201",
        "TARDANZAS": "0704", "PRÉSTAMO PERSONAL": "0706", "PRESTAMO PERSONAL": "0706",
        "ADELANTO DE SUELDO": "0701",
        # Gratificaciones (Ley 27735) — código según mes de pago
        "GRATIFICACIÓN": _cod_grati, "GRATIFICACION": _cod_grati,
        "GRATIFICACION (JUL/DIC)": _cod_grati,
        # Bono Extraordinario 9% (Ley 29351)
        "BONO EXT. 9%": "0303", "BONO EXTRAORDINARIO 9%": "0303",
        "BONIFICACION EXT. 9% GRATI": "0303",
        "BONIFICACIÓN EXTRAORDINARIA LEY 29351 (9%)": "0303",
        # CTS (D.L. 650) — en meses 05 y 11 se reporta el depósito
        "CTS": "0401", "DEPOSITO CTS": "0401",
        # Gratificación trunca por cese
        "GRATIFICACIÓN TRUNCA": "0305", "GRATIFICACION TRUNCA": "0305",
    }
    
    for dni_original, data in auditoria.items():
        dni_limpio = "".join(str(dni_original).split())
        t = db.query(Trabajador).filter_by(num_doc=dni_limpio, empresa_id=empresa_id).first()
        if t and getattr(t, 'tipo_contrato', 'PLANILLA') == 'LOCADOR': continue
            
        tipo_doc = getattr(t, 'tipo_documento', '01') if t else '01'
        if len(dni_limpio) > 8 and tipo_doc == '01': tipo_doc = '04'
        
        # Estructura: (Nombre, Monto, Codigo_Sunat_Preasignado)
        rubros_a_exportar = []
        
        # 1. Ingresos y Descuentos Normales
        for nombre, monto in data.get('ingresos', {}).items():
            rubros_a_exportar.append((nombre, monto, None))
        for nombre, monto in data.get('descuentos', {}).items():
            rubros_a_exportar.append((nombre, monto, None))
            
        # 2. PENSIONES: Asignación directa del código SUNAT
        pensiones = data.get('detalle_pensiones', {})
        if pensiones:
            tipo_pen = pensiones.get('tipo', '')
            desglose = pensiones.get('desglose', {})
            if tipo_pen == 'AFP':
                if 'aporte' in desglose: rubros_a_exportar.append(("AFP Aporte", desglose['aporte'], "0608"))
                if 'comision' in desglose: rubros_a_exportar.append(("AFP Comision", desglose['comision'], "0601"))
                if 'prima' in desglose: rubros_a_exportar.append(("AFP Seguro", desglose['prima'], "0606"))
            elif tipo_pen == 'ONP':
                if 'aporte' in desglose: rubros_a_exportar.append(("ONP Aporte", desglose['aporte'], "0607"))
                    
        # 3. QUINTA CATEGORÍA: Asignación directa
        monto_q = 0
        if 'quinta' in data and isinstance(data['quinta'], dict):
            monto_q = data['quinta'].get('retencion', 0)
        elif 'retencion_5ta' in data:
            monto_q = data['retencion_5ta']
        if float(monto_q) > 0:
            rubros_a_exportar.append(("Retencion 5ta", monto_q, "0605"))
                
        codigos_procesados = set()
            
        # 4. Procesamiento
        for nombre_concepto, monto, cod_preasignado in rubros_a_exportar:
            try:
                monto_float = float(monto)
            except ValueError: continue
            
            nombre_limpio = str(nombre_concepto).strip().upper()
            
            # Resolver Código
            if cod_preasignado:
                cod_sunat = cod_preasignado
            elif nombre_limpio.startswith("SUELDO BASE"):
                cod_sunat = "0121"
            else:
                cod_sunat = cod_map.get(nombre_limpio) or fallback_map.get(nombre_limpio)
            
            # Omitir ONP obligatoriamente
            if cod_sunat == "0607": continue
            
            if cod_sunat:
                cod_str = str(cod_sunat).strip()
                
                # Ignorar montos 0, EXCEPTO la tríada AFP y la 5ta
                if monto_float <= 0 and cod_str not in ["0601", "0605", "0606", "0608"]:
                    continue
                    
                codigos_procesados.add(cod_str)
                
                # Regla de Devengados (Serie 06 y 07 en cero)
                if cod_str.startswith("07") or cod_str.startswith("06"):
                    monto_devengado = 0.00
                    monto_pagado = monto_float
                else:
                    monto_devengado = monto_float
                    monto_pagado = monto_float
                    
                lineas.append(f"{tipo_doc}|{dni_limpio}|{cod_str}|{monto_devengado:.2f}|{monto_pagado:.2f}|")
                
        # 5. INYECCIONES OBLIGATORIAS FINALES
        # Renta de 5ta (0605) es obligatoria para todos
        if "0605" not in codigos_procesados:
            lineas.append(f"{tipo_doc}|{dni_limpio}|0605|0.00|0.00|")
            
        # Tríada de AFP (0608, 0606, 0601) obligatoria si pertenece al Sistema Privado de Pensiones
        sistema_pension = str(getattr(t, 'sistema_pension', '')).upper() if t else ""
        if "AFP" in sistema_pension:
            for cod_afp in ["0608", "0606", "0601"]:
                if cod_afp not in codigos_procesados:
                    lineas.append(f"{tipo_doc}|{dni_limpio}|{cod_afp}|0.00|0.00|")
                
    # ── CTS: en Mayo (05) y Noviembre (11) agregar líneas de depósito ────────
    if _mes_plame in (5, 11):
        try:
            from infrastructure.database.models import DepositoCTS
            deps_cts = db.query(DepositoCTS).filter_by(
                empresa_id=empresa_id,
                periodo_key_deposito=periodo_key,
            ).all()
            for dep in deps_cts:
                if dep.monto and dep.monto > 0:
                    t_dep = dep.trabajador
                    if not t_dep:
                        continue
                    tipo_doc_dep = getattr(t_dep, 'tipo_documento', '01') or '01'
                    dni_dep = "".join(str(t_dep.num_doc).split())
                    if len(dni_dep) > 8 and tipo_doc_dep == '01':
                        tipo_doc_dep = '04'
                    lineas.append(
                        f"{tipo_doc_dep}|{dni_dep}|0401|{dep.monto:.2f}|{dep.monto:.2f}|"
                    )
        except Exception:
            pass

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
