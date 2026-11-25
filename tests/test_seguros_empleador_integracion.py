"""
Integración de Vida Ley / SCTR: auditoría de planilla -> .REM de PLAME y asiento contable.

Usa una SQLite temporal. SEGURIDAD: el .env del proyecto apunta a la base real, por eso
este módulo se salta por completo si el motor de SQLAlchemy NO es SQLite (por ejemplo si
otro test importó `connection` antes que este archivo). Ejecútese solo o con el resto:
    pytest tests/test_seguros_empleador_integracion.py
"""
import io
import json
import os
import tempfile

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

# load_dotenv() no pisa variables ya definidas: esto gana sobre el .env del proyecto.
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test_seguros.db")

from infrastructure.database import connection  # noqa: E402

if not str(connection.engine.url).startswith("sqlite"):
    pytest.skip("El motor no es SQLite: se omite para no tocar una base real.", allow_module_level=True)

import pandas as pd  # noqa: E402
from infrastructure.database import models as m  # noqa: E402
from core.use_cases.exportador_plame import generar_txt_e18  # noqa: E402
from core.use_cases.generador_asiento_contable import generar_asiento_planilla, AsientoContableError  # noqa: E402

PERIODO = "03-2026"
DNI = "12345678"


def _auditoria(aportes):
    return {DNI: {
        "ingresos": {"Sueldo Base (30 días)": 2000.0},
        "descuentos": {},
        "detalle_pensiones": {},
        "quinta": {"retencion": 0},
        "aportes_empleador": aportes,
    }}


def _resultado_json():
    fila = {
        "DNI": DNI, "Apellidos y Nombres": "PEREZ JUAN", "Sist. Pensión": "ONP",
        "TOTAL BRUTO": 2000.0, "ONP (13%)": 260.0, "AFP Aporte": 0.0, "AFP Seguro": 0.0,
        "AFP Comis.": 0.0, "Ret. 5ta Cat.": 0.0, "Aporte Seg. Social": 180.0,
        "NETO A PAGAR": 1740.0,
    }
    return pd.DataFrame([fila]).to_json(orient="records")


@pytest.fixture
def db():
    m.Base.metadata.drop_all(bind=connection.engine)
    m.Base.metadata.create_all(bind=connection.engine)
    s = connection.SessionLocal()
    emp = m.Empresa(ruc="20123456789", razon_social="EMPRESA TEST SAC")
    s.add(emp)
    s.flush()
    s.add(m.Trabajador(
        empresa_id=emp.id, tipo_doc="DNI", tipo_documento="01", num_doc=DNI, nombres="PEREZ JUAN",
        sueldo_base=2000.0, tipo_contrato="PLANILLA", sistema_pension="ONP",
    ))
    s.commit()
    s.empresa_id = emp.id
    yield s
    s.close()


def _guardar_planilla(db, aportes):
    db.add(m.PlanillaMensual(
        empresa_id=db.empresa_id, periodo_key=PERIODO, estado="CERRADA",
        resultado_json=_resultado_json(), auditoria_json=json.dumps(_auditoria(aportes)),
    ))
    db.commit()


APORTES = {
    "VIDA_LEY": {"etiqueta": "Vida Ley", "entidad": "ASEGURADORA", "codigo": "0803", "monto": 12.5},
    "SCTR_SALUD": {"etiqueta": "SCTR Salud", "entidad": "EPS", "codigo": "0810", "monto": 40.0},
    "SCTR_PENSION": {"etiqueta": "SCTR Pensión", "entidad": "ASEGURADORA", "codigo": "0814", "monto": 25.75},
}


# ── .REM de PLAME ───────────────────────────────────────────────────────────────

def test_rem_por_defecto_no_incluye_aportes_del_empleador(db):
    _guardar_planilla(db, APORTES)
    rem = generar_txt_e18(db, db.empresa_id, PERIODO)
    assert "|0803|" not in rem and "|0810|" not in rem and "|0814|" not in rem
    assert "|0121|2000.00|2000.00|" in rem   # el resto del .REM sigue igual


def test_rem_con_opcion_incluye_los_codigos_correctos(db):
    _guardar_planilla(db, APORTES)
    rem = generar_txt_e18(db, db.empresa_id, PERIODO, incluir_aportes_empleador=True)
    assert f"01|{DNI}|0803|12.50|12.50|" in rem
    assert f"01|{DNI}|0810|40.00|40.00|" in rem
    assert f"01|{DNI}|0814|25.75|25.75|" in rem


