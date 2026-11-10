"""
infrastructure/repositories/repo_beneficios.py

Lecturas de BD que necesitan los cálculos de CTS (depósito semestral y CTS trunca
de la liquidación por cese). La lógica de cálculo vive en
core/use_cases/calculo_beneficios_sociales.py; aquí solo se arman sus datos.
"""
import json

from infrastructure.database.models import ParametroLegal, VariablesMes, PlanillaMensual, Concepto
from core.use_cases.calculo_beneficios_sociales import clave_periodo


def _json_dict(raw) -> dict:
    try:
        val = json.loads(raw or '{}')
        return val if isinstance(val, dict) else {}
    except (TypeError, ValueError):
        return {}


def cargar_parametro_vigente(db, empresa_id: int, anio: int, mes: int):
    """
    ParametroLegal vigente a un mes dado: el del propio mes o, si no existe, el
    último registrado ANTES de ese mes (orden cronológico real, no alfabético).
    Retorna None si la empresa no tiene ningún parámetro hasta esa fecha.
    """
    objetivo = (int(anio), int(mes))
    candidatos = [
        p for p in db.query(ParametroLegal).filter_by(empresa_id=empresa_id).all()
        if (0, 0) < clave_periodo(p.periodo_key) <= objetivo
    ]
    if not candidatos:
        return None
    return max(candidatos, key=lambda p: (clave_periodo(p.periodo_key), p.id))


def cargar_variables_rango(db, empresa_id: int, periodo_keys: list, trabajador_id=None) -> dict:
    """
    VariablesMes de los periodos indicados, agrupadas por trabajador_id:
    {trabajador_id: [{'periodo_key', 'suspensiones', 'conceptos', 'dias_faltados'}, ...]}
    """
    q = db.query(VariablesMes).filter(
        VariablesMes.empresa_id == empresa_id,
        VariablesMes.periodo_key.in_(list(periodo_keys)),
    )
    if trabajador_id is not None:
        q = q.filter(VariablesMes.trabajador_id == trabajador_id)

    agrupado: dict = {}
    for v in q.all():
        agrupado.setdefault(v.trabajador_id, []).append({
            'periodo_key':   v.periodo_key,
            'suspensiones':  _json_dict(getattr(v, 'suspensiones_json', '{}')),
            'conceptos':     _json_dict(v.conceptos_json),
            'dias_faltados': int(v.dias_faltados or 0),
        })
    return agrupado


def nombres_conceptos_computables_cts(db, empresa_id: int) -> set:
    """Nombres de los conceptos de INGRESO marcados 'Computable CTS' en el Maestro de Conceptos."""
    return {
        c.nombre for c in db.query(Concepto).filter_by(
            empresa_id=empresa_id, tipo='INGRESO', computable_cts=True,
        ).all()
    }


def nombres_conceptos_computables_grati(db, empresa_id: int) -> set:
    """Nombres de los conceptos de INGRESO marcados 'Computable Grati' en el Maestro de Conceptos."""
    return {
        c.nombre for c in db.query(Concepto).filter_by(
            empresa_id=empresa_id, tipo='INGRESO', computable_grati=True,
        ).all()
    }


def planilla_cerrada(db, empresa_id: int, periodo_key: str) -> bool:
    p = db.query(PlanillaMensual).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first()
    return bool(p and getattr(p, 'estado', 'ABIERTA') == 'CERRADA')


def sueldos_de_planilla(db, empresa_id: int, periodo_key: str) -> dict:
    """
    Sueldo básico nominal con el que se calculó la planilla de un periodo,
    por DNI: {dni: sueldo}. Vacío si la planilla no existe o es antigua y no
    guardaba 'sueldo_base_nominal' en la auditoría.
    """
    p = db.query(PlanillaMensual).filter_by(empresa_id=empresa_id, periodo_key=periodo_key).first()
    if not p:
        return {}
    resultado = {}
    for dni, data in _json_dict(p.auditoria_json).items():
        if isinstance(data, dict) and data.get('sueldo_base_nominal'):
            try:
                resultado[str(dni)] = float(data['sueldo_base_nominal'])
            except (TypeError, ValueError):
                pass
    return resultado
