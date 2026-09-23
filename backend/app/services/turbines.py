from pathlib import Path

from pydantic import TypeAdapter

from backend.app.core.errors import AppError
from backend.app.schemas.turbine import TurbineList, TurbineRead


class TurbineService:
    def __init__(self, config_file: Path):
        turbines = TypeAdapter(list[TurbineRead]).validate_json(config_file.read_text())
        self._turbines = {turbine.id: turbine for turbine in turbines}
        if len(self._turbines) != len(turbines):
            raise ValueError("Duplicate turbine IDs in configuration")

    def get(self, turbine_id: int) -> TurbineRead:
        turbine = self._turbines.get(turbine_id)
        if turbine is None:
            raise AppError(404, "TURBINE_NOT_FOUND", "Турбина не найдена.")
        return turbine

    def list(self) -> TurbineList:
        return TurbineList(items=sorted(self._turbines.values(), key=lambda turbine: turbine.id))
