"""
Generador del Asiento Contable de Liquidación por Cese — Excel de importación a
SISCONT (mismo formato que el asiento de planilla). Voucher INDEPENDIENTE, con la
fecha de cese del trabajador (no se agrupa con el asiento mensual de planilla,
porque una liquidación puede ocurrir cualquier día del mes).

Solo se puede generar si la LiquidacionCese está APROBADA o PAGADA — nunca desde
un BORRADOR, que todavía puede cambiar.

Reparto de deducciones entre las cuentas por pagar específicas (ver notas junto a
cada línea): la retención de 5ta se resta primero de Vacaciones Por Pagar (hasta
agotarlo) y el remanente de Gratificación Por Pagar, porque ahora ambas están
afectas (código SUNAT 0114 y 0406/0312). El préstamo pendiente se resta de CTS Por
Pagar. Si el usuario prefiere otra convención, es un ajuste local a este archivo.
"""
import io

import pandas as pd

from infrastructure.database.models import LiquidacionCese, Trabajador, Concepto, ConfiguracionContable
from core.use_cases.generador_asiento_contable import (
    AsientoContableError, _fila, COLUMNAS_SISCONT, _RUC_SUNAT, _NOMBRE_SUNAT,
    _AFP_CUENTA_ATTR, _AFP_RUC_RSOCIAL,
)

VERSION_GENERADOR_LIQ = "2026-09-21-r2"


