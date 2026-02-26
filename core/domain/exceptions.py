class EmpresaNoSeleccionadaError(Exception):
    """Se lanza cuando se intenta operar sin una empresa en el contexto."""
    pass

class TrabajadorInactivoError(Exception):
    """Se lanza cuando se intenta calcular planilla a un trabajador cesado y no liquidado."""
    pass

class ReglaNegocioError(Exception):
    """Errores generales de cálculo (ej. faltan tasas de AFP para el mes actual)."""
    pass