from sqlalchemy import Column, Integer, String, Float, Boolean, Date, ForeignKey, DateTime, UniqueConstraint, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from infrastructure.database.connection import Base


# TABLA INTERMEDIA PARA PERMISOS DE USUARIOS POR EMPRESA (Control de Accesos SAP Style)
class UsuarioEmpresa(Base):
    __tablename__ = "usuario_empresa"
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id", ondelete="CASCADE"), primary_key=True)
    fecha_asignacion = Column(DateTime, default=datetime.now)

# 0. TABLA MAESTRA DE USUARIOS (Seguridad Centralizada)
class Usuario(Base):
    __tablename__ = "usuarios"

    id               = Column(Integer, primary_key=True, index=True)
    username         = Column(String(50), unique=True, nullable=False, index=True)
    password_hash    = Column(String(64), nullable=False)
    rol              = Column(String(20), nullable=False)   # admin | supervisor | analista | consulta
    nombre_completo  = Column(String(100), nullable=True)
    email            = Column(String(100), nullable=True)
    activo           = Column(Boolean, default=True)
    acceso_total     = Column(Boolean, default=False)       # Bypass de seguridad multi-empresa
    modulos_restringidos = Column(Text, default='[]')       # JSON con lista de módulos bloqueados
    ultimo_login     = Column(DateTime, nullable=True)
    fecha_registro   = Column(DateTime, default=datetime.now)

    # Relación jerárquica con empresas (Control de Perímetros)
    empresas_asignadas = relationship("Empresa", secondary="usuario_empresa", backref="usuarios_autorizados")


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
    cuenta_cargo_bcp = Column(String(20)) # Para Telecrédito

    # --- RÉGIMEN LABORAL ---
    regimen_laboral = Column(String(100), nullable=False, default="Régimen General")
    fecha_acogimiento = Column(Date, nullable=True)

    # --- JORNADA LABORAL ---
    horas_jornada_diaria = Column(Float, default=8.0)

    # --- POLÍTICAS DE PROYECCIÓN ---
    factor_proyeccion_grati = Column(Float, nullable=True)

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
    tipo_doc = Column(String(20))    # 01=DNI, 04=CE, 07=Pasaporte
    num_doc = Column(String(20), index=True, nullable=False)
    # Nombre completo (campo original — mantener para compat. con registros existentes)
    nombres = Column(String(200), nullable=False)
    # Campos separados para PLAME / AFPnet
    apellido_paterno = Column(String(100), nullable=True)
    apellido_materno = Column(String(100), nullable=True)
    fecha_nac = Column(Date)
    correo_electronico = Column(String(100), nullable=True)
    
    # Datos Laborales
    cargo = Column(String(100))
    fecha_ingreso = Column(Date)
    fecha_cese = Column(Date, nullable=True)
    situacion = Column(String(50), default="ACTIVO")
    sueldo_base = Column(Float, nullable=False)
    # Tipo de contratación: 'PLANILLA' (5ta Cat.) o 'LOCADOR' (4ta Cat.)
    tipo_contrato = Column(String(20), default='PLANILLA', nullable=False, server_default='PLANILLA')
    dias_vacaciones_anuales = Column(Integer, default=30)
    
    # Datos Bancarios
    banco = Column(String(100))
    cuenta_bancaria = Column(String(100))
    cci = Column(String(20))
    # Suspensión de retenciones 4ta categoría (locadores con constancia SUNAT)
    tiene_suspension_4ta = Column(Boolean, default=False, server_default='false')
    
    # Datos Previsionales y Seguros
    asig_fam = Column(Boolean, default=False)
    eps = Column(Boolean, default=False)
    sistema_pension = Column(String(50))
    comision_afp = Column(String(50))
    cuspp = Column(String(50))
    # Seguro de salud: "ESSALUD" (9%) o "SIS" (S/15.00 fijo, solo Micro Empresa)
    seguro_social = Column(String(20), default="ESSALUD", nullable=False, server_default="ESSALUD")
    
    # Relación Inversa
    empresa = relationship("Empresa", back_populates="trabajadores")
    vacaciones = relationship("RegistroVacaciones", backref="trabajador", cascade="all, delete-orphan")


