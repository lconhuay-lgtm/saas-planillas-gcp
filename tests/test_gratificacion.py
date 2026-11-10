"""Pruebas de la gratificación: voluntaria, bono extraordinario con EPS y computables."""
import datetime
from types import SimpleNamespace

import pytest

from core.use_cases.calculo_beneficios_sociales import (
    OPCIONES_GRATI_VOLUNTARIA,
    calcular_gratificacion_trabajador,
    extras_computables_regulares,
    factor_grati_aplicable,
    rango_grati,
    tasa_bono_extraordinario,
)

D = datetime.date
RMV = 1130.0
GENERAL = "Régimen General"
MICRO = "Régimen Especial - Micro Empresa"
PEQUENA = "Régimen Especial - Pequeña Empresa"
ACOGIMIENTO = D(2023, 1, 1)


def _trab(ingreso=D(2024, 1, 1), sueldo=2000.0, asig_fam=False, eps=False, cese=None):
    return SimpleNamespace(fecha_ingreso=ingreso, fecha_cese=cese, sueldo_base=sueldo,
                           asig_fam=asig_fam, eps=eps)


def _grati(t, regimen, voluntaria=None, **kw):
    return calcular_gratificacion_trabajador(
        t, 'ENE-JUN', 2026, RMV, regimen_empresa=regimen,
        fecha_acogimiento=None if regimen == GENERAL else ACOGIMIENTO,
        factor_override=voluntaria, **kw)


# ── Gratificación voluntaria ────────────────────────────────────────────────

def test_micro_por_ley_no_paga_gratificacion():
    r = _grati(_trab(), MICRO)
    assert r['factor_grati'] == 0.0
    assert r['monto_grati'] == 0.0
    assert not r['aplica']


@pytest.mark.parametrize("opcion, factor, monto", [
    ("Media gratificación (50%)", 0.5, 1000.0),
    ("Gratificación completa (100%)", 1.0, 2000.0),
])
def test_micro_puede_otorgar_media_o_completa_voluntaria(opcion, factor, monto):
    r = _grati(_trab(), MICRO, OPCIONES_GRATI_VOLUNTARIA[opcion])
    assert r['factor_grati'] == factor
    assert r['es_voluntaria']
    assert r['monto_grati'] == pytest.approx(monto)
    assert "Voluntaria" in r['observaciones']


def test_pequena_puede_subir_a_completa():
    r = _grati(_trab(), PEQUENA, 1.0)
    assert r['factor_legal'] == 0.5
    assert r['factor_grati'] == 1.0


def test_media_voluntaria_no_recorta_al_regimen_general():
    r = _grati(_trab(), GENERAL, 0.5)
    assert r['factor_grati'] == 1.0          # antes quedaba en 50 %: ilegal
    assert not r['es_voluntaria']


def test_media_voluntaria_no_recorta_derechos_adquiridos():
    t = _trab(ingreso=D(2020, 1, 1))         # ingresó antes del acogimiento MYPE
    r = _grati(t, MICRO, 0.5)
    assert r['factor_grati'] == 1.0


def test_factor_aplicable_limites():
    assert factor_grati_aplicable(0.0, None) == 0.0
    assert factor_grati_aplicable(0.5, 0.0) == 0.5    # una política antigua "0" no recorta
    assert factor_grati_aplicable(0.0, 5) == 1.0      # nunca más del 100 %
    assert factor_grati_aplicable(1.0, "x") == 1.0


# ── Bonificación extraordinaria ─────────────────────────────────────────────

def test_bono_9_por_ciento_sin_eps():
    r = _grati(_trab(), GENERAL)
    assert r['bono_9pct'] == pytest.approx(180.0)
    assert r['total'] == pytest.approx(2180.0)


def test_bono_675_con_eps():
    r = _grati(_trab(eps=True), GENERAL)
    assert r['tasa_bono'] == 0.0675
    assert r['bono_9pct'] == pytest.approx(135.0)
    assert "EPS" in r['observaciones']


def test_tasa_bono():
    assert tasa_bono_extraordinario(False) == 0.09
    assert tasa_bono_extraordinario(True) == 0.0675


# ── Conceptos computables ───────────────────────────────────────────────────

def test_concepto_computable_regular_entra_en_la_base():
    meses = [{'conceptos': {"BONO": 300.0}} for _ in range(4)]
    extras = extras_computables_regulares(meses, {"BONO"}, 6)
    r = _grati(_trab(), GENERAL, extras_computables=extras['total'])
    assert extras['total'] == pytest.approx(200.0)
    assert r['base_computable'] == pytest.approx(2200.0)
    assert r['monto_grati'] == pytest.approx(2200.0)


def test_rango_grati():
    assert rango_grati('ENE-JUN', 2026) == (D(2026, 1, 1), D(2026, 6, 30))
    assert rango_grati('JUL-DIC', 2026) == (D(2026, 7, 1), D(2026, 12, 31))


def test_gratificacion_proporcional_por_meses_completos():
    r = _grati(_trab(ingreso=D(2026, 3, 15)), GENERAL)   # abril, mayo, junio completos
    assert r['meses_computados'] == 3
    assert r['monto_grati'] == pytest.approx(1000.0)
