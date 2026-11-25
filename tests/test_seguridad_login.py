"""Pruebas de hash de contraseñas, política y bloqueo (infrastructure/services/seguridad.py)."""
import hashlib
from datetime import datetime, timedelta

from infrastructure.services import seguridad as s


def test_hash_nuevo_verifica_y_usa_sal():
    h1 = s.hash_password("ClaveSegura2026")
    h2 = s.hash_password("ClaveSegura2026")
    assert h1 != h2                                  # sal distinta en cada hash
    assert h1.startswith("pbkdf2_sha256$")
    assert s.verificar_password("ClaveSegura2026", h1)
    assert not s.verificar_password("otraClave2026", h1)
    assert not s.necesita_rehash(h1)


def test_hash_legado_sha256_sigue_funcionando_y_pide_rehash():
    legado = hashlib.sha256(b"admin123").hexdigest()
    assert s.es_hash_legado(legado)
    assert s.verificar_password("admin123", legado)
    assert not s.verificar_password("admin1234", legado)
    assert s.necesita_rehash(legado)


def test_entradas_invalidas_no_autentican():
    assert not s.verificar_password("", s.hash_password("x1234567890"))
    assert not s.verificar_password("algo", "")
    assert not s.verificar_password("algo", "md5$1$a$b")
    assert not s.verificar_password("algo", "pbkdf2_sha256$no-numero$a$b")


def test_politica_de_contrasenas():
    assert s.validar_politica("corta1") is not None
    assert s.validar_politica("supervisor123") is not None             # clave por defecto
    assert s.validar_politica("SoloLetrasLargas") is not None
    assert s.validar_politica("1234567890123") is not None
    assert s.validar_politica("juanperez2026x", "juanperez") is not None
    assert s.validar_politica("Planillas2026!", "juanperez") is None


def test_bloqueo_tras_cinco_intentos():
    ahora = datetime(2026, 11, 9, 10, 0)
    intentos, bloqueo = 0, None
    for _ in range(s.MAX_INTENTOS_FALLIDOS - 1):
        intentos, bloqueo = s.registrar_intento_fallido(intentos, ahora)
        assert bloqueo is None
    intentos, bloqueo = s.registrar_intento_fallido(intentos, ahora)
    assert intentos == 0
    assert bloqueo == ahora + timedelta(minutes=s.MINUTOS_BLOQUEO)
    assert s.esta_bloqueado(bloqueo, ahora + timedelta(minutes=1))
    assert not s.esta_bloqueado(bloqueo, ahora + timedelta(minutes=s.MINUTOS_BLOQUEO + 1))
    assert not s.esta_bloqueado(None, ahora)