# 3. TABLA DE CONCEPTOS REMUNERATIVOS (Ingresos y Descuentos)
class Concepto(Base):
    __tablename__ = "conceptos"
    
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    
    nombre = Column(String(100), nullable=False)
    tipo = Column(String(20), nullable=False)          # "INGRESO" o "DESCUENTO"
    codigo_sunat = Column(String(4), nullable=True)    # Código Tabla 22 PLAME (ej: "0121")

    # Afectaciones Tributarias
    afecto_afp = Column(Boolean, default=False)
    afecto_5ta = Column(Boolean, default=False)
    afecto_essalud = Column(Boolean, default=False)
    computable_cts = Column(Boolean, default=False)
    computable_grati = Column(Boolean, default=False)
    prorrateable_por_asistencia = Column(Boolean, default=False)
    
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

    # Retención 4ta Categoría (Locadores de Servicio)
    tasa_4ta  = Column(Float, default=8.0)     # Porcentaje de retención (8 % por ley)
    tope_4ta  = Column(Float, default=1500.0)  # Monto mínimo para aplicar retención

    # Límite de edad para cobro de Prima de Seguro AFP
    edad_maxima_prima_afp = Column(Integer, default=65)

    fecha_registro = Column(DateTime, default=datetime.now)


# 5. TABLA DE VARIABLES MENSUALES (Asistencias, HE, Conceptos Variables)
class VariablesMes(Base):
    """
    Almacena las variables de nómina de cada trabajador por periodo.
    Reemplaza el session_state['variables_por_periodo'] para persistencia real.
    Los conceptos dinámicos (bonos, descuentos manuales) se almacenan como JSON.
    """
    __tablename__ = "variables_mes"
    __table_args__ = (
        UniqueConstraint('empresa_id', 'trabajador_id', 'periodo_key', name='uq_variable_mes'),
    )

    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False)
    periodo_key = Column(String(10), nullable=False)  # Formato "MM-YYYY", ej: "02-2026"

    # Campos fijos de tiempo
    dias_faltados = Column(Integer, default=0)         # Legado — usar suspensiones_json
    min_tardanza = Column(Integer, default=0)
    hrs_extras_25 = Column(Float, default=0.0)
    hrs_extras_35 = Column(Float, default=0.0)

    # Suspensiones por tipo SUNAT Tabla 21: {"07": 2, "20": 3}
    suspensiones_json = Column(Text, default='{}')

    # Montos de conceptos dinámicos: {"BONO DE RIESGO": 500.0, "GRATIFICACION (JUL/DIC)": 3000.0}
    conceptos_json = Column(Text, default='{}')

    # Días sin prestar servicios para locadores (4ta categoría)
    dias_descuento_locador = Column(Integer, default=0)

    # Notas manuales de gestión (SAP/Oracle style)
    notas_gestion = Column(Text, default='')

    fecha_registro = Column(DateTime, default=datetime.now)

    # Relaciones
    trabajador = relationship("Trabajador", backref="variables_mes")
    empresa = relationship("Empresa", backref="variables_mes")


# 6. TABLA DE PLANILLAS CALCULADAS (Resultado Mensual Cerrado)
class PlanillaMensual(Base):
    """
    Guarda el resultado completo del cálculo de planilla de un periodo.
    Reemplaza el session_state['res_planilla'] para persistencia real.
    El resultado se almacena como JSON para recuperación exacta entre sesiones.
    """
    __tablename__ = "planillas_mensuales"
    __table_args__ = (
        UniqueConstraint('empresa_id', 'periodo_key', name='uq_planilla_mes'),
    )

    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    periodo_key = Column(String(10), nullable=False)  # Formato "MM-YYYY"
    fecha_calculo = Column(DateTime, default=datetime.now)

    # DataFrame completo de resultados serializado como JSON
    resultado_json = Column(Text, nullable=False)
    # Datos de auditoría por trabajador (desglose detallado)
    auditoria_json = Column(Text, nullable=False)
    # NUEVO: Resultados calculados de locadores (snapshot)
    honorarios_json = Column(Text, default='[]')

    # Cierre de planilla
    estado      = Column(String(10), default="ABIERTA")   # ABIERTA | CERRADA
    cerrada_por = Column(String(100), nullable=True)
    fecha_cierre = Column(DateTime, nullable=True)

    empresa = relationship("Empresa", backref="planillas")


