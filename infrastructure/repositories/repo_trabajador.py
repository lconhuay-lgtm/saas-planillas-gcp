from sqlalchemy.orm import Session
from infrastructure.database.models_sqlalchemy import TrabajadorModel

class TrabajadorRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_trabajador_by_id(self, trabajador_id: int, empresa_id: int):
        """ Busca un trabajador, pero asegura que pertenezca a la empresa activa """
        return self.db.query(TrabajadorModel).filter(
            TrabajadorModel.id == trabajador_id,
            TrabajadorModel.empresa_id == empresa_id # 🔒 CANDADO MULTI-TENANT
        ).first()

    def get_all_by_empresa(self, empresa_id: int):
        """ Retorna todos los trabajadores activos de la empresa seleccionada """
        return self.db.query(TrabajadorModel).filter(
            TrabajadorModel.empresa_id == empresa_id,
            TrabajadorModel.estado == 'ACTIVO'
        ).all()

    def create(self, empresa_id: int, datos: dict):
        """ Crea un nuevo trabajador forzando la vinculación a la empresa activa """
        nuevo_trabajador = TrabajadorModel(
            empresa_id=empresa_id,
            dni=datos['dni'],
            nombres_apellidos=datos['nombres_apellidos'],
            fecha_ingreso=datos['fecha_ingreso'],
            sueldo_base=datos['sueldo_base'],
            tiene_asignacion_familiar=datos.get('tiene_asignacion_familiar', False),
            tiene_eps=datos.get('tiene_eps', False),
            sistema_pension=datos['sistema_pension'],
            tipo_comision_afp=datos.get('tipo_comision_afp')
        )
        self.db.add(nuevo_trabajador)
        self.db.commit()
        self.db.refresh(nuevo_trabajador)
        return nuevo_trabajador