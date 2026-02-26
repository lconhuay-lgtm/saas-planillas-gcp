from infrastructure.database.connection import engine, Base
from infrastructure.database.models import Empresa, Trabajador, Concepto

def inicializar_base_de_datos():
    print("⏳ Conectando al servidor de Neon (PostgreSQL)...")
    
    try:
        # 1. ESTO BORRA LAS TABLAS VIEJAS (¡Cuidado en producción!)
        print("🗑️ Borrando estructura antigua...")
        Base.metadata.drop_all(bind=engine)
        
        # 2. ESTO CREA LAS TABLAS NUEVAS CON LAS NUEVAS COLUMNAS
        print("🏗️ Construyendo nueva estructura con Régimen MYPE...")
        Base.metadata.create_all(bind=engine)
        
        print("✅ ¡ÉXITO TOTAL! Las tablas han sido recreadas correctamente.")
        print("Ahora sí verás 'regimen_laboral' y 'fecha_acogimiento' en tu BD.")
    except Exception as e:
        print(f"❌ Ocurrió un error al conectar o recrear las tablas:")
        print(e)

if __name__ == "__main__":
    inicializar_base_de_datos()