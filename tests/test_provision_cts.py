"""
Provisión de CTS (al corte, con el mismo motor que la liquidación), ajuste contra el depósito real,
regla de remuneración variable, valorización de vacaciones y consistencia con calcular_liquidacion().

SEGURIDAD: usa SQLite temporal y se salta si el motor no es SQLite (el .env apunta a la base real).
"""
import datetime
import io
import json
import os
import tempfile

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test_cts.db")

from infrastructure.database import connection  # noqa: E402

if not str(connection.engine.url).startswith("sqlite"):
    pytest.skip("El motor no es SQLite: se omite para no tocar una base real.", allow_module_level=True)

import pandas as pd  # noqa: E402
from infrastructure.database import models as m  # noqa: E402
from core.use_cases import provision_cts as pc  # noqa: E402
from core.use_cases import valorizacion_vacaciones as vv  # noqa: E402
from core.use_cases.generador_asiento_contable import AsientoContableError  # noqa: E402
from core.use_cases.generador_asiento_liquidacion import generar_asiento_liquidacion  # noqa: E402
from core.use_cases.calculo_liquidacion_cese import calcular_liquidacion  # noqa: E402

DNI = "11111111"     # ingresó 01/01/2026, sueldo 3000

CUENTAS = dict(
    cuenta_essalud_gasto="627101", cuenta_essalud_pasivo="403101", cuenta_onp="401701",
    cuenta_retencion_5ta="401111", cuenta_remuneraciones_por_pagar="411101",
    cuenta_cts_gasto="621401", cuenta_cts_por_pagar="415301",
)


def _excel(buf):
    return pd.read_excel(io.BytesIO(buf.getvalue()), dtype={"Cuenta": str})


def _totales(df, cuenta):
    f = df[df["Cuenta"] == cuenta]
    return round(f["Monto Debe"].sum(), 2), round(f["Monto Haber"].sum(), 2)


def _cuadra(df):
    return round(df["Monto Debe"].sum() - df["Monto Haber"].sum(), 2) == 0


def _planilla(db, periodo, estado="CERRADA"):
    aud = {DNI: {"nombres": "TRAB 1", "ingresos": {"Sueldo Base (30 días)": 3000.0}, "descuentos": {},
                 "sueldo_base_nominal": 3000.0, "quinta": {"retencion": 0}}}
    db.add(m.PlanillaMensual(empresa_id=db.empresa_id, periodo_key=periodo, estado=estado,
                             resultado_json="[]", auditoria_json=json.dumps(aud)))
    db.commit()


@pytest.fixture
def db():
    m.Base.metadata.drop_all(bind=connection.engine)
    m.Base.metadata.create_all(bind=connection.engine)
    s = connection.SessionLocal()
    emp = m.Empresa(ruc="20123456789", razon_social="BASCAT TEST SAC", regimen_laboral="Régimen General")
    s.add(emp)
    s.flush()
    s.empresa_id = emp.id
    s.add(m.Trabajador(empresa_id=emp.id, tipo_doc="DNI", tipo_documento="01", num_doc=DNI, nombres="TRAB 1",
                       sueldo_base=3000.0, tipo_contrato="PLANILLA", sistema_pension="ONP", eps=False, asig_fam=False,
                       fecha_ingreso=datetime.date(2026, 1, 1), situacion="ACTIVO", dias_vacaciones_anuales=30))
    s.add(m.ParametroLegal(
        empresa_id=emp.id, periodo_key="01-2026", rmv=1130.0, uit=5350.0, tasa_essalud=9.0, tasa_eps=2.25,
        tasa_onp=13.0, tope_afp=12000.0,
        h_ap=10.0, h_pr=1.4, h_fl=1.5, h_mx=0.0, i_ap=10.0, i_pr=1.4, i_fl=1.5, i_mx=0.0,
        p_ap=10.0, p_pr=1.4, p_fl=1.5, p_mx=0.0, pr_ap=10.0, pr_pr=1.4, pr_fl=1.5, pr_mx=0.0))
    s.commit()
    s.tid = s.query(m.Trabajador).filter_by(num_doc=DNI).one().id
    yield s
    s.close()


def _config(db, **extra):
    db.add(m.ConfiguracionContable(empresa_id=db.empresa_id, **{**CUENTAS, **extra}))
    db.commit()


# ── Provisión al corte ───────────────────────────────────────────────────────────

