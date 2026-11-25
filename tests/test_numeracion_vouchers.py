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


def _planilla_agosto(db):
    j = db.query(m.PlanillaMensual).filter_by(empresa_id=db.empresa_id, periodo_key="07-2026").one()
    db.add(m.PlanillaMensual(empresa_id=db.empresa_id, periodo_key="08-2026", estado="CERRADA",
                             resultado_json=j.resultado_json, auditoria_json=j.auditoria_json))
    db.commit()


def _docs_pasivo(buf, cuenta):
    df = _excel(buf)
    return set(df[df["Cuenta"] == cuenta]["Num.Doc"].tolist())


def test_las_provisiones_de_un_periodo_comparten_un_solo_num_doc(db):
    """Julio y agosto: el pasivo de cada tipo queda en UN documento, no uno por mes."""
    e = db.empresa_id
    _planilla_agosto(db)
    assert _docs_pasivo(pc.generar_asiento_provision(db, e, "07-2026"), "415301") == {"CTS-MAYOCT-2026"}
    assert _docs_pasivo(pc.generar_asiento_provision(db, e, "08-2026"), "415301") == {"CTS-MAYOCT-2026"}
    assert _docs_pasivo(pg.generar_asiento_provision(db, e, "07-2026"), "415101") == {"GRA-JULDIC-2026"}
    assert _docs_pasivo(pg.generar_asiento_provision(db, e, "08-2026"), "415101") == {"GRA-JULDIC-2026"}
    assert _docs_pasivo(pv.generar_asiento_provision(db, e, "07-2026"), "415201") == {"VAC-2026"}
    assert _docs_pasivo(pv.generar_asiento_provision(db, e, "08-2026"), "415201") == {"VAC-2026"}


def test_helpers_de_num_doc():
    assert nv.doc_cts("MAY-OCT-2026") == "CTS-MAYOCT-2026"
    assert nv.doc_cts("NOV-ABR-2027") == "CTS-NOVABR-2027"
    assert nv.doc_gratificacion("JUL-DIC", 2026) == "GRA-JULDIC-2026"
    assert nv.doc_vacaciones(2026) == "VAC-2026"


def test_la_liquidacion_cancela_cada_pasivo_contra_el_documento_de_su_provision(db):
    """El Debe de la liquidación lleva el mismo Num.Doc que las provisiones que cancela."""
    from core.use_cases.generador_asiento_liquidacion import generar_asiento_liquidacion
    e = db.empresa_id
    tid = db.query(m.Trabajador).filter_by(num_doc=DNI).one().id
    db.add(m.ProvisionVacaciones(empresa_id=e, trabajador_id=tid, periodo_key="09-2026", saldo=1800.0,
                                 monto_provision=1800.0, cancelado=0.0))
    db.add(m.ProvisionGratificacion(empresa_id=e, trabajador_id=tid, periodo_key="09-2026", semestre="JUL-DIC-2026",
                                    monto_grati=500.0, monto_bono=45.0))
    db.add(m.ProvisionCTS(empresa_id=e, trabajador_id=tid, periodo_key="09-2026", periodo_cts="MAY-OCT-2026",
                          tipo="PROVISION", monto=400.0))
    liq = m.LiquidacionCese(
        empresa_id=e, trabajador_id=tid, estado="APROBADA",
        fecha_ingreso_snapshot=datetime.date(2026, 1, 1), fecha_cese_snapshot=datetime.date(2026, 10, 15),
        sueldo_base_snapshot=3000.0, monto_vacaciones_truncas=2000.0, monto_grati_trunca=500.0, monto_bono_9=45.0,
        monto_cts_trunca=450.0, periodo_grati_ref="JUL-DIC 2026", periodo_cts_ref="MAY-OCT (dep. 2026)",
        total_bruto=2995.0, total_neto=2995.0)
    db.add(liq)
    db.commit()
    df = _excel(generar_asiento_liquidacion(db, e, liq.id))
    debe = df[df["Monto Debe"] > 0]
    assert set(debe[debe["Cuenta"] == "415201"]["Num.Doc"]) == {"VAC-2026"}
    assert set(debe[debe["Cuenta"] == "415101"]["Num.Doc"]) == {"GRA-JULDIC-2026"}
    assert set(debe[debe["Cuenta"] == "415301"]["Num.Doc"]) == {"CTS-MAYOCT-2026"}


def test_la_numeracion_es_por_mes_y_por_empresa(db):
    e = db.empresa_id
    assert nv.numero_voucher(db, e, "07-2026", "A") == 1
    assert nv.numero_voucher(db, e, "07-2026", "B") == 2
    assert nv.numero_voucher(db, e, "08-2026", "A") == 1                        # otro mes: vuelve a 1
    otra = m.Empresa(ruc="20999999999", razon_social="OTRA SAC", regimen_laboral="Régimen General")
    db.add(otra)
    db.commit()
    assert nv.numero_voucher(db, otra.id, "07-2026", "A") == 1                  # otra empresa: vuelve a 1
