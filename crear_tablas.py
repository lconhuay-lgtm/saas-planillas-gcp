from infrastructure.database.connection import engine, Base

# Importar TODOS los modelos para que SQLAlchemy los registre en Base.metadata
from infrastructure.database.models import (
    Usuario, UsuarioEmpresa,
    Empresa, Trabajador, Concepto, ParametroLegal,
    VariablesMes, PlanillaMensual
)

def inicializar_base_de_datos(forzar_recrear=False):
    """
    Crea las tablas en Neon si no existen.

    Args:
        forzar_recrear (bool): Si es True, BORRA y recrea todas las tablas.
                               ⚠️ SOLO usar en entornos de desarrollo, NUNCA en producción.
    """
    print("[WAIT] Conectando al servidor de Neon (PostgreSQL)...")

    try:
        if forzar_recrear:
            print("[WARN] MODO DESTRUCTIVO: Borrando estructura antigua...")
            print("       (Solo usar en desarrollo. En producción usa migraciones Alembic)")
            Base.metadata.drop_all(bind=engine)
            print("[INFO] Reconstruyendo todas las tablas...")
        else:
            print("[INFO] Creando tablas nuevas (las existentes no se modifican)...")

        Base.metadata.create_all(bind=engine)

        tablas = list(Base.metadata.tables.keys())
        print(f"[OK] ¡EXITO! Tablas verificadas/creadas: {tablas}")

    except Exception as e:
        print(f"[ERROR] Error al conectar o crear las tablas:")
        print(e)


if __name__ == "__main__":
    import sys
    # Pasar --reset como argumento para forzar recreación (solo desarrollo)
    forzar = "--reset" in sys.argv
    if forzar:
        print("[WARN] ATENCION: Se ejecutara con --reset. Esto BORRARA todos los datos.")
        confirmacion = input("Escriba 'CONFIRMAR' para continuar: ")
        if confirmacion != "CONFIRMAR":
            print("Operación cancelada.")
            exit()
    inicializar_base_de_datos(forzar_recrear=forzar)
