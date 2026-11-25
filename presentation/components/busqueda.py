"""Búsqueda de texto para listas de la interfaz (sin dependencias de Streamlit)."""
import unicodedata


def normalizar(texto) -> str:
    """Minúsculas, sin tildes ni espacios repetidos: 'Pequeña  S.A.C.' -> 'pequena s.a.c.'"""
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def filtrar_empresas(empresas, texto: str) -> list:
    """
    Empresas cuya razón social o RUC contienen TODAS las palabras buscadas, en
    cualquier orden y sin importar tildes ni mayúsculas ("andes sac", "2061").
    Sin texto devuelve todas. El resultado siempre va ordenado por razón social.
    """
    ordenadas = sorted(empresas, key=lambda e: normalizar(e.razon_social))
    palabras = normalizar(texto).split()
    if not palabras:
        return ordenadas
    return [
        e for e in ordenadas
        if all(p in f"{normalizar(e.razon_social)} {e.ruc or ''}" for p in palabras)
    ]
