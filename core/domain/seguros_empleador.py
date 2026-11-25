"""
Seguros a cargo del empleador: Vida Ley y SCTR (Salud y Pensión).

Reglas de negocio acordadas:
  - Cada trabajador se marca por separado en cada seguro (Maestro de Personal).
  - El monto NO se calcula: lo digita el usuario cada mes (prima completa, sin
    prorrateo ni proporcionalidad por días/suspensión) en "Ingreso de Asistencias".
  - SCTR Salud puede ser con EPS o con EsSalud; SCTR Pensión con aseguradora privada
    o con la ONP — varía por empresa y por trabajador, por eso la entidad se guarda
    en el trabajador y de ella se deriva el código PLAME.
  - Son aportes a cargo del empleador: NO afectan el neto del trabajador ni las bases
    de AFP/ONP, 5ta categoría o EsSalud.

Este módulo es puro (sin base de datos ni Streamlit) para poder probarlo aislado.
"""

# ── Claves de los seguros ────────────────────────────────────────────────────
VIDA_LEY = "VIDA_LEY"
SCTR_SALUD = "SCTR_SALUD"
SCTR_PENSION = "SCTR_PENSION"

# Orden de presentación (boleta, reportes, asiento)
SEGUROS = (VIDA_LEY, SCTR_SALUD, SCTR_PENSION)

ETIQUETAS = {
    VIDA_LEY: "Vida Ley",
    SCTR_SALUD: "SCTR Salud",
    SCTR_PENSION: "SCTR Pensión",
}

# Clave reservada dentro de VariablesMes.conceptos_json donde se guarda el monto
# digitado cada mes. El prefijo "_" sigue la convención de los ajustes de auditoría
# (_ajuste_afp, etc.): no es un concepto del Maestro de Conceptos y el resto del motor
# la ignora.
CLAVE_JSON = {
    VIDA_LEY: "_seg_vida_ley",
    SCTR_SALUD: "_seg_sctr_salud",
    SCTR_PENSION: "_seg_sctr_pension",
}

# ── Entidades con las que se puede contratar cada seguro ─────────────────────
ASEGURADORA = "ASEGURADORA"
EPS = "EPS"
ESSALUD = "ESSALUD"
ONP = "ONP"

ENTIDADES = {
    VIDA_LEY: {ASEGURADORA: "Aseguradora"},
    SCTR_SALUD: {EPS: "EPS (aseguradora privada)", ESSALUD: "EsSalud"},
    SCTR_PENSION: {ASEGURADORA: "Aseguradora privada", ONP: "ONP"},
}

# Nombre corto para columnas angostas (boleta, resumen de la sábana): los largos de
# ENTIDADES no caben en una celda y se pisan con la columna vecina.
ENTIDAD_CORTA = {ASEGURADORA: "Aseguradora", EPS: "EPS", ESSALUD: "EsSalud", ONP: "ONP"}

# Entidad por defecto cuando el trabajador no tiene una guardada
ENTIDAD_DEFECTO = {
    VIDA_LEY: ASEGURADORA,
    SCTR_SALUD: EPS,
    SCTR_PENSION: ASEGURADORA,
}

# ── Códigos PLAME (Tabla 22 — aportes a cargo del empleador) ─────────────────
# Verificados por el usuario: 0803 (Vida Ley), 0810 (SCTR Salud con EPS),
# 0813 (SCTR Pensión con ONP) y 0814 (SCTR Pensión con aseguradora).
# SCTR Salud con EsSalud: código PENDIENTE de validar contra la declaración de
# prueba. Mientras sea None el aporte se calcula y se muestra en boleta, reportes y
# asiento, pero NO se exporta al .REM (y la pantalla de reportes lo advierte).
CODIGOS_PLAME = {
    (VIDA_LEY, ASEGURADORA): "0803",
    (SCTR_SALUD, EPS): "0810",
    (SCTR_SALUD, ESSALUD): None,
    (SCTR_PENSION, ASEGURADORA): "0814",
    (SCTR_PENSION, ONP): "0813",
}

# Campos de la cuenta contable (ConfiguracionContable) por seguro: (gasto, pasivo)
CUENTAS_CONTABLES = {
    VIDA_LEY: ("cuenta_vida_ley_gasto", "cuenta_vida_ley_pasivo"),
    SCTR_SALUD: ("cuenta_sctr_salud_gasto", "cuenta_sctr_salud_pasivo"),
    SCTR_PENSION: ("cuenta_sctr_pension_gasto", "cuenta_sctr_pension_pasivo"),
}


def codigo_plame(seguro: str, entidad: str):
    """Código PLAME del seguro según la entidad; None si no está definido/validado."""
    return CODIGOS_PLAME.get((seguro, entidad))


def normalizar_entidad(seguro: str, entidad) -> str:
    """Devuelve una entidad válida para el seguro (la por defecto si viene vacía/ajena)."""
    entidad = str(entidad or "").strip().upper()
    if entidad in ENTIDADES[seguro]:
        return entidad
    return ENTIDAD_DEFECTO[seguro]


def _es_si(valor) -> bool:
    """Acepta bool o el 'Sí'/'No' que usa el DataFrame del maestro de personal."""
    if isinstance(valor, str):
        return valor.strip().upper() in ("SÍ", "SI", "TRUE", "1")
    try:
        return bool(valor) and valor == valor  # descarta NaN (NaN != NaN)
    except Exception:
        return False


