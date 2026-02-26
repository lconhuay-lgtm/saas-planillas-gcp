from sqlalchemy.orm import Session
from infrastructure.database.models_sqlalchemy import EmpresaModel

class EmpresaRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self):
        return self.db.query(EmpresaModel).all()

    def create(self, ruc: str, razon_social: str, regimen: str = 'GENERAL'):
        nueva_empresa = EmpresaModel(
            ruc=ruc, 
            razon_social=razon_social, 
            regimen_laboral=regimen
        )
        self.db.add(nueva_empresa)
        self.db.commit()
        self.db.refresh(nueva_empresa)
        return nueva_empresa