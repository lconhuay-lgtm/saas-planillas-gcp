"""
infrastructure/repositories/repo_planilla.py

Repositorio de acceso a datos para el módulo de Planilla Mensual.
Centraliza todas las operaciones de lectura/escritura contra la BD
de las entidades: ParametroLegal, Trabajador, VariablesMes, Concepto, PlanillaMensual.
"""
import json
import io
import pandas as pd
from datetime import datetime
from sqlalchemy import or_
from infrastructure.database.models import (
    Trabajador, Concepto, ParametroLegal, VariablesMes, PlanillaMensual,
)


def cargar_parametros(db, empresa_id, periodo_key) -> dict | None:
    """Lee los ParametroLegal de Neon y los devuelve como dict con claves compatibles."""
    p_db = db.query(ParametroLegal).filter_by(
        empresa_id=empresa_id, periodo_key=periodo_key
    ).first()
    if not p_db:
        return None
    return {
        'rmv': p_db.rmv, 'uit': p_db.uit,
        'tasa_onp': p_db.tasa_onp, 'tasa_essalud': p_db.tasa_essalud,
        'tasa_eps': p_db.tasa_eps, 'tope_afp': p_db.tope_afp,
        'afp_habitat_aporte': p_db.h_ap, 'afp_habitat_prima': p_db.h_pr,
        'afp_habitat_flujo': p_db.h_fl, 'afp_habitat_mixta': p_db.h_mx,
        'afp_integra_aporte': p_db.i_ap, 'afp_integra_prima': p_db.i_pr,
        'afp_integra_flujo': p_db.i_fl, 'afp_integra_mixta': p_db.i_mx,
        'afp_prima_aporte': p_db.p_ap, 'afp_prima_prima': p_db.p_pr,
        'afp_prima_flujo': p_db.p_fl, 'afp_prima_mixta': p_db.p_mx,
        'afp_profuturo_aporte': p_db.pr_ap, 'afp_profuturo_prima': p_db.pr_pr,
        'afp_profuturo_flujo': p_db.pr_fl, 'afp_profuturo_mixta': p_db.pr_mx,
        'tasa_4ta': getattr(p_db, 'tasa_4ta', 8.0) or 8.0,
        'tope_4ta': getattr(p_db, 'tope_4ta', 1500.0) or 1500.0,
        'edad_maxima_prima_afp': getattr(p_db, 'edad_maxima_prima_afp', 65) or 65,
    }


def cargar_trabajadores_df(db, empresa_id, mes_calc: int = 0, anio_calc: int = 0) -> pd.DataFrame:
    """Lee trabajadores activos de Neon y los devuelve como DataFrame compatible.
    Si se pasan mes_calc/anio_calc, incluye también trabajadores cesados cuya
    fecha_cese caiga en ese período (para calcular su último mes proporcional).
    """
    import calendar as _cal
    from datetime import date as _date
    from sqlalchemy import and_

    tipo_planilla = or_(
        Trabajador.tipo_contrato == 'PLANILLA',
        Trabajador.tipo_contrato == None,
        Trabajador.tipo_contrato == ''
    )

    if mes_calc and anio_calc:
        primer_dia = _date(anio_calc, mes_calc, 1)
        ultimo_dia = _date(anio_calc, mes_calc, _cal.monthrange(anio_calc, mes_calc)[1])
        trabajadores = (
            db.query(Trabajador)
            .filter(
                Trabajador.empresa_id == empresa_id,
                tipo_planilla,
                or_(
                    Trabajador.situacion == "ACTIVO",
                    and_(
                        Trabajador.situacion == "CESADO",
                        Trabajador.fecha_cese >= primer_dia,
                        Trabajador.fecha_cese <= ultimo_dia,
                    )
                )
            )
            .all()
        )
    else:
        trabajadores = (
            db.query(Trabajador)
            .filter(
                Trabajador.empresa_id == empresa_id,
                Trabajador.situacion == "ACTIVO",
                tipo_planilla,
            )
            .all()
        )

    rows = []
    for t in trabajadores:
        rows.append({
            "Num. Doc.": t.num_doc,
            "Nombres y Apellidos": t.nombres,
            "Fecha Ingreso": t.fecha_ingreso,
            "Fecha Cese": getattr(t, 'fecha_cese', None),
            "Fecha Nacimiento": t.fecha_nac,
            "Sueldo Base": t.sueldo_base,
            "Sistema Pensión": t.sistema_pension or "NO AFECTO",
            "Comisión AFP": t.comision_afp or "FLUJO",
            "Asig. Fam.": "Sí" if t.asig_fam else "No",
            "EPS": "Sí" if t.eps else "No",
            "CUSPP": t.cuspp or "",
            "Cargo": t.cargo or "",
            "Seguro Social": getattr(t, 'seguro_social', None) or "ESSALUD",
            "Banco": t.banco or "",
            "Cuenta Bancaria": t.cuenta_bancaria or "",
            "CCI": t.cci or "",
        })
    return pd.DataFrame(rows)