def test_julio_provisiona_de_golpe_lo_devengado_del_periodo(db):
    """MAY-OCT 2026 al 31/07: 3 meses × (3000 + sexto de grati 500) / 12 = 875 (ajuste en julio)."""
    _planilla(db, "07-2026")
    f = pc.calcular_provision_mes(db, db.empresa_id, "07-2026")[0]
    assert f["periodo_cts"] == "MAY-OCT-2026" and f["meses"] == 3
    assert f["base_cts"] == 3500.0 and f["objetivo"] == 875.0 and f["delta_provision"] == 875.0


# ── Regularización ÚNICA de NOV-ABR (solo julio 2026) ────────────────────────────

def _deposito_mayo(db, monto):
    db.add(m.DepositoCTS(empresa_id=db.empresa_id, trabajador_id=db.tid, periodo_label="NOV 2025 – ABR 2026",
                         periodo_key_deposito="05-2026", monto=monto, estado="PENDIENTE"))
    db.commit()


def test_julio_regulariza_una_sola_vez_la_cts_pendiente_de_nov_abr(db):
    """Trabajador de 01/01/2026: 4 meses (ene–abr) de NOV-ABR, todos sin provisionar."""
    _planilla(db, "07-2026")
    f = pc.calcular_provision_mes(db, db.empresa_id, "07-2026", incluir_reg_nov_abr=True)[0]
    assert f["reg_periodo"] == "NOV-ABR-2026" and f["reg_monto"] > 0
    assert f["delta_total"] == round(f["delta_provision"] + f["reg_monto"], 2)


def test_agosto_en_adelante_no_vuelve_a_regularizar(db):
    _planilla(db, "08-2026")
    f = pc.calcular_provision_mes(db, db.empresa_id, "08-2026", incluir_reg_nov_abr=True)[0]
    assert f["reg_monto"] == 0.0 and f["reg_periodo"] is None


def test_la_regularizacion_usa_el_deposito_registrado_si_existe(db):
    _deposito_mayo(db, 1200.0)
    _planilla(db, "07-2026")
    f = pc.calcular_provision_mes(db, db.empresa_id, "07-2026", incluir_reg_nov_abr=True)[0]
    assert f["reg_monto"] == 1200.0 and "depósito" in f["reg_fuente"]      # ingresó en enero: ene–abr = todo el periodo


def test_solo_se_regulariza_enero_a_abril_no_noviembre_diciembre_2025(db):
    """Ingresó el 01/11/2025: 6 meses en NOV-ABR, de los que solo 4 (ene–abr) se regularizan → 4/6 del depósito."""
    t = db.query(m.Trabajador).filter_by(id=db.tid).one()
    t.fecha_ingreso = datetime.date(2025, 11, 1)
    db.commit()
    _deposito_mayo(db, 1500.0)
    _planilla(db, "07-2026")
    assert pc.calcular_provision_mes(db, db.empresa_id, "07-2026", incluir_reg_nov_abr=True)[0]["reg_monto"] == 1000.0


def test_el_asiento_de_julio_incluye_la_regularizacion_con_su_documento_y_cuadra(db):
    _config(db)
    _deposito_mayo(db, 1200.0)
    _planilla(db, "07-2026")
    df = _excel(pc.generar_asiento_provision(db, db.empresa_id, "07-2026", incluir_reg_nov_abr=True))
    reg = df[df["Num.Doc"] == "CTS-NOVABR-2026"]
    assert round(reg["Monto Debe"].sum(), 2) == 1200.0 and round(reg["Monto Haber"].sum(), 2) == 1200.0
    assert df["Glosa"].str.contains("REGULARIZACION ENE-ABR").any()
    assert _cuadra(df)
    assert pc.provision_de_trabajador(db, db.empresa_id, db.tid, "NOV-ABR-2026") == 1200.0


def test_la_regularizacion_es_opcional_y_por_defecto_no_se_incluye(db):
    _deposito_mayo(db, 1200.0)
    _planilla(db, "07-2026")
    f = pc.calcular_provision_mes(db, db.empresa_id, "07-2026")[0]
    assert f["reg_monto"] == 0.0 and f["reg_periodo"] is None
    assert not pc.reg_nov_abr_registrada(db, db.empresa_id)


def test_se_recuerda_si_la_regularizacion_ya_se_registro(db):
    _config(db)
    _deposito_mayo(db, 1200.0)
    _planilla(db, "07-2026")
    pc.generar_asiento_provision(db, db.empresa_id, "07-2026", incluir_reg_nov_abr=True)
    assert pc.reg_nov_abr_registrada(db, db.empresa_id)


