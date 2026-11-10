"""Pruebas del motor de CTS (core/use_cases/calculo_beneficios_sociales.py)."""
import datetime
from types import SimpleNamespace

import pytest

from core.use_cases.calculo_beneficios_sociales import (
    calcular_cts_trabajador,
    clave_periodo,
    dias_no_computables_cts,
    extras_computables_cts,
    meses_con_servicio,
    periodo_keys_rango,
    rango_cts,
)

RMV = 1130.0
D = datetime.date


def _trab(sueldo=3000.0, asig_fam=True, ingreso=D(2020, 1, 1), cese=None):
    return SimpleNamespace(fecha_ingreso=ingreso, fecha_cese=cese, sueldo_base=sueldo, asig_fam=asig_fam)


# ── Ordenamiento de periodos (causa del error de RMV) ─────────────────────────

def test_clave_periodo_ordena_cronologicamente_y_no_como_texto():
    periodos = ["12-2025", "11-2026", "05-2026"]
    assert max(periodos) == "12-2025"                      # el error anterior
    assert max(periodos, key=clave_periodo) == "11-2026"   # lo correcto


def test_clave_periodo_invalida():
    assert clave_periodo("basura") == (0, 0)
    assert clave_periodo(None) == (0, 0)


def test_rango_y_periodos_del_semestre():
    assert rango_cts('NOV-ABR', 2026) == (D(2025, 11, 1), D(2026, 4, 30))
    assert rango_cts('MAY-OCT', 2026) == (D(2026, 5, 1), D(2026, 10, 31))
    assert periodo_keys_rango(D(2025, 11, 1), D(2026, 4, 30)) == [
        "11-2025", "12-2025", "01-2026", "02-2026", "03-2026", "04-2026",
    ]


# ── Cálculo base ─────────────────────────────────────────────────────────────

def test_cts_semestre_completo():
    # 3000 + 113 (asig. fam.) + 3113/6 (sexto) = 3631.83 → × 6/12
    r = calcular_cts_trabajador(_trab(), 'MAY-OCT', 2026, RMV, grati_semestral=3113.0)
    assert r['base_cts'] == pytest.approx(3631.83, abs=0.01)
    assert r['meses_computados'] == 6
    assert r['monto_cts'] == pytest.approx(1815.92, abs=0.01)


def test_cts_usa_sueldo_vigente_al_cierre_si_se_indica():
    r = calcular_cts_trabajador(_trab(sueldo=3500.0), 'MAY-OCT', 2026, RMV,
                                grati_semestral=0.0, remuneracion_basica=3000.0)
    assert r['sueldo_base_usado'] == 3000.0
    assert r['remuneracion_base'] == pytest.approx(3113.0)


def test_cts_pequena_empresa_50_por_ciento():
    t = _trab(ingreso=D(2024, 1, 1))
    r = calcular_cts_trabajador(t, 'MAY-OCT', 2026, RMV, grati_semestral=0.0,
                                regimen_empresa="Régimen Especial - Pequeña Empresa",
                                fecha_acogimiento=D(2023, 1, 1))
    assert r['factor_cts'] == 0.5
    assert r['monto_cts'] == pytest.approx(3113.0 * 0.5 * 0.5, abs=0.01)


def test_cts_derechos_adquiridos_mantiene_100_por_ciento():
    t = _trab(ingreso=D(2020, 1, 1))
    r = calcular_cts_trabajador(t, 'MAY-OCT', 2026, RMV, grati_semestral=0.0,
                                regimen_empresa="Régimen Especial - Pequeña Empresa",
                                fecha_acogimiento=D(2023, 1, 1))
    assert r['factor_cts'] == 1.0


# ── Faltas y suspensiones no computables ─────────────────────────────────────

def test_faltas_injustificadas_se_descuentan_por_treintavos():
    r = calcular_cts_trabajador(_trab(), 'MAY-OCT', 2026, RMV, grati_semestral=3113.0,
                                dias_no_computables=3)
    esperado = 3631.83 * (6 / 12 - 3 / 360)
    assert r['monto_cts'] == pytest.approx(esperado, abs=0.01)
    assert r['dias_no_computables'] == 3


