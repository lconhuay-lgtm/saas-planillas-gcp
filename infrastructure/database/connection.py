import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# 1. Cargar las variables de entorno (Tu archivo .env)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("⚠️ ERROR: No se encontró DATABASE_URL en el archivo .env. Asegúrate de haberlo creado.")

# 2. Crear el Motor (Engine) de SQLAlchemy
# pool_pre_ping=True es vital para Neon: verifica que la conexión siga viva antes de enviar datos
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,          # Conexiones simultáneas permitidas en este clon de la app
    max_overflow=10       # Conexiones extra de emergencia
)

# 3. Crear la Fábrica de Sesiones
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 4. Crear la Clase Base de donde heredarán todas nuestras tablas
Base = declarative_base()

# 5. Función para obtener la sesión de BD de forma segura
def get_db():
    """Generador que abre una conexión y la cierra automáticamente al terminar"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()