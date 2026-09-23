from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def require_iso_datetime(value):
    if not isinstance(value, (str, datetime)):
        raise ValueError("Use an ISO 8601 datetime with an explicit timezone")
    return value


UTCDateTime = Annotated[
    AwareDatetime, BeforeValidator(require_iso_datetime), AfterValidator(to_utc)
]
SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class ErrorDetail(Schema):
    code: str
    message: str
    retryable: bool = False


class ErrorResponse(Schema):
    error: ErrorDetail