def test_rem_no_exporta_aportes_sin_codigo_validado(db):
    aportes = {"SCTR_SALUD": {"etiqueta": "SCTR Salud", "entidad": "ESSALUD", "codigo": None, "monto": 30.0}}
    _guardar_planilla(db, aportes)
    rem = generar_txt_e18(db, db.empresa_id, PERIODO, incluir_aportes_empleador=True)
    assert "|30.00|" not in rem


def test_rem_periodo_viejo_sin_la_clave_no_falla(db):
    db.add(m.PlanillaMensual(
        empresa_id=db.empresa_id, periodo_key=PERIODO, estado="CERRADA", resultado_json=_resultado_json(),
        auditoria_json=json.dumps({DNI: {"ingresos": {"Sueldo Base (30 días)": 2000.0}, "descuentos": {}}}),
    ))
    db.commit()
    rem = generar_txt_e18(db, db.empresa_id, PERIODO, incluir_aportes_empleador=True)
    assert "|0121|" in rem


# ── Asiento contable ────────────────────────────────────────────────────────────

def _configurar_cuentas(db, con_seguros=True):
    db.add(m.Concepto(empresa_id=db.empresa_id, nombre="SUELDO BASICO", tipo="INGRESO", cuenta_contable="621101"))
    kw = dict(
        cuenta_essalud_gasto="627101", cuenta_essalud_pasivo="403101", cuenta_onp="401701",
        cuenta_retencion_5ta="401111", cuenta_remuneraciones_por_pagar="411101",
    )
    if con_seguros:
        kw.update(
            cuenta_vida_ley_gasto="627201", cuenta_vida_ley_pasivo="424101",
            cuenta_sctr_salud_gasto="627202", cuenta_sctr_salud_pasivo="424102",
            cuenta_sctr_pension_gasto="627203", cuenta_sctr_pension_pasivo="424103",
        )
    db.add(m.ConfiguracionContable(empresa_id=db.empresa_id, **kw))
    db.commit()


def test_asiento_incluye_seguros_y_cuadra(db):
    _guardar_planilla(db, APORTES)
    _configurar_cuentas(db)
    buf = generar_asiento_planilla(db, db.empresa_id, PERIODO)
    df = pd.read_excel(io.BytesIO(buf.getvalue()))
    debe_col = next(c for c in df.columns if "Debe" in c)
    haber_col = next(c for c in df.columns if "Haber" in c)
    cuenta_col = next(c for c in df.columns if "Cuenta" in c)
    cuentas = df[cuenta_col].astype(str).tolist()

    # Gasto al débito y pasivo al crédito, por el monto de cada seguro
    for gasto, pasivo, monto in [("627201", "424101", 12.5), ("627202", "424102", 40.0), ("627203", "424103", 25.75)]:
        g = df[df[cuenta_col].astype(str) == gasto]
        p = df[df[cuenta_col].astype(str) == pasivo]
        assert round(g[debe_col].sum(), 2) == monto and round(g[haber_col].sum(), 2) == 0
        assert round(p[haber_col].sum(), 2) == monto and round(p[debe_col].sum(), 2) == 0
    # el asiento completo cuadra
    assert round(df[debe_col].sum() - df[haber_col].sum(), 2) == 0
    assert "621101" in cuentas   # el sueldo sigue contabilizándose


def test_asiento_exige_cuentas_de_seguros_solo_si_hay_monto(db):
    _guardar_planilla(db, APORTES)
    _configurar_cuentas(db, con_seguros=False)
    with pytest.raises(AsientoContableError) as ei:
        generar_asiento_planilla(db, db.empresa_id, PERIODO)
    faltan = " | ".join(ei.value.cuentas_faltantes)
    assert "Vida Ley — Gasto" in faltan and "SCTR Pensión — Por Pagar" in faltan


def test_asiento_sin_seguros_no_pide_cuentas_de_seguros(db):
    _guardar_planilla(db, {})
    _configurar_cuentas(db, con_seguros=False)
    buf = generar_asiento_planilla(db, db.empresa_id, PERIODO)   # no debe lanzar
    df = pd.read_excel(io.BytesIO(buf.getvalue()))
    debe_col = next(c for c in df.columns if "Debe" in c)
    haber_col = next(c for c in df.columns if "Haber" in c)
    assert round(df[debe_col].sum() - df[haber_col].sum(), 2) == 0
