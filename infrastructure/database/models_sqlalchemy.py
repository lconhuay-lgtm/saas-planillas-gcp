from sqlalchemy import Column, Integer, String, Float, Boolean, Date, ForeignKey, Enum
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class EmpresaModel(Base):
    __tablename__ = 'empresas'
    id = Column(Integer, primary_key=True, autoincrement=True)
    ruc = Column(String(11), unique=True, nullable=False)
    razon_social = Column(String(200), nullable=False)
    regimen_laboral = Column(String(50), default='GENERAL') # GENERAL, PEQUENA, MICRO
    
    # Relaciones
    trabajadores = relationship("TrabajadorModel", back_populates="empresa")
    conceptos = relationship("ConceptoEmpresaModel", back_populates="empresa")

class TrabajadorModel(Base):
    __tablename__ = 'trabajadores'
    id = Column(Integer, primary_key=True, autoincrement=True)
    empresa_id = Column(Integer, ForeignKey('empresas.id'), nullable=False)
    dni = Column(String(15), unique=True, nullable=False)
    nombres_apellidos = Column(String(150), nullable=False)
    fecha_ingreso = Column(Date, nullable=False)
    sueldo_base = Column(Float, nullable=False)
    tiene_asignacion_familiar = Column(Boolean, default=False)
    tiene_eps = Column(Boolean, default=False)
    sistema_pension = Column(String(50), nullable=False) # Ej: ONP, AFP_INTEGRA
    tipo_comision_afp = Column(String(20)) # FLUJO, MIXTA
    renta_quinta_retenida_previa = Column(Float, default=0.0)
    estado = Column(String(20), default='ACTIVO') # ACTIVO, CESADO

    empresa = relationship("EmpresaModel", back_populates="trabajadores")

class ConceptoEmpresaModel(Base):
    """ 
    TABLA MAESTRA DE CONCEPTOS DINÁMICOS
    Aquí la empresa crea sus propias reglas remunerativas.
    """
    __tablename__ = 'conceptos_empresa'
    id = Column(Integer, primary_key=True, autoincrement=True)
    empresa_id = Column(Integer, ForeignKey('empresas.id'), nullable=False)
    
    nombre = Column(String(100), nullable=False) # Ej: "Bono de Riesgo", "Adelanto de Sueldo"
    tipo_concepto = Column(String(20), nullable=False) # INGRESO, DESCUENTO, APORTE_EMPLEADOR
    
    # Las reglas tributarias (Los Checks)
    afecto_afp_onp = Column(Boolean, default=True)
    afecto_quinta_cat = Column(Boolean, default=True)
    afecto_essalud = Column(Boolean, default=True)
    computable_cts = Column(Boolean, default=False)
    computable_grati = Column(Boolean, default=False)

    empresa = relationship("EmpresaModel", back_populates="conceptos")

class PlanillaMensualModel(Base):
    """ Cabecera de la Planilla Calculada y Cerrada """
    __tablename__ = 'planillas_mensuales'
    id = Column(Integer, primary_key=True, autoincrement=True)
    empresa_id = Column(Integer, ForeignKey('empresas.id'), nullable=False)
    trabajador_id = Column(Integer, ForeignKey('trabajadores.id'), nullable=False)
    mes = Column(Integer, nullable=False)
    anio = Column(Integer, nullable=False)
    
    # Totales para lectura rápida
    total_ingresos = Column(Float, default=0.0)
    total_descuentos = Column(Float, default=0.0)
    total_aportes = Column(Float, default=0.0)
    neto_a_pagar = Column(Float, default=0.0)

    detalles = relationship("DetallePlanillaModel", back_populates="planilla")

class DetallePlanillaModel(Base):
    """ Detalle de qué conceptos exactos se le pagó o descontó al trabajador ese mes """
    __tablename__ = 'detalles_planilla'
    id = Column(Integer, primary_key=True, autoincrement=True)
    planilla_id = Column(Integer, ForeignKey('planillas_mensuales.id'), nullable=False)
    concepto_id = Column(Integer, ForeignKey('conceptos_empresa.id'), nullable=False)
    monto = Column(Float, nullable=False)

    planilla = relationship("PlanillaMensualModel", back_populates="detalles")