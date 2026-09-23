from typing import Annotated

from pydantic import Field, StringConstraints

from backend.app.schemas.common import Schema

TurbineId = Annotated[int, Field(strict=True, ge=1, le=2)]


class TurbineRead(Schema):
    id: TurbineId
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class TurbineList(Schema):
    items: list[TurbineRead]
