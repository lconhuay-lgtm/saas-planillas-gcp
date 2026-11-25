"""
Valorización de Gratificación y CTS "AL CORTE": lo que se pagaría si el trabajador cesara el
último día del mes que se está provisionando.

Es la base de la regla "no provisionar más de lo que calcularíamos": las provisiones usan
EXACTAMENTE las mismas llamadas que la liquidación por cese (core/use_cases/calculo_liquidacion_cese.py),
con el cese simulado en la fecha de corte. Así:
  - Remuneración fija: la vigente al corte (sueldo del mes + asignación familiar con la RMV del mes).
  - Remuneración variable: solo entra el concepto "computable" percibido en ≥ 3 meses del semestre
    transcurrido hasta el corte; su incorporación es suma ÷ 6 (semestre completo) o suma ÷ meses con
    servicio (semestre incompleto). Un variable que aún no llegó a 3 meses NO se provisiona, y no
    se proyectan meses futuros.
  - Meses: solo los completos transcurridos (gratificación) o dozavos y treintavos (CTS).
Un test (tests/test_provision_cts.py) verifica que esto coincide con calcular_liquidacion().
"""
import datetime
import types

from core.use_cases.calculo_beneficios_sociales import (
    calcular_gratificacion_trabajador, calcular_cts_trabajador,
    rango_cts, rango_grati, periodo_keys_rango, meses_con_servicio,
    dias_no_computables_cts, extras_computables_cts, extras_computables_regulares,
)
from core.use_cases.calculo_liquidacion_cese import (
    _semestre_grati_de_fecha, _periodo_cts_de_fecha, _obtener_grati_referencia_cts,
)


def trabajador_al_corte(t, fecha_corte: datetime.date, sueldo: float = None):
    """Copia en memoria del trabajador con el cese simulado al corte (o su cese real si fue antes)."""
    cese_real = getattr(t, 'fecha_cese', None)
    return types.SimpleNamespace(
        id=getattr(t, 'id', None),
        fecha_ingreso=t.fecha_ingreso,
        fecha_cese=cese_real if (cese_real and cese_real <= fecha_corte) else fecha_corte,
        sueldo_base=float(sueldo if sueldo is not None else (t.sueldo_base or 0.0)),
        asig_fam=bool(getattr(t, 'asig_fam', False)),
        num_doc=t.num_doc,
        eps=bool(getattr(t, 'eps', False)),
        dias_vacaciones_anuales=getattr(t, 'dias_vacaciones_anuales', None) or 30,
    )


def valorizar_gratificacion_al(db, empresa_id: int, t, fecha_corte: datetime.date, rmv: float,
                               regimen_empresa: str, fecha_acogimiento=None, factor_override=None,
                               sueldo: float = None) -> dict:
    """Resultado de calcular_gratificacion_trabajador() del semestre de `fecha_corte`, al corte."""
    from infrastructure.repositories.repo_beneficios import (
        cargar_variables_rango, nombres_conceptos_computables_grati,
    )
    sim = trabajador_al_corte(t, fecha_corte, sueldo)
    semestre, anio = _semestre_grati_de_fecha(fecha_corte)
    ini, fin = rango_grati(semestre, anio)
    variables = cargar_variables_rango(
        db, empresa_id, periodo_keys_rango(ini, min(fin, fecha_corte)), trabajador_id=t.id,
    ).get(t.id, [])
    extras = extras_computables_regulares(
        variables, nombres_conceptos_computables_grati(db, empresa_id),
        meses_con_servicio(t.fecha_ingreso, sim.fecha_cese, ini, fin),
    )
    res = calcular_gratificacion_trabajador(
        sim, semestre, anio, rmv, regimen_empresa=regimen_empresa, fecha_acogimiento=fecha_acogimiento,
        factor_override=factor_override, extras_computables=extras['total'],
    )
    res['semestre'], res['anio'] = semestre, anio
    return res


def valorizar_cts_al(db, empresa_id: int, t, fecha_corte: datetime.date, rmv: float,
                     regimen_empresa: str, fecha_acogimiento=None, factor_override=None,
                     sueldo: float = None) -> dict:
    """Resultado de calcular_cts_trabajador() del periodo CTS de `fecha_corte`, al corte.
    Agrega 'periodo_cts', 'anio_dep' y 'grati_ref' (la gratificación de referencia para el sexto)."""
    from infrastructure.repositories.repo_beneficios import (
        cargar_variables_rango, nombres_conceptos_computables_cts,
    )
    sim = trabajador_al_corte(t, fecha_corte, sueldo)
    periodo_cts, anio_dep = _periodo_cts_de_fecha(fecha_corte)
    grati_ref = _obtener_grati_referencia_cts(
        db, t, empresa_id, periodo_cts, anio_dep, regimen_empresa, fecha_acogimiento, factor_override, rmv,
    )
    inicio, fin = rango_cts(periodo_cts, anio_dep)
    variables = cargar_variables_rango(
        db, empresa_id, periodo_keys_rango(inicio, min(fin, fecha_corte)), trabajador_id=t.id,
    ).get(t.id, [])
    extras = extras_computables_cts(
        variables, nombres_conceptos_computables_cts(db, empresa_id),
        meses_con_servicio(t.fecha_ingreso, sim.fecha_cese, inicio, fin),
    )
    res = calcular_cts_trabajador(
        sim, periodo_cts, anio_dep, rmv, grati_semestral=grati_ref['monto'],
        regimen_empresa=regimen_empresa, fecha_acogimiento=fecha_acogimiento,
        extras_computables=extras['total'], dias_no_computables=dias_no_computables_cts(variables),
    )
    res['periodo_cts'], res['anio_dep'], res['grati_ref'] = periodo_cts, anio_dep, grati_ref
    return res
