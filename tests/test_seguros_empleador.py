"""Tests de Vida Ley y SCTR a cargo del empleador (core/domain/seguros_empleador.py)."""
import json

from core.domain import seguros_empleador as se


def _trab(**kw):
    base = {
        "Seg. Vida Ley": "No",
        "Seg. SCTR Salud": "No", "Seg. SCTR Salud Entidad": "EPS",
        "Seg. SCTR Pensión": "No", "Seg. SCTR Pensión Entidad": "ASEGURADORA",
    }
    base.update(kw)
    return base


def test_codigos_verificados_por_el_usuario():
    assert se.codigo_plame(se.VIDA_LEY, se.ASEGURADORA) == "0803"
    assert se.codigo_plame(se.SCTR_SALUD, se.EPS) == "0810"
    assert se.codigo_plame(se.SCTR_PENSION, se.ONP) == "0813"
    assert se.codigo_plame(se.SCTR_PENSION, se.ASEGURADORA) == "0814"


def test_sctr_salud_essalud_no_tiene_codigo_validado():
    # Pendiente de validar con declaración de prueba: no debe inventarse un código.
    assert se.codigo_plame(se.SCTR_SALUD, se.ESSALUD) is None


def test_sin_marcas_no_hay_aportes_aunque_haya_montos():
    cj = {"_seg_vida_ley": 50.0, "_seg_sctr_salud": 30.0, "_seg_sctr_pension": 20.0}
    assert se.calcular_aportes_empleador(_trab(), cj) == {}


def test_marcado_con_monto_genera_aporte_con_codigo():
    t = _trab(**{"Seg. Vida Ley": "Sí", "Seg. SCTR Salud": "Sí", "Seg. SCTR Pensión": "Sí"})
    cj = {"_seg_vida_ley": 12.5, "_seg_sctr_salud": 40.0, "_seg_sctr_pension": 25.75}
    ap = se.calcular_aportes_empleador(t, cj)
    assert ap[se.VIDA_LEY]["codigo"] == "0803" and ap[se.VIDA_LEY]["monto"] == 12.5
    assert ap[se.SCTR_SALUD]["codigo"] == "0810" and ap[se.SCTR_SALUD]["entidad"] == "EPS"
    assert ap[se.SCTR_PENSION]["codigo"] == "0814" and ap[se.SCTR_PENSION]["monto"] == 25.75
    assert se.total_aportes(ap) == 78.25


def test_entidad_distinta_por_trabajador():
    # Mismo mes, dos trabajadores: uno con EPS/ONP, otro con EsSalud/aseguradora.
    cj = {"_seg_sctr_salud": 30.0, "_seg_sctr_pension": 20.0}
    a = se.calcular_aportes_empleador(
        _trab(**{"Seg. SCTR Salud": "Sí", "Seg. SCTR Salud Entidad": "EPS",
                 "Seg. SCTR Pensión": "Sí", "Seg. SCTR Pensión Entidad": "ONP"}), cj)
    b = se.calcular_aportes_empleador(
        _trab(**{"Seg. SCTR Salud": "Sí", "Seg. SCTR Salud Entidad": "ESSALUD",
                 "Seg. SCTR Pensión": "Sí", "Seg. SCTR Pensión Entidad": "ASEGURADORA"}), cj)
    assert (a[se.SCTR_SALUD]["codigo"], a[se.SCTR_PENSION]["codigo"]) == ("0810", "0813")
    assert (b[se.SCTR_SALUD]["codigo"], b[se.SCTR_PENSION]["codigo"]) == (None, "0814")


def test_marcado_sin_monto_no_genera_aporte_pero_se_avisa():
    t = _trab(**{"Seg. Vida Ley": "Sí", "Seg. SCTR Salud": "Sí"})
    cj = {"_seg_vida_ley": 10.0}
    ap = se.calcular_aportes_empleador(t, cj)
    assert set(ap) == {se.VIDA_LEY}
    assert se.marcados_sin_monto(t, cj) == ["SCTR Salud"]