def test_descuento_nunca_vuelve_negativa_la_cts():
    t = _trab(ingreso=D(2026, 10, 20))
    r = calcular_cts_trabajador(t, 'MAY-OCT', 2026, RMV, dias_no_computables=60)
    assert r['monto_cts'] == 0.0


def test_dias_no_computables_solo_cuenta_suspensiones_perfectas():
    meses = [
        {'suspensiones': {"07": 2, "23": 15}, 'dias_faltados': 0},   # falta + vacaciones
        {'suspensiones': {"05": 3, "20": 4}, 'dias_faltados': 0},    # lic. sin goce + desc. médico
        {'suspensiones': {"09": 30, "02": 1}, 'dias_faltados': 0},   # maternidad y huelga: computables
        {'suspensiones': {"7": 1}, 'dias_faltados': 0},              # código sin cero a la izquierda
    ]
    assert dias_no_computables_cts(meses) == 2 + 3 + 1


def test_dias_faltados_legado_cuando_no_hay_suspensiones():
    meses = [{'suspensiones': {}, 'dias_faltados': 2},
             {'suspensiones': {"23": 5}, 'dias_faltados': 9}]  # con suspensiones manda el JSON
    assert dias_no_computables_cts(meses) == 2


# ── Remuneraciones computables (antes ignoradas) ─────────────────────────────

def test_concepto_regular_se_promedia_entre_6():
    meses = [{'conceptos': {"BONO PRODUCTIVIDAD": 300.0}} for _ in range(3)] + \
            [{'conceptos': {}} for _ in range(3)]
    r = extras_computables_cts(meses, {"BONO PRODUCTIVIDAD"}, meses_servicio=6)
    assert r['total'] == pytest.approx(150.0)
    assert r['detalle'] == {"BONO PRODUCTIVIDAD": 150.0}


def test_concepto_no_regular_no_se_incluye():
    meses = [{'conceptos': {"COMISION": 500.0}}, {'conceptos': {"COMISION": 500.0}}]
    r = extras_computables_cts(meses, {"COMISION"}, meses_servicio=6)
    assert r['total'] == 0.0
    assert r['no_regulares'] == ["COMISION"]


def test_solo_cuentan_conceptos_marcados_y_no_la_gratificacion_ni_ajustes():
    meses = [{'conceptos': {"MOVILIDAD": 200.0, "GRATIFICACION (JUL/DIC)": 3000.0,
                            "_ajuste_otros": 50.0, "BONO": 100.0}} for _ in range(6)]
    r = extras_computables_cts(meses, {"BONO", "GRATIFICACION (JUL/DIC)", "_ajuste_otros"}, 6)
    assert r['detalle'] == {"BONO": 100.0}


def test_semestre_incompleto_divide_entre_meses_con_servicio():
    meses = [{'conceptos': {"BONO": 200.0}} for _ in range(2)]
    r = extras_computables_cts(meses, {"BONO"}, meses_servicio=4)
    assert r['total'] == pytest.approx(100.0)   # 400 / 4, regular con 2 de 4 meses


def test_extras_entran_en_la_base_de_la_cts():
    r = calcular_cts_trabajador(_trab(asig_fam=False), 'MAY-OCT', 2026, RMV,
                                grati_semestral=0.0, extras_computables=150.0)
    assert r['remuneracion_base'] == pytest.approx(3150.0)
    assert r['monto_cts'] == pytest.approx(1575.0, abs=0.01)


def test_meses_con_servicio():
    ini, fin = rango_cts('MAY-OCT', 2026)
    assert meses_con_servicio(D(2020, 1, 1), None, ini, fin) == 6
    assert meses_con_servicio(D(2026, 7, 15), None, ini, fin) == 4
    assert meses_con_servicio(D(2020, 1, 1), D(2026, 6, 10), ini, fin) == 2
