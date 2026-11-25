"""Pruebas de la búsqueda del Selector de Empresa."""
from types import SimpleNamespace

from presentation.components.busqueda import filtrar_empresas, normalizar


def _emp(razon, ruc):
    return SimpleNamespace(razon_social=razon, ruc=ruc)


EMPRESAS = [
    _emp("Transportes Los Andes S.A.C.", "20612345671"),
    _emp("ACME Perú E.I.R.L.", "20498765432"),
    _emp("Panadería Ñaña S.A.", "10456789012"),
]


def _nombres(lista):
    return [e.razon_social for e in lista]


def test_sin_texto_devuelve_todas_ordenadas():
    assert _nombres(filtrar_empresas(EMPRESAS, "")) == [
        "ACME Perú E.I.R.L.", "Panadería Ñaña S.A.", "Transportes Los Andes S.A.C.",
    ]
    assert len(filtrar_empresas(EMPRESAS, "   ")) == 3


def test_busca_sin_importar_mayusculas_ni_tildes():
    assert _nombres(filtrar_empresas(EMPRESAS, "peru")) == ["ACME Perú E.I.R.L."]
    assert _nombres(filtrar_empresas(EMPRESAS, "PANADERIA")) == ["Panadería Ñaña S.A."]
    assert _nombres(filtrar_empresas(EMPRESAS, "nana")) == ["Panadería Ñaña S.A."]


def test_busca_por_ruc_parcial():
    assert _nombres(filtrar_empresas(EMPRESAS, "2061")) == ["Transportes Los Andes S.A.C."]


def test_varias_palabras_en_cualquier_orden():
    assert _nombres(filtrar_empresas(EMPRESAS, "andes transportes")) == ["Transportes Los Andes S.A.C."]
    assert filtrar_empresas(EMPRESAS, "andes acme") == []


def test_tolera_ruc_vacio():
    assert len(filtrar_empresas([_emp("Sin RUC", None)], "sin")) == 1


def test_normalizar():
    assert normalizar("  Pequeña   Empresa ") == "pequena empresa"