def test_la_provision_coincide_con_lo_que_pagaria_la_liquidacion_ese_dia(db):
    """La regla de oro: provisión == CTS trunca si el trabajador cesara el último día del mes."""
    _planilla(db, "08-2026")
    t = db.query(m.Trabajador).filter_by(id=db.tid).one()
    f = pc.calcular_provision_mes(db, db.empresa_id, "08-2026")[0]
    liq = calcular_liquidacion(db, t, db.empresa_id, datetime.date(2026, 8, 31), "Régimen General")
    assert f["objetivo"] == liq["monto_cts_trunca"]


def test_agosto_es_el_acumulado_menos_lo_ya_provisionado(db):
    _config(db)
    _planilla(db, "07-2026")
    _planilla(db, "08-2026")
    pc.generar_asiento_provision(db, db.empresa_id, "07-2026")
    f = pc.calcular_provision_mes(db, db.empresa_id, "08-2026")[0]
    assert f["objetivo"] == 1166.67 and f["ya_provisionado"] == 875.0 and f["delta_provision"] == 291.67


def test_asiento_cuadra_y_registra_en_el_libro(db):
    _config(db)
    _planilla(db, "07-2026")
    df = _excel(pc.generar_asiento_provision(db, db.empresa_id, "07-2026"))
    assert _totales(df, "621401") == (875.0, 0.0) and _totales(df, "415301") == (0.0, 875.0)
    assert _cuadra(df)
    assert pc.provision_de_trabajador(db, db.empresa_id, db.tid, "MAY-OCT-2026") == 875.0


def test_regenerar_el_mismo_mes_reemplaza_y_no_duplica(db):
    _config(db)
    _planilla(db, "07-2026")
    pc.generar_asiento_provision(db, db.empresa_id, "07-2026")
    pc.generar_asiento_provision(db, db.empresa_id, "07-2026")
    assert pc.provision_de_trabajador(db, db.empresa_id, db.tid, "MAY-OCT-2026") == 875.0


def test_no_se_puede_regenerar_un_mes_con_posteriores_y_un_mes_omitido_se_recupera(db):
    _config(db)
    for mes in ("07", "08", "09"):
        _planilla(db, f"{mes}-2026")
    pc.generar_asiento_provision(db, db.empresa_id, "07-2026")
    df = _excel(pc.generar_asiento_provision(db, db.empresa_id, "09-2026"))       # se omitió agosto
    assert _totales(df, "621401") == (583.33, 0.0)                                  # 1458.33 − 875
    with pytest.raises(AsientoContableError, match="posteriores"):
        pc.generar_asiento_provision(db, db.empresa_id, "07-2026")


def test_antes_del_corte_o_sin_cerrar_no_se_provisiona(db):
    _planilla(db, "06-2026")
    _planilla(db, "07-2026", estado="ABIERTA")
    with pytest.raises(AsientoContableError, match="julio 2026"):
        pc.calcular_provision_mes(db, db.empresa_id, "06-2026")
    with pytest.raises(AsientoContableError, match="no está cerrada"):
        pc.calcular_provision_mes(db, db.empresa_id, "07-2026")


def test_sin_cuentas_avisa_cuales_faltan_y_no_registra_nada(db):
    _config(db, cuenta_cts_gasto="", cuenta_cts_por_pagar="")
    _planilla(db, "07-2026")
    with pytest.raises(AsientoContableError) as ei:
        pc.generar_asiento_provision(db, db.empresa_id, "07-2026")
    assert any("CTS — Gasto" in c for c in ei.value.cuentas_faltantes)
    assert any("CTS — Por Pagar" in c for c in ei.value.cuentas_faltantes)
    assert db.query(m.ProvisionCTS).count() == 0


# ── Remuneración variable ────────────────────────────────────────────────────────

def _bono(db, meses, monto=300.0):
    db.add(m.Concepto(empresa_id=db.empresa_id, nombre="BONO PRODUCCION", tipo="INGRESO", computable_cts=True))
    for mes in meses:
        db.add(m.VariablesMes(empresa_id=db.empresa_id, trabajador_id=db.tid, periodo_key=f"{mes}-2026",
                              conceptos_json=json.dumps({"BONO PRODUCCION": monto})))
    db.commit()


def test_una_variable_con_menos_de_3_meses_no_se_provisiona(db):
    _bono(db, ["05", "06"])                           # solo 2 meses: aún no es "regular"
    _planilla(db, "07-2026")
    assert pc.calcular_provision_mes(db, db.empresa_id, "07-2026")[0]["objetivo"] == 875.0