def test_monto_negativo_o_invalido_se_trata_como_cero():
    assert se.monto_digitado({"_seg_vida_ley": -5}, se.VIDA_LEY) == 0.0
    assert se.monto_digitado({"_seg_vida_ley": "abc"}, se.VIDA_LEY) == 0.0
    assert se.monto_digitado({"_seg_vida_ley": None}, se.VIDA_LEY) == 0.0
    assert se.monto_digitado({}, se.VIDA_LEY) == 0.0


def test_entidad_ajena_o_vacia_cae_a_la_por_defecto():
    assert se.normalizar_entidad(se.SCTR_SALUD, "") == "EPS"
    assert se.normalizar_entidad(se.SCTR_SALUD, "ONP") == "EPS"      # ONP no aplica a salud
    assert se.normalizar_entidad(se.SCTR_PENSION, None) == "ASEGURADORA"
    assert se.normalizar_entidad(se.SCTR_PENSION, "onp") == "ONP"


def test_marcas_aceptan_bool_y_si_no():
    assert se.seguros_marcados({"Seg. Vida Ley": True}) == {se.VIDA_LEY: "ASEGURADORA"}
    assert se.seguros_marcados({"Seg. Vida Ley": "Sí"}) == {se.VIDA_LEY: "ASEGURADORA"}
    assert se.seguros_marcados({"Seg. Vida Ley": "No"}) == {}
    assert se.seguros_marcados({"Seg. Vida Ley": float("nan")}) == {}
    assert se.seguros_marcados({}) == {}


def test_el_resultado_es_serializable_a_json_para_la_auditoria():
    t = _trab(**{"Seg. Vida Ley": "Sí"})
    ap = se.calcular_aportes_empleador(t, {"_seg_vida_ley": 9.9})
    assert json.loads(json.dumps(ap)) == ap


def test_totales_por_seguro_suma_todos_los_trabajadores():
    aud = {
        "111": {"aportes_empleador": {"VIDA_LEY": {"monto": 10.5}, "SCTR_SALUD": {"monto": 30.0}}},
        "222": {"aportes_empleador": {"VIDA_LEY": {"monto": 4.5}}},
        "333": {"aportes_empleador": {}},
        "444": {},   # periodo calculado antes de existir esta función
    }
    assert se.totales_por_seguro(aud) == {"VIDA_LEY": 15.0, "SCTR_SALUD": 30.0, "SCTR_PENSION": 0.0}
    assert se.totales_por_seguro({}) == {"VIDA_LEY": 0.0, "SCTR_SALUD": 0.0, "SCTR_PENSION": 0.0}
    assert se.totales_por_seguro(None) == {"VIDA_LEY": 0.0, "SCTR_SALUD": 0.0, "SCTR_PENSION": 0.0}


def test_resumen_agrupa_por_seguro_y_entidad():
    aud = {
        "1": {"aportes_empleador": {"SCTR_SALUD": {"entidad": "EPS", "monto": 30.0},
                                    "SCTR_PENSION": {"entidad": "ONP", "monto": 20.0}}},
        "2": {"aportes_empleador": {"SCTR_SALUD": {"entidad": "EPS", "monto": 10.0}}},
        "3": {"aportes_empleador": {"SCTR_SALUD": {"entidad": "ESSALUD", "monto": 5.0},
                                    "VIDA_LEY": {"entidad": "ASEGURADORA", "monto": 8.0}}},
        "4": {"aportes_empleador": {"VIDA_LEY": {"entidad": "ASEGURADORA", "monto": 0}}},  # monto 0: se ignora
    }
    assert se.resumen_por_seguro_entidad(aud) == [
        ("VIDA_LEY", "ASEGURADORA", 1, 8.0),
        ("SCTR_SALUD", "EPS", 2, 40.0),
        ("SCTR_SALUD", "ESSALUD", 1, 5.0),
        ("SCTR_PENSION", "ONP", 1, 20.0),
    ]
    assert se.resumen_por_seguro_entidad({}) == []


def test_claves_reservadas_no_chocan_con_ajustes_de_auditoria():
    reservadas = set(se.CLAVE_JSON.values())
    assert reservadas.isdisjoint({"_ajuste_afp", "_ajuste_quinta", "_ajuste_otros"})
    assert all(c.startswith("_") for c in reservadas)
