from abc import ABC, abstractmethod
from typing import List, Dict

class ITrabajadorRepository(ABC):
    @abstractmethod
    def get_all_by_empresa(self, empresa_id: int) -> List:
        pass

class IEmpresaRepository(ABC):
    @abstractmethod
    def get_empresa_by_id(self, empresa_id: int):
        pass