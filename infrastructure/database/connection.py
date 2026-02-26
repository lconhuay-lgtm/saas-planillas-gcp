import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# 1. Cargar las variables de entorno (Tu archivo .env)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError(
        "⚠️ ERROR CRÍTICO: DATABASE_URL no está configurado.\n"
        "  - Local: crea un archivo .env con DATABASE_URL=postgresql://...\n"
        "  - Cloud Run: usa --set-secrets=DATABASE_URL=DATABASE_URL:latest al desplegar."
    )

# Neon y otros PaaS entregan 'postgres://' pero SQLAlchemy 2.x requiere 'postgresql://'
DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 2. Crear el Motor (Engine) de SQLAlchemy
# pool_size reducido para Cloud Run: cada instancia crea su propio pool.
# Con pool_size=2 y max_overflow=3 → máx 5 conexiones por instancia.
# Usa la URL del Pooler de Neon para evitar agotar el límite de conexiones.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=2,
    max_overflow=3
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