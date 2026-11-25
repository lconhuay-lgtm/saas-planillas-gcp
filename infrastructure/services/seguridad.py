"""
Hash y verificación de contraseñas, política de claves y bloqueo por intentos.

Formato del hash: "pbkdf2_sha256$<iteraciones>$<sal_hex>$<hash_hex>" (PBKDF2-HMAC-
SHA256 de la librería estándar, sin dependencias nuevas). Los hashes antiguos
(SHA-256 sin sal, 64 caracteres hex) se siguen aceptando para no dejar a nadie
fuera, y se reemplazan por el formato nuevo en el primer login exitoso.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

ALGORITMO = "pbkdf2_sha256"
ITERACIONES = 600_000

MAX_INTENTOS_FALLIDOS = 5
MINUTOS_BLOQUEO = 15
LONGITUD_MINIMA = 10

# Claves que el sistema sembraba antes por defecto: si alguien entra con una de
# ellas, se le obliga a cambiarla antes de usar el sistema.
CLAVES_POR_DEFECTO = frozenset({"admin123", "analista123", "supervisor123"})


def _pbkdf2(password: str, sal: str, iteraciones: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), sal.encode("utf-8"), iteraciones
    ).hex()


def hash_password(password: str) -> str:
    sal = secrets.token_hex(16)
    return f"{ALGORITMO}${ITERACIONES}${sal}${_pbkdf2(password, sal, ITERACIONES)}"


def es_hash_legado(hash_guardado: str) -> bool:
    h = hash_guardado or ""
    return "$" not in h and len(h) == 64


def verificar_password(password: str, hash_guardado: str) -> bool:
    if not password or not hash_guardado:
        return False
    if es_hash_legado(hash_guardado):
        legado = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legado, hash_guardado)
    try:
        algoritmo, iteraciones, sal, esperado = hash_guardado.split("$")
        if algoritmo != ALGORITMO:
            return False
        calculado = _pbkdf2(password, sal, int(iteraciones))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculado, esperado)


def necesita_rehash(hash_guardado: str) -> bool:
    if es_hash_legado(hash_guardado):
        return True
    try:
        algoritmo, iteraciones, _, _ = hash_guardado.split("$")
        return algoritmo != ALGORITMO or int(iteraciones) < ITERACIONES
    except (ValueError, TypeError, AttributeError):
        return True


# Hash con el que se compara cuando el usuario no existe, para que la respuesta
# tarde lo mismo y no delate qué nombres de usuario son válidos.
_HASH_SEÑUELO = hash_password(secrets.token_hex(16))


def verificar_contra_señuelo(password: str) -> None:
    verificar_password(password, _HASH_SEÑUELO)


def validar_politica(password: str, username: str = "") -> str | None:
    """Devuelve un mensaje de error si la clave no cumple la política, o None si es válida."""
    p = password or ""
    if len(p) < LONGITUD_MINIMA:
        return f"La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres."
    if p.lower() in CLAVES_POR_DEFECTO:
        return "No puede usar una contraseña por defecto del sistema."
    if username and username.strip().lower() in p.lower():
        return "La contraseña no puede contener el nombre de usuario."
    if not any(c.isalpha() for c in p) or not any(c.isdigit() for c in p):
        return "La contraseña debe combinar letras y números."
    return None


def esta_bloqueado(bloqueado_hasta, ahora: datetime | None = None) -> bool:
    ahora = ahora or datetime.now()
    return bool(bloqueado_hasta and bloqueado_hasta > ahora)


def registrar_intento_fallido(intentos_previos: int, ahora: datetime | None = None) -> tuple:
    """Devuelve (intentos_actualizados, bloqueado_hasta_o_None)."""
    ahora = ahora or datetime.now()
    intentos = int(intentos_previos or 0) + 1
    if intentos >= MAX_INTENTOS_FALLIDOS:
        return 0, ahora + timedelta(minutes=MINUTOS_BLOQUEO)
    return intentos, None
