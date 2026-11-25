"""
Numeración de vouchers: cada asiento generado en el mes lleva su propio Num.Voucher, en orden de generación.

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

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test_vouchers.db")

from infrastructure.database import connection  # noqa: E402

if not str(connection.engine.url).startswith("sqlite"):
    pytest.skip("El motor no es SQLite: se omite para no tocar una base real.", allow_module_level=True)

import pandas as pd  # noqa: E402
from infrastructure.database import models as m  # noqa: E402
from core.use_cases import numeracion_vouchers as nv  # noqa: E402
from core.use_cases import provision_gratificacion as pg  # noqa: E402
from core.use_cases import provision_vacaciones as pv  # noqa: E402
from core.use_cases import provision_cts as pc  # noqa: E402
from core.use_cases.generador_asiento_contable import generar_asiento_planilla  # noqa: E402

DNI = "11111111"
CUENTAS = dict(
    cuenta_essalud_gasto="627101", cuenta_essalud_pasivo="403101", cuenta_onp="401701",
    cuenta_retencion_5ta="401111", cuenta_remuneraciones_por_pagar="411101",
    cuenta_descanso_vacacional="621301", cuenta_vacaciones_por_pagar="415201",
    cuenta_gratificacion_gasto="621201", cuenta_gratificacion_por_pagar="415101",
    cuenta_cts_gasto="621401", cuenta_cts_por_pagar="415301",
)


def _excel(buf):
    return pd.read_excel(io.BytesIO(buf.getvalue()), dtype={"Cuenta": str})


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
    s.add(m.ConfiguracionContable(empresa_id=emp.id, **CUENTAS))
    aud = {DNI: {"nombres": "TRAB 1", "ingresos": {"Sueldo Base (30 días)": 3000.0}, "descuentos": {},
                 "sueldo_base_nominal": 3000.0, "quinta": {"retencion": 0}}}
    fila = {"DNI": DNI, "Apellidos y Nombres": "TRAB 1", "Sist. Pensión": "ONP", "ONP (13%)": 390.0,
            "AFP Aporte": 0.0, "AFP Seguro": 0.0, "AFP Comis.": 0.0, "Ret. 5ta Cat.": 0.0,
            "Aporte Seg. Social": 270.0}
    s.add(m.PlanillaMensual(empresa_id=emp.id, periodo_key="07-2026", estado="CERRADA",
                            resultado_json=pd.DataFrame([fila]).to_json(orient="records"),
                            auditoria_json=json.dumps(aud)))
    s.commit()
    yield s
    s.close()


def _voucher(buf):
    return set(_excel(buf)["Num.Voucher"].tolist())


def test_cada_asiento_lleva_numero_distinto_en_orden_de_generacion(db):
    """CTS primero, luego vacaciones, luego gratificación y planilla: 1, 2, 3, 4."""
    e = db.empresa_id
    assert _voucher(pc.generar_asiento_provision(db, e, "07-2026")) == {1}
    assert _voucher(pv.generar_asiento_provision(db, e, "07-2026")) == {2}
    assert _voucher(pg.generar_asiento_provision(db, e, "07-2026")) == {3}
    assert _voucher(generar_asiento_planilla(db, e, "07-2026")) == {4}


def test_regenerar_un_asiento_conserva_su_numero(db):
    e = db.empresa_id
    pv.generar_asiento_provision(db, e, "07-2026")
    pg.generar_asiento_provision(db, e, "07-2026")
    assert _voucher(pv.generar_asiento_provision(db, e, "07-2026")) == {1}     # no consume uno nuevo
    assert _voucher(pg.generar_asiento_provision(db, e, "07-2026")) == {2}


def test_la_numeracion_es_por_mes_y_por_empresa(db):
    e = db.empresa_id
    assert nv.numero_voucher(db, e, "07-2026", "A") == 1
    assert nv.numero_voucher(db, e, "07-2026", "B") == 2
    assert nv.numero_voucher(db, e, "08-2026", "A") == 1                        # otro mes: vuelve a 1
    otra = m.Empresa(ruc="20999999999", razon_social="OTRA SAC", regimen_laboral="Régimen General")
    db.add(otra)
    db.commit()
    assert nv.numero_voucher(db, otra.id, "07-2026", "A") == 1                  # otra empresa: vuelve a 1
