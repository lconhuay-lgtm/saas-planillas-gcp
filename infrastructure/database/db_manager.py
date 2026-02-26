from contextlib import contextmanager
from .connection import SessionLocal

@contextmanager
def get_db_session():
    """Context manager para asegurar que las conexiones a BD se cierren correctamente."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()