# 7. TABLA DE PRÉSTAMOS / DESCUENTOS PROGRAMADOS
class Prestamo(Base):
    __tablename__ = "prestamos"

    id              = Column(Integer, primary_key=True, index=True)
    empresa_id      = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    trabajador_id   = Column(Integer, ForeignKey("trabajadores.id"), nullable=False)
    concepto        = Column(String(100), default="Préstamo Personal")
    monto_total     = Column(Float, nullable=False)
    numero_cuotas   = Column(Integer, nullable=False)
    fecha_otorgamiento = Column(Date, default=datetime.now)
    estado          = Column(String(20), default="ACTIVO")   # ACTIVO | CANCELADO

    trabajador = relationship("Trabajador", backref="prestamos")
    cuotas     = relationship("CuotaPrestamo", back_populates="prestamo",
                              cascade="all, delete-orphan")


class CuotaPrestamo(Base):
    __tablename__ = "cuotas_prestamo"

    id           = Column(Integer, primary_key=True, index=True)
    prestamo_id  = Column(Integer, ForeignKey("prestamos.id"), nullable=False)
    numero_cuota = Column(Integer, nullable=False)
    periodo_key  = Column(String(10), nullable=False)   # Formato MM-YYYY
    monto        = Column(Float, nullable=False)
    estado       = Column(String(20), default="PENDIENTE")  # PENDIENTE | PAGADA

    prestamo = relationship("Prestamo", back_populates="cuotas")


# 8. TABLA DE KARDEX DE VACACIONES
class RegistroVacaciones(Base):
    __tablename__ = "registro_vacaciones"

    id = Column(Integer, primary_key=True, index=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False)
    
    # Rango de fechas
    fecha_inicio = Column(Date, nullable=False)
    fecha_fin = Column(Date, nullable=False)
    
    # Consumo
    dias_gozados = Column(Integer, default=0)
    dias_vendidos = Column(Integer, default=0)
    
    # Control
    periodo_origen = Column(String(50), nullable=True) # Ej: '2024-2025'
    estado = Column(String(20), default="APROBADO")    # APROBADO | ANULADO
    observaciones = Column(Text, nullable=True)
    
    # Auditoría
    fecha_registro = Column(DateTime, default=datetime.now)

# 9. TABLA DE DEPÓSITOS DE CTS
class DepositoCTS(Base):
    __tablename__ = 'depositos_cts'
    __table_args__ = (
        UniqueConstraint('empresa_id', 'trabajador_id', 'periodo_key_deposito', name='uq_deposito_cts'),
    )

    id                   = Column(Integer, primary_key=True, index=True)
    empresa_id           = Column(Integer, ForeignKey('empresas.id'), nullable=False)
    trabajador_id        = Column(Integer, ForeignKey('trabajadores.id'), nullable=False)
    periodo_label        = Column(String(30))          # "NOV 2025 – ABR 2026"
    periodo_key_deposito = Column(String(10))          # "05-2026" (mes de depósito)
    base_computable      = Column(Float, default=0.0)
    sexto_grati          = Column(Float, default=0.0)  # 1/6 de grati aplicada en la base
    meses_computados     = Column(Float, default=0.0)
    factor               = Column(Float, default=1.0)
    monto                = Column(Float, default=0.0)
    estado               = Column(String(20), default='PENDIENTE')  # PENDIENTE | DEPOSITADO
    fecha_deposito       = Column(Date, nullable=True)
    banco_cts            = Column(String(100), nullable=True)
    cuenta_cts           = Column(String(100), nullable=True)
    fecha_registro       = Column(DateTime, default=datetime.now)

    empresa    = relationship('Empresa')
    trabajador = relationship('Trabajador', backref='depositos_cts')


class LogEnvioBoleta(Base):
    __tablename__ = "log_envio_boletas"
    id = Column(Integer, primary_key=True, index=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False)
    periodo_key = Column(String(10), nullable=False)
    correo_destino = Column(String(100), nullable=False)
    estado = Column(String(20), default="ENVIADO") # ENVIADO | ERROR
    mensaje_error = Column(Text, nullable=True)
    fecha_envio = Column(DateTime, default=datetime.now)