def generar_asiento_liquidacion(db, empresa_id, liquidacion_id):
    """Genera el Excel del Asiento de Liquidación por Cese. Retorna un io.BytesIO."""
    liq = db.query(LiquidacionCese).filter_by(id=liquidacion_id, empresa_id=empresa_id).first()
    if not liq:
        raise AsientoContableError("No se encontró la liquidación indicada.")
    if liq.estado == "BORRADOR":
        raise AsientoContableError(
            "Esta liquidación está en BORRADOR — apruébela antes de generar el asiento "
            "contable (un borrador todavía puede cambiar)."
        )

    trabajador = db.query(Trabajador).filter_by(id=liq.trabajador_id).first()
    if not trabajador:
        raise AsientoContableError("No se encontró al trabajador de esta liquidación.")

    cfg = db.query(ConfiguracionContable).filter_by(empresa_id=empresa_id).first()
    faltantes = set()

    def _cuenta(attr, etiqueta):
        val = ((getattr(cfg, attr, None) if cfg else None) or "").strip()
        if not val:
            faltantes.add(etiqueta)
        return val

    dni = trabajador.num_doc
    nombre = trabajador.nombres
    fecha_asiento = liq.fecha_cese_snapshot.strftime('%d/%m/%Y')
    num_doc_asiento = f"LIQ-{liq.id:06d}"
    glosa_asiento = f"LIQUIDACION DE BENEFICIOS SOCIALES - {nombre}"

    tiene_vac = liq.monto_vacaciones_truncas > 0
    tiene_grati = (liq.monto_grati_trunca + liq.monto_bono_9) > 0
    tiene_cts = liq.monto_cts_trunca > 0
    tiene_sueldo = liq.incluye_sueldo_mes_cese and liq.monto_sueldo_proporcional > 0
    tiene_5ta = liq.monto_retencion_5ta > 0
    tiene_prestamo = liq.monto_prestamos_pendientes > 0
    tiene_pension = getattr(liq, 'monto_pension_afp_onp', 0) > 0
    tiene_essalud_vac = getattr(liq, 'monto_essalud_vacaciones', 0) > 0
    tiene_bono_cese = getattr(liq, 'monto_bono_cese', 0) > 0

    cuenta_vac_gasto = cuenta_vac_pasivo = ""
    cuenta_grati_gasto = cuenta_grati_pasivo = ""
    cuenta_cts_gasto = cuenta_cts_pasivo = ""
    cuenta_sueldo = cuenta_remun_pagar = ""
    cuenta_pension = ""
    ruc_pension = r_social_pension = ""
    cuenta_bono_cese_gasto = cuenta_bono_cese_pasivo = ""

    if tiene_vac:
        cuenta_vac_gasto = _cuenta('cuenta_descanso_vacacional', "Descanso Vacacional (Configuración Contable)")
        cuenta_vac_pasivo = _cuenta('cuenta_vacaciones_por_pagar', "Vacaciones Truncas Por Pagar (Configuración Contable)")
    if tiene_grati:
        cuenta_grati_gasto = _cuenta('cuenta_gratificacion_gasto', "Gratificación Trunca — Gasto (Configuración Contable)")
        cuenta_grati_pasivo = _cuenta('cuenta_gratificacion_por_pagar', "Gratificación Trunca Por Pagar (Configuración Contable)")
    if tiene_cts:
        cuenta_cts_gasto = _cuenta('cuenta_cts_gasto', "CTS — Gasto (Configuración Contable)")
        cuenta_cts_pasivo = _cuenta('cuenta_cts_por_pagar', "CTS Por Pagar (Configuración Contable)")
    if tiene_sueldo:
        conceptos_db = db.query(Concepto).filter_by(empresa_id=empresa_id, nombre="SUELDO BASICO").first()
        cuenta_sueldo = (conceptos_db.cuenta_contable or "").strip() if conceptos_db else ""
        if not cuenta_sueldo:
            faltantes.add('Concepto "SUELDO BASICO" (Maestro de Conceptos)')
        cuenta_remun_pagar = _cuenta('cuenta_remuneraciones_por_pagar', "Remuneraciones por Pagar (Configuración Contable)")
    if tiene_5ta:
        _cuenta('cuenta_retencion_5ta', "Retención 5ta Categoría (Configuración Contable)")
    if tiene_prestamo:
        _cuenta('cuenta_prestamos_personal', "Préstamos al Personal (Configuración Contable)")
    if tiene_pension:
        sistema_pension = (getattr(liq, 'sistema_pension_snapshot', '') or '').upper()
        if sistema_pension == "ONP":
            cuenta_pension = _cuenta('cuenta_onp', "ONP (Configuración Contable)")
            ruc_pension, r_social_pension = _RUC_SUNAT, _NOMBRE_SUNAT
        elif sistema_pension in _AFP_CUENTA_ATTR:
            cuenta_pension = _cuenta(_AFP_CUENTA_ATTR[sistema_pension], f"{sistema_pension} (Configuración Contable)")
            ruc_pension, r_social_pension = _AFP_RUC_RSOCIAL.get(sistema_pension, ("", ""))
        else:
            faltantes.add("Sistema de pensión del trabajador no reconocido (revisar Maestro de Personal)")
    if tiene_essalud_vac:
        _cuenta('cuenta_essalud_gasto', "EsSalud - Gasto (Configuración Contable)")
        _cuenta('cuenta_essalud_pasivo', "EsSalud - Por Pagar (Configuración Contable)")
    if tiene_bono_cese:
        cuenta_bono_cese_gasto = _cuenta('cuenta_bono_cese_gasto', "Bono por Cese — Gasto (Configuración Contable)")
        cuenta_bono_cese_pasivo = _cuenta('cuenta_bono_cese_por_pagar', "Bono por Cese Por Pagar (Configuración Contable)")

    if faltantes:
        raise AsientoContableError(
            "Faltan cuentas contables por configurar antes de generar el asiento.",
            cuentas_faltantes=sorted(faltantes),
        )

    filas = []

    # ── DEBE: gasto de cada componente, por su monto BRUTO completo ──────────
    if tiene_vac:
        filas.append(_fila(11, 1, fecha_asiento, cuenta_vac_gasto, liq.monto_vacaciones_truncas, 0.0,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=dni, ruc=dni, r_social=nombre))
    if tiene_grati:
        monto_grati_bruto = liq.monto_grati_trunca + liq.monto_bono_9
        filas.append(_fila(11, 1, fecha_asiento, cuenta_grati_gasto, monto_grati_bruto, 0.0,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=dni, ruc=dni, r_social=nombre))
    if tiene_cts:
        filas.append(_fila(11, 1, fecha_asiento, cuenta_cts_gasto, liq.monto_cts_trunca, 0.0,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=dni, ruc=dni, r_social=nombre))
    if tiene_sueldo:
        filas.append(_fila(11, 1, fecha_asiento, cuenta_sueldo, liq.monto_sueldo_proporcional, 0.0,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=dni, ruc=dni, r_social=nombre))
    if tiene_essalud_vac:
        filas.append(_fila(11, 1, fecha_asiento, cfg.cuenta_essalud_gasto, liq.monto_essalud_vacaciones, 0.0,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=dni, ruc=dni, r_social=nombre))
    if tiene_bono_cese:
        filas.append(_fila(11, 1, fecha_asiento, cuenta_bono_cese_gasto, liq.monto_bono_cese, 0.0,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=dni, ruc=dni, r_social=nombre))

    # ── HABER: pasivo de cada componente, NETO de las deducciones que le corresponden ──
    # Retención de 5ta: ahora vacaciones truncas (código 0114) TAMBIÉN están afectas,
    # junto con grati trunca + bono 9% (códigos 0406/0312) — se resta primero de
    # Vacaciones Por Pagar (hasta agotarlo), el remanente de Gratificación Por Pagar.
    ret5ta_de_vac = min(liq.monto_retencion_5ta, liq.monto_vacaciones_truncas) if (tiene_5ta and tiene_vac) else 0.0
    ret5ta_de_grati = (liq.monto_retencion_5ta - ret5ta_de_vac) if tiene_5ta else 0.0

    # AFP/ONP y EsSalud sobre vacaciones truncas también se restan de Vacaciones Por Pagar.
    monto_vac_neto = (
        liq.monto_vacaciones_truncas
        - (liq.monto_pension_afp_onp if tiene_pension else 0.0)
        - ret5ta_de_vac
    ) if tiene_vac else 0.0
    if tiene_vac and monto_vac_neto > 0:
        filas.append(_fila(11, 1, fecha_asiento, cuenta_vac_pasivo, 0.0, monto_vac_neto,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=dni, ruc=dni, r_social=nombre))

    monto_grati_neto = ((liq.monto_grati_trunca + liq.monto_bono_9) - ret5ta_de_grati) if tiene_grati else 0.0
    if tiene_grati and monto_grati_neto > 0:
        filas.append(_fila(11, 1, fecha_asiento, cuenta_grati_pasivo, 0.0, monto_grati_neto,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=dni, ruc=dni, r_social=nombre))

    if tiene_5ta:
        filas.append(_fila(11, 1, fecha_asiento, cfg.cuenta_retencion_5ta, 0.0, liq.monto_retencion_5ta,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=_RUC_SUNAT, ruc=_RUC_SUNAT, r_social=_NOMBRE_SUNAT))

    # El préstamo pendiente se resta de CTS Por Pagar (elección simple: ambos son
    # beneficios de naturaleza "diferida/fondo", a diferencia de vacaciones que es
    # efectivo puro por días no gozados). Ajustable aquí si se prefiere otra cuenta.
    monto_cts_neto = liq.monto_cts_trunca - liq.monto_prestamos_pendientes if tiene_cts else 0.0
    if tiene_cts and monto_cts_neto > 0:
        filas.append(_fila(11, 1, fecha_asiento, cuenta_cts_pasivo, 0.0, monto_cts_neto,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=dni, ruc=dni, r_social=nombre))
    if tiene_prestamo:
        filas.append(_fila(11, 1, fecha_asiento, cfg.cuenta_prestamos_personal, 0.0, liq.monto_prestamos_pendientes,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=dni, ruc=dni, r_social=nombre))

    if tiene_pension:
        filas.append(_fila(11, 1, fecha_asiento, cuenta_pension, 0.0, liq.monto_pension_afp_onp,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=ruc_pension, ruc=ruc_pension, r_social=r_social_pension))
    if tiene_essalud_vac:
        filas.append(_fila(11, 1, fecha_asiento, cfg.cuenta_essalud_pasivo, 0.0, liq.monto_essalud_vacaciones,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=_RUC_SUNAT, ruc=_RUC_SUNAT, r_social=_NOMBRE_SUNAT))
    if tiene_bono_cese:
        filas.append(_fila(11, 1, fecha_asiento, cuenta_bono_cese_pasivo, 0.0, liq.monto_bono_cese,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=dni, ruc=dni, r_social=nombre))
    if tiene_sueldo:
        filas.append(_fila(11, 1, fecha_asiento, cuenta_remun_pagar, 0.0, liq.monto_sueldo_proporcional,
                            num_doc_asiento, glosa_asiento, cod_prov_clie=dni, ruc=dni, r_social=nombre))

    # ── Seguro interno: el asiento SIEMPRE debe cuadrar ──────────────────────
    total_debe = sum(f["Monto Debe"] for f in filas)
    total_haber = sum(f["Monto Haber"] for f in filas)
    if round(total_debe - total_haber, 2) != 0:
        raise AsientoContableError(
            f"El asiento no cuadra (Debe: S/ {total_debe:,.2f} vs Haber: S/ {total_haber:,.2f}). "
            f"No se generó el archivo — este es un error interno, no de configuración."
        )

    df_out = pd.DataFrame(filas, columns=COLUMNAS_SISCONT)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_out.to_excel(writer, index=False, sheet_name='Asiento')
    buffer.seek(0)
    return buffer
