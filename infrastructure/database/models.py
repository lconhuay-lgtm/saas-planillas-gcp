from sqlalchemy import Column, Integer, String, Float, Boolean, Date, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from infrastructure.database.connection import Base

# 1. TABLA MAESTRA DE EMPRESAS
class Empresa(Base):
    __tablename__ = "empresas"
    
    id = Column(Integer, primary_key=True, index=True)
    ruc = Column(String(11), unique=True, index=True, nullable=False)
    razon_social = Column(String(200), nullable=False)
    
    # --- DATOS CORPORATIVOS ---
    domicilio = Column(String(300))
    representante_legal = Column(String(200))
    correo_electronico = Column(String(100))
    
    # --- RÉGIMEN LABORAL ---
    regimen_laboral = Column(String(100), nullable=False, default="Régimen General")
    fecha_acogimiento = Column(Date, nullable=True) # Solo para MYPEs
    
    fecha_registro = Column(DateTime, default=datetime.now)
    
    # Relaciones
    trabajadores = relationship("Trabajador", back_populates="empresa", cascade="all, delete-orphan")
    conceptos = relationship("Concepto", back_populates="empresa", cascade="all, delete-orphan")


# 2. TABLA MAESTRA DE TRABAJADORES
class Trabajador(Base):
    __tablename__ = "trabajadores"
    
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    
    # Datos Personales
    tipo_doc = Column(String(20))
    num_doc = Column(String(20), index=True, nullable=False)
    nombres = Column(String(200), nullable=False)
    fecha_nac = Column(Date)
    
    # Datos Laborales
    cargo = Column(String(100))
    fecha_ingreso = Column(Date)
    situacion = Column(String(50), default="ACTIVO")
    sueldo_base = Column(Float, nullable=False)
    
    # Datos Bancarios
    banco = Column(String(100))
    cuenta_bancaria = Column(String(100))
    cci = Column(String(20))
    
    # Datos Previsionales y Seguros
    asig_fam = Column(Boolean, default=False)
    eps = Column(Boolean, default=False)
    sistema_pension = Column(String(50))
    comision_afp = Column(String(50))
    cuspp = Column(String(50))
    
    # Relación Inversa
    empresa = relationship("Empresa", back_populates="trabajadores")


# 3. TABLA DE CONCEPTOS REMUNERATIVOS (Ingresos y Descuentos)
class Concepto(Base):
    __tablename__ = "conceptos"
    
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    
    nombre = Column(String(100), nullable=False)
    tipo = Column(String(20), nullable=False) # "INGRESO" o "DESCUENTO"
    
    # Afectaciones Tributarias
    afecto_afp = Column(Boolean, default=False)
    afecto_5ta = Column(Boolean, default=False)
    afecto_essalud = Column(Boolean, default=False)
    computable_cts = Column(Boolean, default=False)
    computable_grati = Column(Boolean, default=False)
    
    # Relación Inversa
    empresa = relationship("Empresa", back_populates="conceptos")
    
class ParametroLegal(Base):
    __tablename__ = "parametros_legales"
    
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    periodo_key = Column(String(10), nullable=False) # Formato "01-2026"
    
    # Tasas Generales
    rmv = Column(Float)
    uit = Column(Float)
    tasa_essalud = Column(Float)
    tasa_eps = Column(Float)
    tasa_onp = Column(Float)
    tope_afp = Column(Float)

    # AFP HABITAT
    h_ap = Column(Float); h_pr = Column(Float); h_fl = Column(Float); h_mx = Column(Float)
    # AFP INTEGRA
    i_ap = Column(Float); i_pr = Column(Float); i_fl = Column(Float); i_mx = Column(Float)
    # AFP PRIMA
    p_ap = Column(Float); p_pr = Column(Float); p_fl = Column(Float); p_mx = Column(Float)
    # AFP PROFUTURO
    pr_ap = Column(Float); pr_pr = Column(Float); pr_fl = Column(Float); pr_mx = Column(Float)
    
    fecha_registro = Column(DateTime, default=datetime.now)