def test_una_variable_regular_entra_promediada_y_solo_con_lo_percibido_hasta_el_corte(db):
    _bono(db, ["05", "06", "07"])                     # 3 meses: regular; 900 ÷ 3 meses con servicio = 300
    _bono_oct = m.VariablesMes(empresa_id=db.empresa_id, trabajador_id=db.tid, periodo_key="10-2026",
                               conceptos_json=json.dumps({"BONO PRODUCCION": 5000.0}))
    db.add(_bono_oct)                                 # un pago FUTURO enorme: no debe contarse en julio
    db.commit()
    _planilla(db, "07-2026")
    f = pc.calcular_provision_mes(db, db.empresa_id, "07-2026")[0]
    assert f["base_cts"] == 3800.0 and f["objetivo"] == 950.0      # (3000 + 300 + 500) × 3/12; sin proyectar el futuro
    # y sigue siendo exactamente lo que pagaría la liquidación ese día
    t = db.query(m.Trabajador).filter_by(id=db.tid).one()
    liq = calcular_liquidacion(db, t, db.empresa_id, datetime.date(2026, 7, 31), "Régimen General")
    assert f["objetivo"] == liq["monto_cts_trunca"]


# ── Depósito de noviembre: ajuste contra lo real + nuevo periodo ─────────────────

def test_noviembre_ajusta_contra_el_deposito_real_y_empieza_el_periodo_nuevo(db):
    _config(db)
    for mes in ("07", "08", "09", "10", "11"):
        _planilla(db, f"{mes}-2026")
    for mes in ("07", "08", "09", "10"):
        pc.generar_asiento_provision(db, db.empresa_id, f"{mes}-2026")
    assert pc.provision_de_trabajador(db, db.empresa_id, db.tid, "MAY-OCT-2026") == 1750.0   # 6 meses

    # el depósito real salió S/ 50 mayor (p. ej. hubo un ajuste de remuneración)
    db.add(m.DepositoCTS(empresa_id=db.empresa_id, trabajador_id=db.tid, periodo_label="MAY-OCT 2026",
                         periodo_key_deposito="11-2026", monto=1800.0, estado="DEPOSITADO"))
    db.commit()
    f = pc.calcular_provision_mes(db, db.empresa_id, "11-2026")[0]
    assert f["periodo_cierre"] == "MAY-OCT-2026" and f["delta_ajuste"] == 50.0
    assert f["periodo_cts"] == "NOV-ABR-2027" and f["delta_provision"] == 291.67       # 1 mes del periodo nuevo

    df = _excel(pc.generar_asiento_provision(db, db.empresa_id, "11-2026"))
    assert _totales(df, "621401") == (341.67, 0.0) and _totales(df, "415301") == (0.0, 341.67)
    assert _cuadra(df)
    assert pc.provision_de_trabajador(db, db.empresa_id, db.tid, "MAY-OCT-2026") == 1800.0   # pasivo = depósito
    assert pc.provision_de_trabajador(db, db.empresa_id, db.tid, "NOV-ABR-2027") == 291.67


def test_el_ajuste_solo_aplica_a_periodos_que_se_provisionaron(db):
    _config(db)
    db.add(m.DepositoCTS(empresa_id=db.empresa_id, trabajador_id=db.tid, periodo_label="MAY-OCT 2026",
                         periodo_key_deposito="11-2026", monto=1800.0, estado="DEPOSITADO"))
    db.commit()
    _planilla(db, "11-2026")                           # sin provisiones previas del periodo MAY-OCT-2026
    f = pc.calcular_provision_mes(db, db.empresa_id, "11-2026")[0]
    assert f["delta_ajuste"] == 0.0 and f["periodo_cierre"] is None


# ── Liquidación por cese ─────────────────────────────────────────────────────────

def _liquidacion(db, cts):
    liq = m.LiquidacionCese(
        empresa_id=db.empresa_id, trabajador_id=db.tid, estado="APROBADA",
        fecha_ingreso_snapshot=datetime.date(2026, 1, 1), fecha_cese_snapshot=datetime.date(2026, 9, 15),
        sueldo_base_snapshot=3000.0, periodo_cts_ref="MAY-OCT (dep. 2026)",
        monto_cts_trunca=cts, total_bruto=cts, total_neto=cts,
    )
    db.add(liq)
    db.commit()
    return liq


def test_liquidacion_sin_libro_mantiene_el_comportamiento_de_siempre(db):
    _config(db)
    liq = _liquidacion(db, 1500.0)
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "621401") == (1500.0, 0.0) and _totales(df, "415301") == (0.0, 1500.0)
    assert _cuadra(df)


