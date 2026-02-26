from dataclasses import dataclass
from typing import Optional
from datetime import date

@dataclass
class Empresa:
    id: int
    ruc: str
    razon_social: str
    # 'GENERAL', 'PEQUENA', 'MICRO' - Afecta el pago de CTS y Gratificaciones
    regimen_laboral: str = 'GENERAL' 

@dataclass
class Trabajador:
    id: int
    empresa_id: int
    dni: str
    nombres_apellidos: str
    fecha_ingreso: date
    sueldo_base: float
    tiene_asignacion_familiar: bool
    tiene_eps: bool  # Si es True, EsSalud es 6.75%, sino 9%
    sistema_pension: str  # 'ONP', 'AFP_HABITAT', 'AFP_INTEGRA', etc.
    tipo_comision_afp: str  # 'FLUJO' o 'MIXTA'
    renta_quinta_retenida_previa: float = 0.0  # Retenciones traídas de otra empresa en el año

@dataclass
class ParametrosLegales:
    uit: float
    rmv: float  # Remuneración Mínima Vital
    # Diccionario con las tasas del mes: {'AFP_HABITAT': {'aporte': 0.10, 'prima': 0.0184, 'flujo': 0.0147, 'mixta': 0.0}, ...}
    tasas_afp: dict 
    tope_seguro_afp: float

@dataclass
class VariablesMes:
    mes: int  # 1 a 12
    anio: int
    dias_laborables_empresa: int = 30
    horas_laborables_empresa: float = 240.0 # Ejemplo: 30 dias * 8 horas
    dias_faltados: int = 0
    minutos_tardanza: int = 0
    horas_extras_25: float = 0.0
    horas_extras_35: float = 0.0
    comisiones_mes: float = 0.0
    bonificaciones_extra: float = 0.0