def cargar_variables_df(db, empresa_id, periodo_key, conceptos) -> pd.DataFrame:
    """Lee VariablesMes de Neon y los devuelve como DataFrame compatible."""
    variables = (
        db.query(VariablesMes)
        .filter_by(empresa_id=empresa_id, periodo_key=periodo_key)
        .all()
    )
    concepto_nombres = [c.nombre for c in conceptos]
    rows = []
    for v in variables:
        susp = json.loads(getattr(v, 'suspensiones_json', '{}') or '{}')
        # Total de ausencias desde suspensiones_json; fallback a dias_faltados
        total_ausencias = sum(susp.values()) if susp else (v.dias_faltados or 0)
        row = {
            "Num. Doc.": v.trabajador.num_doc,
            "Nombres y Apellidos": v.trabajador.nombres,
            "Días Faltados": total_ausencias,
            "suspensiones_json": json.dumps(susp),
            "Min. Tardanza": v.min_tardanza or 0,
            "Hrs Extras 25%": v.hrs_extras_25 or 0.0,
            "Hrs Extras 35%": v.hrs_extras_35 or 0.0,
        }
        conceptos_data = json.loads(v.conceptos_json or '{}')
        for nombre in concepto_nombres:
            row[nombre] = conceptos_data.get(nombre, 0.0)
        # Preservar el JSON completo para que el motor de cálculo pueda leer
        # los ajustes de auditoría (_ajuste_afp, _ajuste_quinta, _ajuste_otros)
        row["conceptos_json"] = v.conceptos_json or '{}'
        rows.append(row)
    df = pd.DataFrame(rows)
    # fillna solo en columnas numéricas para no borrar el JSON de ajustes
    cols_num = [c for c in df.columns if c != "conceptos_json"]
    df[cols_num] = df[cols_num].fillna(0.0)
    return df


def cargar_conceptos_df(db, empresa_id) -> pd.DataFrame:
    """Lee conceptos de la empresa de Neon como DataFrame compatible con el motor."""
    conceptos = db.query(Concepto).filter_by(empresa_id=empresa_id).all()
    rows = []
    for c in conceptos:
        rows.append({
            "Empresa_ID": empresa_id,
            "Nombre del Concepto": c.nombre,
            "Tipo": c.tipo,
            "Afecto AFP/ONP": c.afecto_afp,
            "Afecto 5ta Cat.": c.afecto_5ta,
            "Afecto EsSalud": c.afecto_essalud,
            "Computable CTS": c.computable_cts,
            "Computable Grati": c.computable_grati,
            "Prorrateable": getattr(c, 'prorrateable_por_asistencia', False),
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def guardar_planilla(db, empresa_id, periodo_key, df_resultados, auditoria_data, df_locadores=None):
    """Guarda (upsert) el resultado de planilla en la tabla PlanillaMensual de Neon."""
    resultado_json = df_resultados.to_json(orient='records', date_format='iso')
    auditoria_json = json.dumps(auditoria_data, default=str)
    
    hon_json = "[]"
    if df_locadores is not None and not df_locadores.empty:
        hon_json = df_locadores.to_json(orient='records', date_format='iso')

    existente = db.query(PlanillaMensual).filter_by(
        empresa_id=empresa_id, periodo_key=periodo_key
    ).first()
    if existente:
        existente.resultado_json = resultado_json
        existente.auditoria_json = auditoria_json
        # Solo sobreescribe si se envía un df válido, si no, respeta lo que ya estaba
        if df_locadores is not None:
            existente.honorarios_json = hon_json
        existente.fecha_calculo = datetime.now()
    else:
        nueva = PlanillaMensual(
            empresa_id=empresa_id,
            periodo_key=periodo_key,
            resultado_json=resultado_json,
            auditoria_json=auditoria_json,
            honorarios_json=hon_json
        )
        db.add(nueva)
    db.commit()


def cargar_planilla_guardada(db, empresa_id, periodo_key):
    """Recupera una planilla previamente guardada de Neon. Retorna (df, auditoria) o (None, None)."""
    p = db.query(PlanillaMensual).filter_by(
        empresa_id=empresa_id, periodo_key=periodo_key
    ).first()
    if not p:
        return None, None
    df = pd.read_json(io.StringIO(p.resultado_json), orient='records')
    auditoria = json.loads(p.auditoria_json)
    return df, auditoria

