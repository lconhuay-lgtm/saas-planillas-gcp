"""
Numeración de vouchers (columna "Num.Voucher" del asiento SISCONT).

Cada asiento que genera el sistema (planilla, provisión de gratificación / vacaciones / CTS y
liquidación por cese) lleva un número de voucher PROPIO dentro del mes contable de la empresa:
el primero que se genera en el mes es el 1, el siguiente el 2, y así. Se asigna en el orden en
que se GENERAN, sin importar de qué tipo sean (si primero se genera la CTS y luego la
gratificación, la CTS es el 1 y la gratificación el 2).

Regenerar el mismo asiento conserva su número (no consume uno nuevo): la clave es
(empresa, mes, tipo de asiento). El registro vive en la tabla `vouchers_asiento`.
"""
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from infrastructure.database.models import VoucherAsiento

# Claves de tipo de asiento
CLAVE_PLANILLA = "PLANILLA"
CLAVE_PROV_GRATI = "PROV-GRATI"
CLAVE_PROV_VAC = "PROV-VAC"
CLAVE_PROV_CTS = "PROV-CTS"


def clave_liquidacion(liquidacion_id: int) -> str:
    return f"LIQ-{liquidacion_id}"


# ── Num.Doc: UNA obligación por periodo y trabajador ─────────────────────────────
# El Num.Voucher identifica el asiento de cada mes; el Num.Doc enlaza los movimientos de una misma
# obligación (junto con el DNI del trabajador). Todas las provisiones de un periodo comparten
# documento, para que el pago (depósito de CTS, planilla de diciembre, liquidación) se aplique
# contra una sola partida abierta por trabajador y no contra un documento por cada mes.

def doc_cts(etiqueta_periodo: str) -> str:
    """'MAY-OCT-2026' -> 'CTS-MAYOCT-2026' (año = el del depósito)."""
    ini, fin, anio = str(etiqueta_periodo).split('-')
    return f"CTS-{ini}{fin}-{anio}"


def doc_gratificacion(semestre: str, anio: int) -> str:
    """('JUL-DIC', 2026) -> 'GRA-JULDIC-2026'."""
    return f"GRA-{str(semestre).replace('-', '')}-{anio}"


def doc_vacaciones(anio: int) -> str:
    """Una partida de vacaciones por ejercicio: 'VAC-2026'."""
    return f"VAC-{anio}"


def numero_voucher(db, empresa_id: int, periodo_key: str, clave: str) -> int:
    """Número de voucher del asiento `clave` en el mes `periodo_key` ("MM-YYYY"); lo crea si no existe."""
    for _ in range(3):   # reintento por si dos generaciones simultáneas piden el mismo número
        existente = db.query(VoucherAsiento).filter_by(
            empresa_id=empresa_id, periodo_key=periodo_key, clave=clave).first()
        if existente:
            return int(existente.num_voucher)
        maximo = db.query(func.max(VoucherAsiento.num_voucher)).filter_by(
            empresa_id=empresa_id, periodo_key=periodo_key).scalar() or 0
        try:
            db.add(VoucherAsiento(empresa_id=empresa_id, periodo_key=periodo_key,
                                  clave=clave, num_voucher=int(maximo) + 1))
            db.commit()
            return int(maximo) + 1
        except IntegrityError:
            db.rollback()
    raise RuntimeError("No se pudo asignar el número de voucher; reintente la generación.")


def numerar_filas(db, empresa_id: int, periodo_key: str, clave: str, filas: list) -> int:
    """Asigna el número de voucher a todas las filas del asiento (modifica `filas`) y lo devuelve."""
    n = numero_voucher(db, empresa_id, periodo_key, clave)
    for f in filas:
        f["Num.Voucher"] = n
    return n
