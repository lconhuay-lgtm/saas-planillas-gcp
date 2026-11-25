"""
Provisión mensual de gratificación: libro de provisiones, asiento de provisión, pago en
julio/diciembre (descuenta lo provisionado) y liquidación por cese.

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

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test_provision.db")

from infrastructure.database import connection  # noqa: E402

if not str(connection.engine.url).startswith("sqlite"):
    pytest.skip("El motor no es SQLite: se omite para no tocar una base real.", allow_module_level=True)

import pandas as pd  # noqa: E402
from infrastructure.database import models as m  # noqa: E402
from core.use_cases import provision_gratificacion as pg  # noqa: E402
from core.use_cases.generador_asiento_contable import generar_asiento_planilla, AsientoContableError  # noqa: E402
from core.use_cases.generador_asiento_liquidacion import generar_asiento_liquidacion  # noqa: E402

DNI_A, DNI_B = "11111111", "22222222"

CUENTAS = dict(
    cuenta_essalud_gasto="627101", cuenta_essalud_pasivo="403101", cuenta_onp="401701",
    cuenta_retencion_5ta="401111", cuenta_remuneraciones_por_pagar="411101",
    cuenta_gratificacion_gasto="621201", cuenta_gratificacion_por_pagar="415101",
)


def _excel(buf):
    df = pd.read_excel(io.BytesIO(buf.getvalue()), dtype={"Cuenta": str})
    return df


def _totales(df, cuenta):
    f = df[df["Cuenta"] == cuenta]
    return round(f["Monto Debe"].sum(), 2), round(f["Monto Haber"].sum(), 2)


def _cuadra(df):
    return round(df["Monto Debe"].sum() - df["Monto Haber"].sum(), 2) == 0


def _planilla(db, periodo, con_grati=0.0, con_bono=0.0, estado="CERRADA", dnis=(DNI_A,)):
    """Planilla guardada: A gana 3000 (ingreso 2020); B gana 2000 (ingreso 15/08/2026)."""
    aud, filas = {}, []
    for dni, sueldo in ((DNI_A, 3000.0), (DNI_B, 2000.0)):
        if dni not in dnis:
            continue
        ingresos = {"Sueldo Base (30 días)": sueldo}
        if con_grati and dni == DNI_A:
            ingresos["Gratificación"] = con_grati
            ingresos["Bono Ext. 9%"] = con_bono
        aud[dni] = {"nombres": f"TRAB {dni}", "ingresos": ingresos, "descuentos": {},
                    "sueldo_base_nominal": sueldo, "quinta": {"retencion": 0}}
        filas.append({"DNI": dni, "Apellidos y Nombres": f"TRAB {dni}", "Sist. Pensión": "ONP",
                      "ONP (13%)": round(sueldo * 0.13, 2), "AFP Aporte": 0.0, "AFP Seguro": 0.0,
                      "AFP Comis.": 0.0, "Ret. 5ta Cat.": 0.0, "Aporte Seg. Social": round(sueldo * 0.09, 2)})
    db.add(m.PlanillaMensual(
        empresa_id=db.empresa_id, periodo_key=periodo, estado=estado,
        resultado_json=pd.DataFrame(filas).to_json(orient="records"), auditoria_json=json.dumps(aud),
    ))
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
    for dni, sueldo, ingreso in ((DNI_A, 3000.0, datetime.date(2020, 1, 1)), (DNI_B, 2000.0, datetime.date(2026, 8, 15))):
        s.add(m.Trabajador(empresa_id=emp.id, tipo_doc="DNI", tipo_documento="01", num_doc=dni,
                           nombres=f"TRAB {dni}", sueldo_base=sueldo, tipo_contrato="PLANILLA",
                           sistema_pension="ONP", fecha_ingreso=ingreso, eps=False, situacion="ACTIVO"))
    s.add(m.Concepto(empresa_id=emp.id, nombre="SUELDO BASICO", tipo="INGRESO", cuenta_contable="621101"))
    s.commit()
    s.id_a = s.query(m.Trabajador).filter_by(num_doc=DNI_A).one().id
    yield s
    s.close()


def _config(db, **extra):
    db.add(m.ConfiguracionContable(empresa_id=db.empresa_id, **{**CUENTAS, **extra}))
    db.commit()


def _libro(db, periodo, grati, bono, trabajador_id=None, sem="JUL-DIC-2026"):
    db.add(m.ProvisionGratificacion(empresa_id=db.empresa_id, trabajador_id=trabajador_id or db.id_a,
                                    periodo_key=periodo, semestre=sem, monto_grati=grati, monto_bono=bono))
    db.commit()


# ── Cálculo de la provisión ──────────────────────────────────────────────────────

def test_provision_julio_es_un_sexto_mas_bono(db):
    _planilla(db, "07-2026", dnis=(DNI_A, DNI_B))
    filas = {f["dni"]: f for f in pg.calcular_provision_mes(db, db.empresa_id, "07-2026")}
    a = filas[DNI_A]
    assert a["meses_computados"] == 1 and a["base_computable"] == 3000.0
    assert a["delta_grati"] == 500.0 and a["delta_bono"] == 45.0 and a["delta_total"] == 545.0
    # B ingresó el 15/08: julio no cuenta, y aunque estuviera en planilla no devenga nada aún
    assert filas[DNI_B]["delta_total"] == 0.0


def test_provision_agosto_es_acumulado_menos_lo_ya_registrado(db):
    _config(db)
    _planilla(db, "07-2026")
    _planilla(db, "08-2026", dnis=(DNI_A, DNI_B))
    pg.generar_asiento_provision(db, db.empresa_id, "07-2026")
    filas = {f["dni"]: f for f in pg.calcular_provision_mes(db, db.empresa_id, "08-2026")}
    assert filas[DNI_A]["objetivo_grati"] == 1000.0 and filas[DNI_A]["ya_provisionado"] == 545.0
    assert filas[DNI_A]["delta_grati"] == 500.0 and filas[DNI_A]["delta_bono"] == 45.0
    assert filas[DNI_B]["meses_computados"] == 0 and filas[DNI_B]["delta_total"] == 0.0   # agosto incompleto


def test_provision_corta_en_julio_2026(db):
    _planilla(db, "06-2026")
    with pytest.raises(AsientoContableError, match="julio 2026"):
        pg.calcular_provision_mes(db, db.empresa_id, "06-2026")
    assert not pg.es_provisionable("06-2026") and pg.es_provisionable("07-2026")


def test_provision_exige_planilla_cerrada(db):
    _planilla(db, "07-2026", estado="ABIERTA")
    with pytest.raises(AsientoContableError, match="no está cerrada"):
        pg.calcular_provision_mes(db, db.empresa_id, "07-2026")


# ── Asiento de provisión y libro ─────────────────────────────────────────────────

def test_asiento_provision_cuadra_y_registra_en_el_libro(db):
    _config(db)
    _planilla(db, "07-2026")
    df = _excel(pg.generar_asiento_provision(db, db.empresa_id, "07-2026"))
    assert _totales(df, "621201") == (545.0, 0.0)      # gasto al débito
    assert _totales(df, "415101") == (0.0, 545.0)      # pasivo al crédito
    assert _cuadra(df)
    assert pg.provisiones_por_dni(db, db.empresa_id, "JUL-DIC", 2026) == {DNI_A: (500.0, 45.0)}


def test_regenerar_el_mismo_mes_reemplaza_y_no_duplica(db):
    _config(db)
    _planilla(db, "07-2026")
    pg.generar_asiento_provision(db, db.empresa_id, "07-2026")
    pg.generar_asiento_provision(db, db.empresa_id, "07-2026")
    assert pg.provisiones_por_dni(db, db.empresa_id, "JUL-DIC", 2026) == {DNI_A: (500.0, 45.0)}


def test_no_se_puede_regenerar_un_mes_con_posteriores_registrados(db):
    _config(db)
    _planilla(db, "07-2026")
    _planilla(db, "08-2026")
    pg.generar_asiento_provision(db, db.empresa_id, "07-2026")
    pg.generar_asiento_provision(db, db.empresa_id, "08-2026")
    with pytest.raises(AsientoContableError, match="posteriores"):
        pg.generar_asiento_provision(db, db.empresa_id, "07-2026")


def test_si_se_omite_un_mes_el_siguiente_lo_recupera(db):
    _config(db)
    _planilla(db, "07-2026")
    _planilla(db, "08-2026")
    _planilla(db, "09-2026")
    pg.generar_asiento_provision(db, db.empresa_id, "07-2026")
    # se salta agosto: septiembre debe provisionar 2 meses (objetivo 3 meses − lo de julio)
    df = _excel(pg.generar_asiento_provision(db, db.empresa_id, "09-2026"))
    assert _totales(df, "621201") == (1090.0, 0.0)     # 3×545 − 545
    assert pg.provisiones_por_dni(db, db.empresa_id, "JUL-DIC", 2026)[DNI_A] == (1500.0, 135.0)


def test_provision_sin_cuentas_avisa_cuales_faltan(db):
    _config(db, cuenta_gratificacion_gasto="", cuenta_gratificacion_por_pagar="")
    _planilla(db, "07-2026")
    with pytest.raises(AsientoContableError) as ei:
        pg.generar_asiento_provision(db, db.empresa_id, "07-2026")
    assert any("Gasto" in c for c in ei.value.cuentas_faltantes)
    assert any("Por Pagar" in c for c in ei.value.cuentas_faltantes)
    assert db.query(m.ProvisionGratificacion).count() == 0       # no se registra nada si falla


# ── Asiento de planilla: pago de julio / diciembre ───────────────────────────────

def test_julio_2026_sin_provision_reconoce_todo_el_pago_como_gasto(db):
    """El 'ajuste en julio': el semestre ENE-JUN nunca se provisionó."""
    _config(db)
    _planilla(db, "07-2026", con_grati=3000.0, con_bono=270.0)
    df = _excel(generar_asiento_planilla(db, db.empresa_id, "07-2026"))
    assert _totales(df, "621201") == (3270.0, 0.0)             # gasto por todo lo pagado
    assert _totales(df, "415101") == (0.0, 0.0)                # sin provisión que cancelar
    assert _cuadra(df)


def test_diciembre_cancela_lo_provisionado_y_solo_la_diferencia_es_gasto(db):
    _config(db)
    for mes in ("07", "08", "09", "10", "11"):
        _libro(db, f"{mes}-2026", 500.0, 45.0)                  # 5 meses × 545 = 2725
    _planilla(db, "12-2026", con_grati=3000.0, con_bono=270.0)
    df = _excel(generar_asiento_planilla(db, db.empresa_id, "12-2026"))
    assert _totales(df, "415101") == (2725.0, 0.0)             # se cancela la provisión
    assert _totales(df, "621201") == (545.0, 0.0)              # solo el mes que faltaba (3270 − 2725)
    assert _cuadra(df)


def test_diciembre_con_provision_completa_no_genera_gasto_extra(db):
    _config(db)
    for mes in ("07", "08", "09", "10", "11", "12"):
        _libro(db, f"{mes}-2026", 500.0, 45.0)                  # 6 meses = 3270 = lo pagado
    _planilla(db, "12-2026", con_grati=3000.0, con_bono=270.0)
    df = _excel(generar_asiento_planilla(db, db.empresa_id, "12-2026"))
    assert _totales(df, "415101") == (3270.0, 0.0)
    assert _totales(df, "621201") == (0.0, 0.0)
    assert _cuadra(df)


def test_diciembre_si_la_provision_excedio_lo_pagado_se_recupera_el_gasto(db):
    _config(db)
    for mes in ("07", "08", "09", "10", "11", "12"):
        _libro(db, f"{mes}-2026", 600.0, 54.0)                  # 3924 provisionado > 3270 pagado
    _planilla(db, "12-2026", con_grati=3000.0, con_bono=270.0)
    df = _excel(generar_asiento_planilla(db, db.empresa_id, "12-2026"))
    assert _totales(df, "415101") == (3924.0, 0.0)
    assert _totales(df, "621201") == (0.0, 654.0)              # recuperación de gasto
    assert _cuadra(df)


def test_asiento_de_pago_avisa_si_falta_la_cuenta_de_gratificacion(db):
    _config(db, cuenta_gratificacion_gasto="")
    _planilla(db, "07-2026", con_grati=3000.0, con_bono=270.0)
    with pytest.raises(AsientoContableError) as ei:
        generar_asiento_planilla(db, db.empresa_id, "07-2026")
    assert any("Gratificación — Gasto" in c for c in ei.value.cuentas_faltantes)


def test_meses_sin_gratificacion_no_piden_cuentas_de_gratificacion(db):
    _config(db, cuenta_gratificacion_gasto="", cuenta_gratificacion_por_pagar="")
    _planilla(db, "09-2026")
    df = _excel(generar_asiento_planilla(db, db.empresa_id, "09-2026"))
    assert _cuadra(df)


# ── Liquidación por cese ─────────────────────────────────────────────────────────

def _liquidacion(db):
    liq = m.LiquidacionCese(
        empresa_id=db.empresa_id, trabajador_id=db.id_a, estado="APROBADA",
        fecha_ingreso_snapshot=datetime.date(2020, 1, 1), fecha_cese_snapshot=datetime.date(2026, 10, 15),
        sueldo_base_snapshot=3000.0, periodo_grati_ref="JUL-DIC 2026",
        monto_grati_trunca=1000.0, monto_bono_9=90.0, total_bruto=1090.0, total_neto=1090.0,
    )
    db.add(liq)
    db.commit()
    return liq


def test_liquidacion_sin_provision_mantiene_el_comportamiento_de_siempre(db):
    _config(db)
    liq = _liquidacion(db)
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "621201") == (1090.0, 0.0)
    assert _totales(df, "415101") == (0.0, 1090.0)
    assert _cuadra(df)


def test_liquidacion_descuenta_lo_provisionado_en_el_semestre(db):
    _config(db)
    for mes in ("07", "08", "09"):
        _libro(db, f"{mes}-2026", 300.0, 27.0)                  # 981 provisionado
    liq = _liquidacion(db)                                       # trunca 1090
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "415101") == (981.0, 1090.0)           # cancela 981 y reconoce el pasivo neto 1090
    assert _totales(df, "621201") == (109.0, 0.0)              # solo la diferencia es gasto
    assert _cuadra(df)


def test_liquidacion_si_la_provision_excedio_recupera_gasto(db):
    _config(db)
    for mes in ("07", "08", "09"):
        _libro(db, f"{mes}-2026", 500.0, 45.0)                  # 1635 provisionado > 1090
    liq = _liquidacion(db)
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "621201") == (0.0, 545.0)
    assert _cuadra(df)


def test_liquidacion_ignora_provisiones_de_otro_semestre(db):
    _config(db)
    _libro(db, "05-2026", 999.0, 99.0, sem="ENE-JUN-2026")      # semestre distinto
    liq = _liquidacion(db)
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "621201") == (1090.0, 0.0)
    assert _cuadra(df)


def test_semestre_desde_la_referencia_de_la_liquidacion():
    assert pg.semestre_desde_ref("JUL-DIC 2026", datetime.date(2026, 10, 15)) == ("JUL-DIC", 2026)
    assert pg.semestre_desde_ref("ENE-JUN 2027", datetime.date(2027, 3, 1)) == ("ENE-JUN", 2027)
    assert pg.semestre_desde_ref(None, datetime.date(2026, 3, 1)) == ("ENE-JUN", 2026)   # respaldo por fecha
    assert pg.semestre_pagado_en(7) == "ENE-JUN" and pg.semestre_pagado_en(12) == "JUL-DIC"
    assert pg.semestre_pagado_en(5) is None
