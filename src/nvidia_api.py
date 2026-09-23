"""Optional NVIDIA NIM explanations; power forecasts remain model outputs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class NvidiaSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NVIDIA_",
        env_file=(ROOT / ".env", ROOT / "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    enabled: bool = False
    api_key: SecretStr = SecretStr("")
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model: str = Field(default="nvidia/llama-3.3-nemotron-super-49b-v1.5", min_length=1)
    timeout_seconds: float = Field(default=20, ge=1, le=60)

    @field_validator("base_url")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
        parts = urlsplit(value)
        local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError(
                "Use an API base URL without credentials, query or fragment"
            )
        if parts.scheme != "https" and not (parts.scheme == "http" and local):
            raise ValueError("Use HTTPS, or HTTP for a local NIM")
        return value.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.api_key.get_secret_value().strip())


class NvidiaError(RuntimeError):
    """A safe message suitable for API responses; never include upstream bodies."""


class NvidiaClient:
    def __init__(
        self, settings: NvidiaSettings, transport: httpx.BaseTransport | None = None
    ):
        self.settings = settings
        self.transport = transport

    def chat(self, instructions: str, data: dict) -> str:
        settings = self.settings
        if not settings.enabled:
            raise NvidiaError("NVIDIA API выключен: задайте NVIDIA_ENABLED=true.")
        if not settings.configured:
            raise NvidiaError(
                "NVIDIA_API_KEY не задан. Добавьте ключ в локальный .env."
            )
        try:
            with httpx.Client(
                timeout=httpx.Timeout(settings.timeout_seconds, connect=5),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = client.post(
                    settings.base_url + "/chat/completions",
                    headers={
                        "Authorization": "Bearer " + settings.api_key.get_secret_value()
                    },
                    json={
                        "model": settings.model,
                        "temperature": 0,
                        "max_tokens": 512,
                        "messages": [
                            {"role": "system", "content": "/no_think\n" + instructions},
                            {
                                "role": "user",
                                "content": json.dumps(
                                    data, ensure_ascii=False, allow_nan=False
                                ),
                            },
                        ],
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if (
                    not isinstance(content, str)
                    or not content.strip()
                    or len(content) > 8000
                ):
                    raise ValueError("Invalid model content")
                return content.strip()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status in (401, 403):
                message = "NVIDIA API отклонил ключ или доступ к модели."
            elif status == 429:
                message = "Лимит NVIDIA API исчерпан; повторите запрос позже."
            elif status == 404:
                message = "Модель или адрес NVIDIA API не найдены; проверьте настройки."
            else:
                message = f"NVIDIA API вернул HTTP {status}."
            raise NvidiaError(message) from None
        except httpx.TimeoutException:
            raise NvidiaError("NVIDIA API не ответил за отведённое время.") from None
        except httpx.HTTPError:
            raise NvidiaError("Не удалось связаться с NVIDIA API.") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise NvidiaError("NVIDIA API вернул некорректный ответ.") from None


class Explanation(BaseModel):
    provider: Literal["policy", "nvidia"]
    model: str | None = None
    text: str
    warning: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def explain_forecast(
    forecast,
    *,
    settings: NvidiaSettings | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Explanation:
    """Only aggregates of an already computed forecast are sent to the LLM."""
    fallback = forecast.analysis.summary
    try:
        settings = settings if settings is not None else NvidiaSettings()
    except ValueError:
        return Explanation(
            provider="policy",
            text=fallback,
            warning="Проверьте настройки NVIDIA в .env.",
        )
    if not settings.enabled:
        return Explanation(provider="policy", text=fallback)
    data = {
        "as_of": forecast.as_of.isoformat(),
        "horizon_hours": forecast.horizon_hours,
        "unit": "normalized_power_0_to_1",
        "model_version": forecast.model_version,
        "time_settings": "UTC+5 and interval_start are unconfirmed research assumptions",
        "turbines": [],
    }
    for series in forecast.series:
        values = [point.predicted_power for point in series.points]
        data["turbines"].append(
            {
                "id": series.turbine_id,
                "hours": len(values),
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / len(values),
                "max_hourly_change": max(abs(b - a) for a, b in pairwise(values)),
            }
        )
    try:
        text = NvidiaClient(settings, transport).chat(
            "Кратко поясни прогноз ВЭС по-русски, до 150 слов. Используй только переданную "
            "сводку. Это пояснение уже рассчитанного прогноза. Не меняй значения, не придумывай "
            "фактическую погоду, причины остановок, точность, номинальную мощность или деньги. "
            "Значения имеют нормализованную шкалу 0–1; база нормализации не подтверждена. "
            "Явно укажи исследовательские временные допущения.",
            data,
        )
        return Explanation(provider="nvidia", model=settings.model, text=text)
    except NvidiaError as error:
        return Explanation(provider="policy", text=fallback, warning=str(error))
