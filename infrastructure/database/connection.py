from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from .models_sqlalchemy import Base

# En producción, esto vendrá de Google Secret Manager o variables de entorno
# Formato: postgresql://usuario:password@host:puerto/nombre_bd
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///planillas_local.db") # SQLite para desarrollo inicial

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def crear_tablas():
    Base.metadata.create_all(bind=engine)