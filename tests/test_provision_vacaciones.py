"""
Provisión de vacaciones (libro de saldos), cancelación en planilla y liquidación por cese; y la
gratificación ya pagada en planilla (liquidación) / diciembre sin provisión aparte.

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

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test_vacaciones.db")

from infrastructure.database import connection  # noqa: E402

if not str(connection.engine.url).startswith("sqlite"):
    pytest.skip("El motor no es SQLite: se omite para no tocar una base real.", allow_module_level=True)

import pandas as pd  # noqa: E402
from infrastructure.database import models as m  # noqa: E402
from core.use_cases import provision_vacaciones as pv  # noqa: E402
from core.use_cases import provision_gratificacion as pg  # noqa: E402
from core.use_cases.generador_asiento_contable import generar_asiento_planilla, AsientoContableError  # noqa: E402
from core.use_cases.generador_asiento_liquidacion import generar_asiento_liquidacion  # noqa: E402
from core.use_cases.calculo_liquidacion_cese import grati_ya_pagada_en_planilla  # noqa: E402

DNI = "11111111"      # ingresó 01/01/2026, sueldo 3000 -> 100 por día, 2.5 días devengados por mes

CUENTAS = dict(
    cuenta_essalud_gasto="627101", cuenta_essalud_pasivo="403101", cuenta_onp="401701",
    cuenta_retencion_5ta="401111", cuenta_remuneraciones_por_pagar="411101",
    cuenta_descanso_vacacional="621301", cuenta_vacaciones_por_pagar="415201",
    cuenta_gratificacion_gasto="621201", cuenta_gratificacion_por_pagar="415101",
)


def _excel(buf):
    return pd.read_excel(io.BytesIO(buf.getvalue()), dtype={"Cuenta": str})


def _totales(df, cuenta):
    f = df[df["Cuenta"] == cuenta]
    return round(f["Monto Debe"].sum(), 2), round(f["Monto Haber"].sum(), 2)


def _cuadra(df):
    return round(df["Monto Debe"].sum() - df["Monto Haber"].sum(), 2) == 0


def _planilla(db, periodo, pago_vacaciones=0.0, estado="CERRADA"):
    ingresos = {"Sueldo Base (30 días)": 3000.0}
    if pago_vacaciones:
        ingresos["Descanso Vacacional"] = pago_vacaciones
    aud = {DNI: {"nombres": "TRAB 1", "ingresos": ingresos, "descuentos": {},
                 "sueldo_base_nominal": 3000.0, "quinta": {"retencion": 0}}}
    fila = {"DNI": DNI, "Apellidos y Nombres": "TRAB 1", "Sist. Pensión": "ONP", "ONP (13%)": 390.0,
            "AFP Aporte": 0.0, "AFP Seguro": 0.0, "AFP Comis.": 0.0, "Ret. 5ta Cat.": 0.0,
            "Aporte Seg. Social": 270.0}
    db.add(m.PlanillaMensual(empresa_id=db.empresa_id, periodo_key=periodo, estado=estado,
                             resultado_json=pd.DataFrame([fila]).to_json(orient="records"),
                             auditoria_json=json.dumps(aud)))
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
                       sueldo_base=3000.0, tipo_contrato="PLANILLA", sistema_pension="ONP", eps=False,
                       fecha_ingreso=datetime.date(2026, 1, 1), situacion="ACTIVO", dias_vacaciones_anuales=30))
    s.add(m.Concepto(empresa_id=emp.id, nombre="SUELDO BASICO", tipo="INGRESO", cuenta_contable="621101"))
    s.commit()
    s.tid = s.query(m.Trabajador).filter_by(num_doc=DNI).one().id
    yield s
    s.close()


def _config(db, **extra):
    db.add(m.ConfiguracionContable(empresa_id=db.empresa_id, **{**CUENTAS, **extra}))
    db.commit()


def _vacaciones_gozadas(db, inicio, dias):
    db.add(m.RegistroVacaciones(trabajador_id=db.tid, fecha_inicio=inicio, fecha_fin=inicio + datetime.timedelta(days=dias - 1),
                                dias_gozados=dias, dias_vendidos=0, estado="APROBADO"))
    db.commit()


def _libro(db, periodo, saldo, provision=0.0, cancelado=0.0):
    db.add(m.ProvisionVacaciones(empresa_id=db.empresa_id, trabajador_id=db.tid, periodo_key=periodo,
                                 saldo=saldo, monto_provision=provision, cancelado=cancelado))
    db.commit()


# ── Provisión del mes ────────────────────────────────────────────────────────────

def test_julio_provisiona_de_golpe_todo_el_saldo_acumulado(db):
    """El 'ajuste en julio': 7 meses devengados = 17.5 días × S/ 100."""
    _planilla(db, "07-2026")
    f = pv.calcular_provision_mes(db, db.empresa_id, "07-2026")[0]
    assert f["dias_saldo"] == 17.5 and f["remuneracion_diaria"] == 100.0
    assert f["saldo_previo"] == 0.0 and f["objetivo"] == 1750.0 and f["delta"] == 1750.0


def _antiguo(db, ingreso=datetime.date(2025, 1, 1)):
    """El trabajador ingresó antes del corte: al 31/12/2025 ya tenía 30 días devengados (12 meses)."""
    t = db.query(m.Trabajador).filter_by(id=db.tid).one()
    t.fecha_ingreso = ingreso
    db.commit()


def test_julio_no_provisiona_el_saldo_de_anios_anteriores(db):
    """Ya está provisionado en la contabilidad: solo se reconoce el devengo ene-jul 2026 (17.5 días)."""
    _antiguo(db)
    _planilla(db, "07-2026")
    f = pv.calcular_provision_mes(db, db.empresa_id, "07-2026")[0]
    assert f["dias_saldo"] == 17.5 and f["objetivo"] == 1750.0 and f["delta"] == 1750.0


def test_dias_gozados_consumen_primero_el_saldo_viejo(db):
    """Con 30 días viejos, gozar 10 en 2026 no reduce lo provisionado (sale del saldo viejo)."""
    _antiguo(db)
    _vacaciones_gozadas(db, datetime.date(2026, 3, 2), 10)
    _planilla(db, "07-2026")
    assert pv.calcular_provision_mes(db, db.empresa_id, "07-2026")[0]["dias_saldo"] == 17.5


def test_gozar_mas_que_el_saldo_viejo_resta_del_devengo_nuevo(db):
    """30 viejos + 17.5 devengados − 40 gozados = 7.5 de saldo; el viejo se agotó, queda devengo nuevo."""
    _antiguo(db)
    _vacaciones_gozadas(db, datetime.date(2026, 3, 2), 40)
    _planilla(db, "07-2026")
    assert pv.calcular_provision_mes(db, db.empresa_id, "07-2026")[0]["dias_saldo"] == 7.5


def test_agosto_provisiona_el_devengo_del_mes(db):
    _config(db)
    _planilla(db, "07-2026")
    _planilla(db, "08-2026")
    pv.generar_asiento_provision(db, db.empresa_id, "07-2026")
    f = pv.calcular_provision_mes(db, db.empresa_id, "08-2026")[0]
    assert f["saldo_previo"] == 1750.0 and f["objetivo"] == 2000.0 and f["delta"] == 250.0   # 2.5 días


def test_un_registro_de_vacaciones_posterior_no_altera_un_mes_ya_cerrado(db):
    _planilla(db, "07-2026")
    _vacaciones_gozadas(db, datetime.date(2026, 10, 5), 10)        # gozadas en octubre
    assert pv.calcular_provision_mes(db, db.empresa_id, "07-2026")[0]["objetivo"] == 1750.0


def test_asiento_de_provision_cuadra_y_registra_el_saldo(db):
    _config(db)
    _planilla(db, "07-2026")
    df = _excel(pv.generar_asiento_provision(db, db.empresa_id, "07-2026"))
    assert _totales(df, "621301") == (1750.0, 0.0)
    assert _totales(df, "415201") == (0.0, 1750.0)
    assert _cuadra(df)
    assert pv.saldo_vigente_trabajador(db, db.empresa_id, db.tid) == 1750.0


def test_regenerar_el_mismo_mes_reemplaza_y_no_duplica(db):
    _config(db)
    _planilla(db, "07-2026")
    pv.generar_asiento_provision(db, db.empresa_id, "07-2026")
    pv.generar_asiento_provision(db, db.empresa_id, "07-2026")
    assert db.query(m.ProvisionVacaciones).count() == 1
    assert pv.saldo_vigente_trabajador(db, db.empresa_id, db.tid) == 1750.0


def test_vacaciones_gozadas_se_cancelan_contra_el_pasivo_y_no_son_gasto_otra_vez(db):
    _config(db)
    _planilla(db, "07-2026")
    _planilla(db, "08-2026")
    _planilla(db, "09-2026", pago_vacaciones=1000.0)               # 10 días × 100
    _vacaciones_gozadas(db, datetime.date(2026, 9, 1), 10)
    pv.generar_asiento_provision(db, db.empresa_id, "07-2026")
    pv.generar_asiento_provision(db, db.empresa_id, "08-2026")
    f = pv.calcular_provision_mes(db, db.empresa_id, "09-2026")[0]
    assert f["cancelado"] == 1000.0 and f["objetivo"] == 1250.0     # (22.5 − 10) días
    assert f["delta"] == 250.0                                       # solo el devengo del mes

    # asiento de planilla de septiembre: las vacaciones gozadas cancelan el pasivo
    df = _excel(generar_asiento_planilla(db, db.empresa_id, "09-2026"))
    assert _totales(df, "415201") == (1000.0, 0.0)
    assert _totales(df, "621301") == (0.0, 0.0)                      # sin gasto extra
    assert _cuadra(df)


def test_si_lo_gozado_supera_el_saldo_provisionado_el_resto_es_gasto(db):
    _config(db)
    _libro(db, "08-2026", saldo=400.0)                                # poco saldo provisionado
    _planilla(db, "09-2026", pago_vacaciones=1000.0)
    df = _excel(generar_asiento_planilla(db, db.empresa_id, "09-2026"))
    assert _totales(df, "415201") == (400.0, 0.0)
    assert _totales(df, "621301") == (600.0, 0.0)
    assert _cuadra(df)


def test_sin_libro_las_vacaciones_gozadas_siguen_siendo_gasto_como_siempre(db):
    _config(db)
    _planilla(db, "09-2026", pago_vacaciones=1000.0)
    df = _excel(generar_asiento_planilla(db, db.empresa_id, "09-2026"))
    assert _totales(df, "621301") == (1000.0, 0.0)
    assert _totales(df, "415201") == (0.0, 0.0)
    assert _cuadra(df)


def test_orden_estricto_el_mes_anterior_debe_estar_registrado(db):
    _config(db)
    _planilla(db, "07-2026")
    _planilla(db, "08-2026")
    _planilla(db, "09-2026")
    pv.generar_asiento_provision(db, db.empresa_id, "07-2026")
    with pytest.raises(AsientoContableError, match="Registre primero"):
        pv.generar_asiento_provision(db, db.empresa_id, "09-2026")      # falta agosto
    pv.generar_asiento_provision(db, db.empresa_id, "08-2026")
    with pytest.raises(AsientoContableError, match="posteriores"):
        pv.generar_asiento_provision(db, db.empresa_id, "07-2026")      # ya hay agosto


def test_el_asiento_de_planilla_exige_el_mes_anterior_si_hay_vacaciones_gozadas(db):
    _config(db)
    _libro(db, "07-2026", saldo=1750.0)                                  # libro en uso, falta agosto
    _planilla(db, "09-2026", pago_vacaciones=1000.0)
    with pytest.raises(AsientoContableError, match="Falta registrar la provisión de vacaciones de 08-2026"):
        generar_asiento_planilla(db, db.empresa_id, "09-2026")


def test_antes_del_corte_no_se_provisiona(db):
    _planilla(db, "06-2026")
    with pytest.raises(AsientoContableError, match="julio 2026"):
        pv.calcular_provision_mes(db, db.empresa_id, "06-2026")


def test_provision_sin_cuentas_avisa_y_no_registra_nada(db):
    _config(db, cuenta_vacaciones_por_pagar="")
    _planilla(db, "07-2026")
    with pytest.raises(AsientoContableError) as ei:
        pv.generar_asiento_provision(db, db.empresa_id, "07-2026")
    assert any("Vacaciones Por Pagar" in c for c in ei.value.cuentas_faltantes)
    assert db.query(m.ProvisionVacaciones).count() == 0


# ── Liquidación por cese: vacaciones truncas ─────────────────────────────────────

def _liquidacion(db, vac_truncas):
    liq = m.LiquidacionCese(
        empresa_id=db.empresa_id, trabajador_id=db.tid, estado="APROBADA",
        fecha_ingreso_snapshot=datetime.date(2026, 1, 1), fecha_cese_snapshot=datetime.date(2026, 10, 15),
        sueldo_base_snapshot=3000.0, monto_vacaciones_truncas=vac_truncas,
        total_bruto=vac_truncas, total_neto=vac_truncas,
    )
    db.add(liq)
    db.commit()
    return liq


def test_liquidacion_sin_libro_mantiene_el_comportamiento_de_siempre(db):
    _config(db)
    liq = _liquidacion(db, 2000.0)
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "621301") == (2000.0, 0.0)
    assert _totales(df, "415201") == (0.0, 2000.0)
    assert _cuadra(df)


def test_liquidacion_descuenta_el_saldo_provisionado(db):
    _config(db)
    _libro(db, "09-2026", saldo=1800.0)
    liq = _liquidacion(db, 2000.0)
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "415201") == (1800.0, 2000.0)                    # cancela lo provisionado
    assert _totales(df, "621301") == (200.0, 0.0)                        # solo la diferencia es gasto
    assert _cuadra(df)


def test_liquidacion_si_el_saldo_excedio_se_recupera_gasto(db):
    _config(db)
    _libro(db, "09-2026", saldo=2300.0)
    liq = _liquidacion(db, 2000.0)
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "621301") == (0.0, 300.0)
    assert _cuadra(df)


def test_liquidacion_cancela_tambien_el_saldo_provisionado_antes_del_corte(db):
    """30 días de 2025 (ya provisionados en su contabilidad) + 10 de 2026 en el libro: todo es pasivo, 0 gasto."""
    _config(db)
    _antiguo(db)
    _libro(db, "09-2026", saldo=1000.0)
    liq = _liquidacion(db, 4000.0)
    liq.dias_vacaciones_pendientes = 40.0                                 # 100 por día
    db.commit()
    df = _excel(generar_asiento_liquidacion(db, db.empresa_id, liq.id))
    assert _totales(df, "415201") == (4000.0, 4000.0)
    assert df[df["Cuenta"] == "621301"].empty
    assert _cuadra(df)


def test_liquidacion_usa_el_ultimo_saldo_registrado(db):
    _config(db)
    _libro(db, "07-2026", saldo=1750.0)
    _libro(db, "08-2026", saldo=2000.0)
    assert pv.saldo_vigente_trabajador(db, db.empresa_id, db.tid) == 2000.0


# ── Gratificación: ya pagada en planilla y diciembre ─────────────────────────────

def test_grati_ya_pagada_en_planilla_se_detecta_por_el_mes_de_pago(db):
    db.add(m.VariablesMes(empresa_id=db.empresa_id, trabajador_id=db.tid, periodo_key="12-2026",
                          conceptos_json=json.dumps({"GRATIFICACION (JUL/DIC)": 3000.0})))
    db.commit()
    assert grati_ya_pagada_en_planilla(db, db.empresa_id, db.tid, "JUL-DIC", 2026) == 3000.0
    assert grati_ya_pagada_en_planilla(db, db.empresa_id, db.tid, "ENE-JUN", 2026) == 0.0   # paga en 07-2026
    assert grati_ya_pagada_en_planilla(db, db.empresa_id, db.tid, "JUL-DIC", 2027) == 0.0


def test_diciembre_no_se_provisiona_aparte(db):
    _planilla(db, "12-2026")
    with pytest.raises(AsientoContableError, match="diciembre"):
        pg.calcular_provision_mes(db, db.empresa_id, "12-2026")
    assert not pg.es_provisionable("12-2026") and pg.es_provisionable("11-2026")


def test_calcular_liquidacion_no_paga_de_nuevo_la_gratificacion_ya_pagada(db):
    """Cese a fines de diciembre: si la gratificación de diciembre ya está en planilla, la trunca es 0."""
    from core.use_cases.calculo_liquidacion_cese import calcular_liquidacion
    db.add(m.ParametroLegal(
        empresa_id=db.empresa_id, periodo_key="12-2026", rmv=1130.0, uit=5350.0, tasa_essalud=9.0, tasa_eps=2.25,
        tasa_onp=13.0, tope_afp=12000.0,
        h_ap=10.0, h_pr=1.4, h_fl=1.5, h_mx=0.0, i_ap=10.0, i_pr=1.4, i_fl=1.5, i_mx=0.0,
        p_ap=10.0, p_pr=1.4, p_fl=1.5, p_mx=0.0, pr_ap=10.0, pr_pr=1.4, pr_fl=1.5, pr_mx=0.0))
    db.commit()
    t = db.query(m.Trabajador).filter_by(id=db.tid).one()
    fc = datetime.date(2026, 12, 28)

    antes = calcular_liquidacion(db, t, db.empresa_id, fc, "Régimen General")
    assert antes["monto_grati_trunca"] == 2500.0 and antes["monto_bono_9"] == 225.0     # 5/6 de 3000 + 9 %
    assert antes["grati_ya_pagada_planilla"] == 0.0

    db.add(m.VariablesMes(empresa_id=db.empresa_id, trabajador_id=db.tid, periodo_key="12-2026",
                          conceptos_json=json.dumps({"GRATIFICACION (JUL/DIC)": 3000.0})))
    db.commit()
    despues = calcular_liquidacion(db, t, db.empresa_id, fc, "Régimen General")
    assert despues["monto_grati_trunca"] == 0.0 and despues["monto_bono_9"] == 0.0
    assert despues["grati_ya_pagada_planilla"] == 3000.0
    assert round(antes["total_bruto"] - despues["total_bruto"], 2) == 2725.0           # no se paga dos veces
