"""
Liquidación por cese en julio con la gratificación enero–junio SIN cargar: se detecta, se avisa y se
paga solo si el usuario lo confirma; el asiento y el PLAME la tratan como gratificación (0301).

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

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test_grati_ant.db")

from infrastructure.database import connection  # noqa: E402

if not str(connection.engine.url).startswith("sqlite"):
    pytest.skip("El motor no es SQLite: se omite para no tocar una base real.", allow_module_level=True)

import pandas as pd  # noqa: E402
from infrastructure.database import models as m  # noqa: E402
from core.use_cases.calculo_liquidacion_cese import (  # noqa: E402
    calcular_liquidacion, grati_anterior_pendiente, generar_liquidacion_borrador_automatica,
)
from core.use_cases.generador_asiento_liquidacion import generar_asiento_liquidacion  # noqa: E402
from core.use_cases.exportador_plame import generar_txt_e18  # noqa: E402

DNI = "11111111"

CUENTAS = dict(
    cuenta_essalud_gasto="627101", cuenta_essalud_pasivo="403101", cuenta_onp="401701",
    cuenta_retencion_5ta="401111", cuenta_remuneraciones_por_pagar="411101",
    cuenta_gratificacion_gasto="621201", cuenta_gratificacion_por_pagar="415101",
)


def _excel(buf):
    return pd.read_excel(io.BytesIO(buf.getvalue()), dtype={"Cuenta": str})


def _totales(df, cuenta):
    f = df[df["Cuenta"] == cuenta]
    return round(f["Monto Debe"].sum(), 2), round(f["Monto Haber"].sum(), 2)


def _cuadra(df):
    return round(df["Monto Debe"].sum() - df["Monto Haber"].sum(), 2) == 0


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
                       fecha_ingreso=datetime.date(2025, 1, 1), situacion="ACTIVO"))
    s.add(m.ParametroLegal(
        empresa_id=emp.id, periodo_key="01-2026", rmv=1130.0, uit=5350.0, tasa_essalud=9.0, tasa_eps=2.25,
        tasa_onp=13.0, tope_afp=12000.0,
        h_ap=10.0, h_pr=1.4, h_fl=1.5, h_mx=0.0, i_ap=10.0, i_pr=1.4, i_fl=1.5, i_mx=0.0,
        p_ap=10.0, p_pr=1.4, p_fl=1.5, p_mx=0.0, pr_ap=10.0, pr_pr=1.4, pr_fl=1.5, pr_mx=0.0))
    s.add(m.ConfiguracionContable(empresa_id=emp.id, **CUENTAS))
    s.commit()
    s.t = s.query(m.Trabajador).filter_by(num_doc=DNI).one()
    yield s
    s.close()


def _cargar_grati_julio(db, monto=3000.0):
    db.add(m.VariablesMes(empresa_id=db.empresa_id, trabajador_id=db.t.id, periodo_key="07-2026",
                          conceptos_json=json.dumps({"GRATIFICACION (JUL/DIC)": monto})))
    db.commit()


# ── Detección ────────────────────────────────────────────────────────────────────

def test_cese_en_julio_sin_gratificacion_cargada_se_detecta(db):
    r = grati_anterior_pendiente(db, db.empresa_id, db.t, datetime.date(2026, 7, 10), "Régimen General")
    assert r["periodo_ref"] == "ENE-JUN 2026" and r["meses"] == 6
    assert r["monto_grati"] == 3000.0 and r["bono_9"] == 270.0 and r["total"] == 3270.0


def test_no_aparece_si_la_gratificacion_ya_esta_cargada_en_planilla(db):
    _cargar_grati_julio(db)
    assert grati_anterior_pendiente(db, db.empresa_id, db.t, datetime.date(2026, 7, 10), "Régimen General") is None


def test_no_aparece_si_el_cese_no_es_en_julio(db):
    assert grati_anterior_pendiente(db, db.empresa_id, db.t, datetime.date(2026, 8, 10), "Régimen General") is None
    assert grati_anterior_pendiente(db, db.empresa_id, db.t, datetime.date(2026, 6, 30), "Régimen General") is None


def test_no_aparece_si_ingreso_despues_de_junio(db):
    db.t.fecha_ingreso = datetime.date(2026, 7, 1)
    db.commit()
    assert grati_anterior_pendiente(db, db.empresa_id, db.t, datetime.date(2026, 7, 20), "Régimen General") is None


def test_con_asignacion_familiar_la_base_la_incluye(db):
    db.t.asig_fam = True
    db.commit()
    r = grati_anterior_pendiente(db, db.empresa_id, db.t, datetime.date(2026, 7, 10), "Régimen General")
    assert r["base_computable"] == 3113.0 and r["monto_grati"] == 3113.0            # 3000 + 10 % de la RMV


# ── Inclusión con casilla ────────────────────────────────────────────────────────

def test_sin_confirmar_se_avisa_pero_no_se_paga_nada(db):
    liq = calcular_liquidacion(db, db.t, db.empresa_id, datetime.date(2026, 7, 10), "Régimen General")
    assert liq["grati_anterior_pendiente"]["total"] == 3270.0           # detectada: la pantalla la avisa
    assert liq["incluye_grati_anterior"] is False
    assert liq["monto_grati_anterior"] == 0.0 and liq["monto_bono_anterior"] == 0.0
    assert liq["periodo_grati_anterior_ref"] is None


def test_confirmada_se_suma_al_bruto_y_a_la_base_de_5ta(db):
    fc = datetime.date(2026, 7, 10)
    sin = calcular_liquidacion(db, db.t, db.empresa_id, fc, "Régimen General")
    con = calcular_liquidacion(db, db.t, db.empresa_id, fc, "Régimen General", incluir_grati_anterior=True)
    assert con["incluye_grati_anterior"] is True
    assert con["monto_grati_anterior"] == 3000.0 and con["monto_bono_anterior"] == 270.0
    assert con["periodo_grati_anterior_ref"] == "ENE-JUN 2026"
    assert round(con["total_bruto"] - sin["total_bruto"], 2) == 3270.0
    assert con["monto_retencion_5ta"] >= sin["monto_retencion_5ta"]     # es remuneración afecta a 5ta


def test_si_ya_estaba_cargada_incluir_no_la_paga_dos_veces(db):
    _cargar_grati_julio(db)
    fc = datetime.date(2026, 7, 10)
    sin = calcular_liquidacion(db, db.t, db.empresa_id, fc, "Régimen General")
    con = calcular_liquidacion(db, db.t, db.empresa_id, fc, "Régimen General", incluir_grati_anterior=True)
    assert con["grati_anterior_pendiente"] is None and con["monto_grati_anterior"] == 0.0
    assert con["total_bruto"] == sin["total_bruto"]


def test_el_borrador_automatico_no_incluye_la_pendiente_sin_confirmacion(db):
    liq = generar_liquidacion_borrador_automatica(
        db, db.t, db.empresa_id, datetime.date(2026, 7, 10), "Régimen General")
    db.commit()
    assert liq.monto_grati_anterior == 0.0 and liq.monto_bono_anterior == 0.0


# ── Asiento contable ─────────────────────────────────────────────────────────────

def _liquidacion(db, anio=2026, prov_ref=None):
    liq = m.LiquidacionCese(
        empresa_id=db.empresa_id, trabajador_id=db.t.id, estado="APROBADA",
        fecha_ingreso_snapshot=datetime.date(2025, 1, 1), fecha_cese_snapshot=datetime.date(anio, 7, 10),
        sueldo_base_snapshot=3000.0, monto_grati_anterior=3000.0, monto_bono_anterior=270.0,
        periodo_grati_anterior_ref=prov_ref or f"ENE-JUN {anio}", total_bruto=3270.0, total_neto=3270.0,
    )
    db.add(liq)
    db.commit()
    return liq


def test_asiento_sin_provision_reconoce_todo_como_gasto(db):
    liq = _liquidacion(db)
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "621201") == (3270.0, 0.0)
    assert _totales(df, "415101") == (0.0, 3270.0)
    assert _cuadra(df)


def test_asiento_descuenta_lo_provisionado_del_semestre_enero_junio(db):
    """Desde 2027 el semestre ENE-JUN sí se provisiona: la pendiente cancela ese pasivo."""
    db.add(m.ProvisionGratificacion(empresa_id=db.empresa_id, trabajador_id=db.t.id, periodo_key="05-2027",
                                    semestre="ENE-JUN-2027", monto_grati=2000.0, monto_bono=180.0))
    db.commit()
    liq = _liquidacion(db, anio=2027)
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "415101") == (2180.0, 3270.0)                 # cancela lo provisionado
    assert _totales(df, "621201") == (1090.0, 0.0)                    # solo la diferencia es gasto
    assert _cuadra(df)


# ── PLAME ────────────────────────────────────────────────────────────────────────

def test_plame_declara_la_gratificacion_pendiente_con_0301_y_un_solo_0303(db):
    _liquidacion(db)
    rem = generar_txt_e18(db, db.empresa_id, "07-2026")
    assert f"01|{DNI}|0301|3000.00|3000.00|" in rem.splitlines()
    lineas_bono = [l for l in rem.splitlines() if "|0303|" in l]
    assert len(lineas_bono) == 1 and "270.00" in lineas_bono[0]       # una sola línea de bono por trabajador


# ── Cese en ENERO: gratificación de julio–diciembre del año anterior sin cargar ───

def test_cese_en_enero_detecta_la_gratificacion_de_diciembre_sin_cargar(db):
    r = grati_anterior_pendiente(db, db.empresa_id, db.t, datetime.date(2027, 1, 15), "Régimen General")
    assert r["periodo_ref"] == "JUL-DIC 2026" and r["meses"] == 6
    assert r["monto_grati"] == 3000.0 and r["bono_9"] == 270.0 and r["total"] == 3270.0


def test_enero_no_aparece_si_la_gratificacion_de_diciembre_ya_se_cargo(db):
    db.add(m.VariablesMes(empresa_id=db.empresa_id, trabajador_id=db.t.id, periodo_key="12-2026",
                          conceptos_json=json.dumps({"GRATIFICACION (JUL/DIC)": 3000.0})))
    db.commit()
    assert grati_anterior_pendiente(db, db.empresa_id, db.t, datetime.date(2027, 1, 15), "Régimen General") is None


def test_enero_no_aparece_si_ingreso_despues_de_diciembre(db):
    db.t.fecha_ingreso = datetime.date(2027, 1, 2)
    db.commit()
    assert grati_anterior_pendiente(db, db.empresa_id, db.t, datetime.date(2027, 1, 20), "Régimen General") is None


def test_solo_julio_y_enero_son_meses_de_gratificacion_pendiente(db):
    for mes in (2, 3, 4, 5, 6, 8, 9, 10, 11, 12):
        assert grati_anterior_pendiente(db, db.empresa_id, db.t, datetime.date(2026, mes, 10), "Régimen General") is None


def test_enero_confirmada_se_suma_con_su_semestre(db):
    fc = datetime.date(2027, 1, 15)
    sin = calcular_liquidacion(db, db.t, db.empresa_id, fc, "Régimen General")
    con = calcular_liquidacion(db, db.t, db.empresa_id, fc, "Régimen General", incluir_grati_anterior=True)
    assert sin["monto_grati_anterior"] == 0.0 and sin["grati_anterior_pendiente"]["periodo_ref"] == "JUL-DIC 2026"
    assert con["periodo_grati_anterior_ref"] == "JUL-DIC 2026"
    assert round(con["total_bruto"] - sin["total_bruto"], 2) == 3270.0


def test_enero_el_asiento_cancela_lo_provisionado_de_julio_a_noviembre(db):
    for mes in ("07", "08", "09", "10", "11"):
        db.add(m.ProvisionGratificacion(empresa_id=db.empresa_id, trabajador_id=db.t.id, periodo_key=f"{mes}-2026",
                                        semestre="JUL-DIC-2026", monto_grati=500.0, monto_bono=45.0))
    db.commit()                                                          # 5 × 545 = 2725 provisionado
    liq = m.LiquidacionCese(
        empresa_id=db.empresa_id, trabajador_id=db.t.id, estado="APROBADA",
        fecha_ingreso_snapshot=datetime.date(2025, 1, 1), fecha_cese_snapshot=datetime.date(2027, 1, 15),
        sueldo_base_snapshot=3000.0, monto_grati_anterior=3000.0, monto_bono_anterior=270.0,
        periodo_grati_anterior_ref="JUL-DIC 2026", total_bruto=3270.0, total_neto=3270.0,
    )
    db.add(liq)
    db.commit()
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "415101") == (2725.0, 3270.0)                 # cancela lo provisionado de JUL-DIC 2026
    assert _totales(df, "621201") == (545.0, 0.0)                     # solo la diferencia (diciembre) es gasto
    assert _cuadra(df)


def test_enero_plame_usa_el_codigo_0302_de_la_gratificacion_de_diciembre(db):
    db.add(m.LiquidacionCese(
        empresa_id=db.empresa_id, trabajador_id=db.t.id, estado="APROBADA",
        fecha_ingreso_snapshot=datetime.date(2025, 1, 1), fecha_cese_snapshot=datetime.date(2027, 1, 15),
        sueldo_base_snapshot=3000.0, monto_grati_anterior=3000.0, monto_bono_anterior=270.0,
        periodo_grati_anterior_ref="JUL-DIC 2026", total_bruto=3270.0, total_neto=3270.0))
    db.commit()
    rem = generar_txt_e18(db, db.empresa_id, "01-2027")
    assert f"01|{DNI}|0302|3000.00|3000.00|" in rem.splitlines()
    assert "|0301|" not in rem
