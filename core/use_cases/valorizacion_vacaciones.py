"""
Valorización de las vacaciones: UNA sola función de base remuneratoria, usada por la
liquidación por cese (vacaciones truncas) y por la provisión mensual, para que ambas
coincidan siempre ("no provisionar más de lo que calcularíamos").

Base legal (revisada con fuentes secundarias; confirmar con el texto oficial y su contador):
  - La remuneración vacacional es la que el trabajador percibiría de continuar laborando y se
    toma la computable para la CTS (D.Leg. 713 Art. 15; D.S. 012-92-TR Art. 16).
  - Esa base incluye lo regular (D.S. 001-97-TR Art. 9): sueldo, asignación familiar y las
    remuneraciones variables regulares, que se promedian (Arts. 16-17: ≥ 3 meses en cada
    periodo de 6, suma ÷ 6). La Cas. Lab. 26128-2017-Lima incluyó la asignación familiar.

BASE_VACACIONAL_COMPUTABLE:
  - False (valor actual): solo el sueldo base — el criterio que la liquidación usaba hasta ahora,
    por lo que NINGÚN monto pagado cambia mientras esté en False.
  - True: sueldo + asignación familiar (10 % RMV) + promedio de variables regulares (conceptos
    marcados "Computable CTS"). Es lo que indican las fuentes; al activarlo suben las vacaciones
    truncas de la liquidación y la provisión, de forma consistente. Decisión del usuario.
"""
import datetime

from core.use_cases.calculo_beneficios_sociales import (
    extras_computables_cts, meses_con_servicio, periodo_keys_rango,
)

BASE_VACACIONAL_COMPUTABLE = False


def valorizar_remuneracion_vacacional(db, empresa_id: int, trabajador, fecha_corte: datetime.date,
                                      sueldo: float, rmv: float = None) -> dict:
    """
    Remuneración MENSUAL con la que se valorizan las vacaciones (el día = base_mensual / 30).
    Devuelve {'base_mensual', 'sueldo', 'asig_fam', 'extras', 'computable': bool}.

    `rmv` solo hace falta con BASE_VACACIONAL_COMPUTABLE activo y trabajador con asignación familiar.
    """
    sueldo = float(sueldo or 0.0)
    if not BASE_VACACIONAL_COMPUTABLE:
        return {'base_mensual': sueldo, 'sueldo': sueldo, 'asig_fam': 0.0, 'extras': 0.0, 'computable': False}

    asig_fam = 0.0
    if getattr(trabajador, 'asig_fam', False):
        if rmv is None:
            raise ValueError("Se necesita la RMV para valorizar la asignación familiar de las vacaciones.")
        asig_fam = float(rmv) * 0.10

    # Variables: últimos 6 meses hasta el corte (mismo criterio de regularidad que la CTS)
    from infrastructure.repositories.repo_beneficios import (
        cargar_variables_rango, nombres_conceptos_computables_cts,
    )
    mes0 = fecha_corte.month - 5
    anio0 = fecha_corte.year
    while mes0 < 1:
        mes0 += 12
        anio0 -= 1
    inicio = datetime.date(anio0, mes0, 1)
    variables = cargar_variables_rango(
        db, empresa_id, periodo_keys_rango(inicio, fecha_corte), trabajador_id=trabajador.id,
    ).get(trabajador.id, [])
    extras = extras_computables_cts(
        variables, nombres_conceptos_computables_cts(db, empresa_id),
        meses_con_servicio(getattr(trabajador, 'fecha_ingreso', None), fecha_corte, inicio, fecha_corte),
    )['total']

    return {'base_mensual': sueldo + asig_fam + extras, 'sueldo': sueldo, 'asig_fam': round(asig_fam, 2),
            'extras': extras, 'computable': True}