def seguros_marcados(trabajador) -> dict:
    """
    Seguros en los que está marcado el trabajador → {clave_seguro: entidad}.

    `trabajador` es un mapeo (fila del DataFrame o dict) con las columnas del maestro:
    "Seg. Vida Ley", "Seg. SCTR Salud", "Seg. SCTR Salud Entidad", "Seg. SCTR Pensión", "Seg. SCTR Pensión Entidad".
    """
    marcados = {}
    if _es_si(trabajador.get("Seg. Vida Ley", False)):
        marcados[VIDA_LEY] = ASEGURADORA
    if _es_si(trabajador.get("Seg. SCTR Salud", False)):
        marcados[SCTR_SALUD] = normalizar_entidad(SCTR_SALUD, trabajador.get("Seg. SCTR Salud Entidad"))
    if _es_si(trabajador.get("Seg. SCTR Pensión", False)):
        marcados[SCTR_PENSION] = normalizar_entidad(SCTR_PENSION, trabajador.get("Seg. SCTR Pensión Entidad"))
    return marcados


def marcas_desde_trabajador(t) -> dict:
    """Marcas de seguros leídas de un objeto Trabajador (ORM), en el formato que espera
    seguros_marcados(). Tolera columnas ausentes (BD sin migrar)."""
    return {
        "Seg. Vida Ley": bool(getattr(t, "seg_vida_ley", False) or False),
        "Seg. SCTR Salud": bool(getattr(t, "seg_sctr_salud", False) or False),
        "Seg. SCTR Salud Entidad": getattr(t, "sctr_salud_entidad", None) or "",
        "Seg. SCTR Pensión": bool(getattr(t, "seg_sctr_pension", False) or False),
        "Seg. SCTR Pensión Entidad": getattr(t, "sctr_pension_entidad", None) or "",
    }


def monto_digitado(conceptos_json: dict, seguro: str) -> float:
    """Monto del mes para el seguro, leído de conceptos_json. Nunca negativo."""
    try:
        valor = float((conceptos_json or {}).get(CLAVE_JSON[seguro], 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return round(valor, 2) if valor > 0 else 0.0


def calcular_aportes_empleador(trabajador, conceptos_json: dict) -> dict:
    """
    Aportes del empleador del mes para un trabajador, listos para guardar en la
    auditoría de la planilla:

        {clave: {"etiqueta", "entidad", "codigo", "monto"}}

    Solo incluye los seguros en los que está marcado Y con monto > 0 digitado. La prima
    es completa: no se prorratea por días trabajados, ingreso, cese ni suspensión.
    """
    aportes = {}
    for seguro, entidad in seguros_marcados(trabajador).items():
        monto = monto_digitado(conceptos_json, seguro)
        if monto <= 0:
            continue
        aportes[seguro] = {
            "etiqueta": ETIQUETAS[seguro],
            "entidad": entidad,
            "codigo": codigo_plame(seguro, entidad),
            "monto": monto,
        }
    return aportes


def total_aportes(aportes: dict) -> float:
    """Suma de los montos de un dict de aportes (el que devuelve calcular_aportes_empleador)."""
    return round(sum(float(a.get("monto", 0) or 0) for a in (aportes or {}).values()), 2)


def totales_por_seguro(auditoria_data: dict) -> dict:
    """
    Total del mes por seguro sumando a todos los trabajadores, leyendo el snapshot de la
    planilla (auditoria_data = {dni: {"aportes_empleador": {...}, ...}}).
    Periodos sin la clave (calculados antes de esta función) suman 0 y no rompen nada.
    """
    totales = {s: 0.0 for s in SEGUROS}
    for info in (auditoria_data or {}).values():
        for seguro, ap in ((info or {}).get("aportes_empleador") or {}).items():
            if seguro in totales:
                totales[seguro] += float((ap or {}).get("monto", 0) or 0)
    return {s: round(v, 2) for s, v in totales.items()}


def resumen_por_seguro_entidad(auditoria_data: dict) -> list:
    """
    Resumen del mes agrupado por seguro Y entidad (a cada una se le paga por separado):
    [(seguro, entidad, n_trabajadores, total)], en el orden de SEGUROS. Solo montos > 0.
    """
    acum = {}
    for info in (auditoria_data or {}).values():
        for seguro, ap in ((info or {}).get("aportes_empleador") or {}).items():
            monto = float((ap or {}).get("monto", 0) or 0)
            if seguro not in SEGUROS or monto <= 0:
                continue
            clave = (seguro, (ap or {}).get("entidad") or ENTIDAD_DEFECTO[seguro])
            n, tot = acum.get(clave, (0, 0.0))
            acum[clave] = (n + 1, tot + monto)
    orden = {s: i for i, s in enumerate(SEGUROS)}
    return [
        (s, e, n, round(t, 2))
        for (s, e), (n, t) in sorted(acum.items(), key=lambda kv: (orden[kv[0][0]], kv[0][1]))
    ]


def marcados_sin_monto(trabajador, conceptos_json: dict) -> list:
    """Etiquetas de los seguros marcados que este mes no tienen monto digitado (para avisar)."""
    return [
        ETIQUETAS[s] for s in seguros_marcados(trabajador)
        if monto_digitado(conceptos_json, s) <= 0
    ]