def test_liquidacion_descuenta_lo_provisionado_del_periodo(db):
    _config(db)
    for mes in ("07", "08"):
        _planilla(db, f"{mes}-2026")
        pc.generar_asiento_provision(db, db.empresa_id, f"{mes}-2026")       # 1166.67 provisionado
    liq = _liquidacion(db, 1400.0)
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "415301") == (1166.67, 1400.0)                       # cancela lo provisionado
    assert _totales(df, "621401") == (233.33, 0.0)                           # solo la diferencia es gasto
    assert _cuadra(df)


def test_liquidacion_si_la_provision_excedio_recupera_gasto(db):
    _config(db)
    _planilla(db, "07-2026")
    pc.generar_asiento_provision(db, db.empresa_id, "07-2026")               # 875
    liq = _liquidacion(db, 700.0)
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "621401") == (0.0, 175.0)
    assert _cuadra(df)


def test_periodo_cts_desde_la_referencia_de_la_liquidacion():
    assert pc.periodo_desde_ref("MAY-OCT (dep. 2026)", datetime.date(2026, 9, 1)) == "MAY-OCT-2026"
    assert pc.periodo_desde_ref("NOV-ABR (dep. 2027)", datetime.date(2026, 12, 1)) == "NOV-ABR-2027"
    assert pc.periodo_desde_ref(None, datetime.date(2026, 12, 1)) == "NOV-ABR-2027"        # respaldo por fecha
    assert pc.periodo_que_cierra(2026, 5) == "NOV-ABR-2026" and pc.periodo_que_cierra(2026, 11) == "MAY-OCT-2026"
    assert pc.periodo_que_cierra(2026, 8) is None


# ── Valorización de vacaciones (base compartida con la liquidación) ──────────────

def test_vacaciones_por_defecto_solo_sueldo_nada_cambia(db):
    t = db.query(m.Trabajador).filter_by(id=db.tid).one()
    assert vv.BASE_VACACIONAL_COMPUTABLE is False
    r = vv.valorizar_remuneracion_vacacional(db, db.empresa_id, t, datetime.date(2026, 9, 30), 3000.0, 1130.0)
    assert r["base_mensual"] == 3000.0 and r["computable"] is False


def test_vacaciones_con_base_computable_suma_asignacion_familiar_y_variables(db, monkeypatch):
    monkeypatch.setattr(vv, "BASE_VACACIONAL_COMPUTABLE", True)
    t = db.query(m.Trabajador).filter_by(id=db.tid).one()
    t.asig_fam = True
    _bono(db, ["07", "08", "09"], monto=600.0)                       # regular: 3 de 6 meses
    r = vv.valorizar_remuneracion_vacacional(db, db.empresa_id, t, datetime.date(2026, 9, 30), 3000.0, 1130.0)
    assert r["asig_fam"] == 113.0 and r["extras"] == 300.0           # 1800 ÷ 6: ventana de 6 meses con servicio
    assert r["base_mensual"] == 3413.0


def test_vacaciones_con_base_computable_una_variable_irregular_no_entra(db, monkeypatch):
    monkeypatch.setattr(vv, "BASE_VACACIONAL_COMPUTABLE", True)
    t = db.query(m.Trabajador).filter_by(id=db.tid).one()
    _bono(db, ["08", "09"], monto=600.0)                             # solo 2 meses
    r = vv.valorizar_remuneracion_vacacional(db, db.empresa_id, t, datetime.date(2026, 9, 30), 3000.0, 1130.0)
    assert r["extras"] == 0.0 and r["base_mensual"] == 3000.0


def test_la_liquidacion_usa_la_misma_base_de_vacaciones_que_la_provision(db, monkeypatch):
    t = db.query(m.Trabajador).filter_by(id=db.tid).one()
    t.asig_fam = True
    db.commit()
    fc = datetime.date(2026, 9, 30)
    base = calcular_liquidacion(db, t, db.empresa_id, fc, "Régimen General")["monto_vacaciones_truncas"]
    monkeypatch.setattr(vv, "BASE_VACACIONAL_COMPUTABLE", True)
    con_asig = calcular_liquidacion(db, t, db.empresa_id, fc, "Régimen General")["monto_vacaciones_truncas"]
    assert con_asig > base                                           # con el flag activo suben (asignación familiar)
    assert round(con_asig / base, 4) == round(3113.0 / 3000.0, 4)
