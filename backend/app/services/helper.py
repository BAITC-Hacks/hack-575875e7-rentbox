"""Contextual site help using OpenAI GPT-6 Astra and server-owned evidence."""

import hashlib
import json
from collections import deque
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.core.config import BACKEND_DIR, PROJECT_DIR
from backend.app.core.errors import AppError
from backend.app.schemas.helper import (
    HelpAction,
    HelpAnswer,
    HelpGeneration,
    HelpRequest,
    HelpSource,
    HelpStatus,
)
from backend.app.services.forecasts import ForecastService

MODEL = "gpt-6-astra"
PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
SYSTEM_PROMPT = (PROMPTS / "helper-system.md").read_text(encoding="utf-8")
KNOWLEDGE = json.loads((PROMPTS / "helper-knowledge.json").read_text(encoding="utf-8"))
PROMPT_VERSION = (
    "helper-v1-"
    + hashlib.sha256(
        (SYSTEM_PROMPT + json.dumps(KNOWLEDGE, ensure_ascii=False)).encode()
    ).hexdigest()[:12]
)
VIEWS = {
    "overview": "Обзор",
    "forecast": "Прогноз",
    "agent": "AI-агент",
    "sources": "Источники данных",
    "history": "История",
}
_slots = BoundedSemaphore(2)
_requests: deque[float] = deque()
_limit_lock = Lock()


class HelperSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPENAI_",
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )
    api_key: SecretStr = SecretStr("")
    base_url: str = "https://api.openai.com/v1"
    helper_enabled: bool = True
    helper_reasoning_effort: Literal["low", "medium", "high"] = "low"
    helper_timeout_seconds: float = Field(default=40, ge=5, le=45)

    @field_validator("base_url")
    @classmethod
    def secure_endpoint(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError("Use an HTTPS API base URL without credentials or query parameters")
        return value.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.api_key.get_secret_value().strip())


def helper_status() -> HelpStatus:
    try:
        settings = HelperSettings()
        return HelpStatus(
            enabled=settings.helper_enabled,
            configured=settings.configured,
            available=settings.helper_enabled and settings.configured,
            prompt_version=PROMPT_VERSION,
        )
    except ValueError:
        return HelpStatus(
            enabled=False, configured=False, available=False, prompt_version=PROMPT_VERSION
        )


def build_evidence(payload: HelpRequest, service: ForecastService) -> tuple[list[dict], dict]:
    """Read the selected run ourselves; never accept browser-supplied power or metrics."""
    evidence = [dict(item) for item in KNOWLEDGE]
    actions = {
        f"navigate.{view}": HelpAction(type="navigate", view=view, label=f"Открыть: {label}")
        for view, label in VIEWS.items()
    }
    settings = service.settings
    evidence.append(
        {
            "id": "platform.status",
            "title": "Текущие настройки платформы",
            "view": "agent",
            "data": {
                "forecast_agent_configured": service.engine is not None,
                "source_timezone": settings.source_timezone,
                "timestamp_meaning": settings.timestamp_meaning,
                "time_configuration_confirmed": settings.time_configuration_confirmed,
                "research_mode": settings.allow_research_time_settings,
                "forecast_configuration_ready": not settings.blocking_time_settings,
            },
        }
    )
    try:
        summary = service.data.summary()
        evidence.append(
            {
                "id": "data.summary",
                "title": "Аудит исходных измерений",
                "view": "sources",
                "data": summary.model_dump(mode="json"),
            }
        )
    except AppError:
        evidence.append(
            {
                "id": "data.summary",
                "title": "Доступность исходных измерений",
                "view": "sources",
                "data": {"unavailable": True, "note": "Сервер не смог прочитать аудит измерений."},
            }
        )
    # Synthetic UI scenarios never inherit a cached real forecast's provenance.
    if payload.run_id and payload.context.mode == "forecast":
        try:
            run = service.store.get_run(payload.run_id)
            selected = run.model_dump(mode="json", exclude={"events", "error"})
            if run.error:
                selected["error_code"] = run.error.code
            selected["warnings"] = [value[:500] for value in run.warnings[:5]]
            if run.status == "completed":
                result = service.store.get_result(run.run_id)
                selected["model_version"] = result.model_version
                selected["unit"] = result.unit
                selected["training_data_available_until"] = (
                    result.training_data_available_until.isoformat()
                )
                selected["turbines"] = []
                for series in result.series:
                    points = series.points
                    values = [point.predicted_power for point in points]
                    selected["turbines"].append(
                        {
                            "id": series.turbine_id,
                            "hours": len(values),
                            "first_valid_time": points[0].valid_time.isoformat(),
                            "last_valid_time": points[-1].valid_time.isoformat(),
                            "min_power": min(values),
                            "max_power": max(values),
                            "mean_power": sum(values) / len(values),
                            "weather_sources": [
                                source.model_dump(mode="json")
                                for source in series.weather.sources[:4]
                            ],
                            "weather_source_count": len(series.weather.sources),
                        }
                    )
                actions["download_csv"] = HelpAction(
                    type="download_csv", label="Скачать CSV этого выпуска", run_id=run.run_id
                )
            evidence.append(
                {
                    "id": "selected_run",
                    "title": "Выбранный выпуск из базы",
                    "view": "forecast",
                    "data": selected,
                }
            )
        except AppError:
            evidence.append(
                {
                    "id": "selected_run",
                    "title": "Выбранный выпуск недоступен",
                    "view": "history",
                    "data": {"unavailable": True, "note": "Выберите доступный выпуск в Истории."},
                }
            )
    # This is explicitly the bundled report, not a claim about every selected model/run.
    try:
        metrics = json.loads((PROJECT_DIR / "artifacts/gfs-model/metrics.json").read_text())
        evidence.append(
            {
                "id": "model.january",
                "title": "Январский отчёт поставляемой модели",
                "view": "overview",
                "data": {
                    "period": "2026-01",
                    "model": metrics["winner"],
                    "artifact_sha256": metrics["artifact_sha256"],
                    "metrics": metrics["january"]["overall"],
                    "unit": "normalized_power_0_to_1",
                    "note": (
                        "Мониторинг экспериментов, не новый независимый тест. Не метрики февраля."
                    ),
                },
            }
        )
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return evidence, actions


def local_help(
    payload: HelpRequest, evidence: list[dict], actions: dict, warning: str
) -> HelpAnswer:
    """Deterministic navigation aid, explicitly labelled as ordinary help."""
    message = payload.message.casefold()
    topics = [
        (("симул", "сценари"), "guide.simulation"),
        (("тема", "тёмн", "темн", "зрени", "язык"), "guide.appearance"),
        (("csv", "скача", "экспорт"), "guide.export"),
        (("феврал", "факт", "измерен"), "guide.limits"),
        (("мвт", "номин", "точност", "mae", "rmse", "процент", "мощност"), "guide.units"),
        (("врем", "часов", "as_of", "utc", "предупрежд", "допущен"), "guide.time"),
        (("погод", "источник", "ветер", "температур"), "guide.sources"),
        (("истори", "прошл", "ревизи"), "guide.history"),
        (("обуч", "nvidia", "gpu", "датчик"), "guide.training"),
        (("агент", "ошиб", "этап", "статус"), "guide.agent"),
        (("прогноз", "расч", "запуст", "начать"), "guide.forecast"),
    ]
    source_id = next(
        (topic for words, topic in topics if any(w in message for w in words)), "guide.overview"
    )
    if payload.context.mode == "simulation" and source_id != "guide.appearance":
        source_id = "guide.simulation"
    source = next(item for item in evidence if item["id"] == source_id)
    buttons = [actions[f"navigate.{source['view']}"]]
    if source_id == "guide.export" and "download_csv" in actions:
        buttons.insert(0, actions["download_csv"])
    return HelpAnswer(
        provider="local_help",
        text=source["text"],
        sources=[HelpSource(**{k: source[k] for k in ("id", "title", "view")})],
        actions=buttons,
        warning=warning,
        prompt_version=PROMPT_VERSION,
    )


def _request_slot() -> bool:
    with _limit_lock:
        now = monotonic()
        while _requests and now - _requests[0] >= 60:
            _requests.popleft()
        if len(_requests) >= 20 or not _slots.acquire(blocking=False):
            return False
        _requests.append(now)
        return True


def answer_help(payload: HelpRequest, service: ForecastService) -> HelpAnswer:
    evidence, actions = build_evidence(payload, service)

    def fallback(message: str) -> HelpAnswer:
        return local_help(payload, evidence, actions, message)

    try:
        settings = HelperSettings()
    except ValueError:
        return fallback("ASTRA недоступна: проверьте серверные настройки OpenAI.")
    if not settings.helper_enabled or not settings.configured:
        return fallback("ASTRA пока не подключена. Доступна справка по платформе.")
    if not _request_slot():
        return fallback("Помощник занят. Повторите вопрос через минуту; пока доступна справка.")
    try:
        schema = HelpGeneration.model_json_schema()
        schema["properties"]["source_ids"]["items"]["enum"] = [e["id"] for e in evidence]
        schema["properties"]["action_ids"]["items"]["enum"] = list(actions)
        with httpx.Client(
            timeout=httpx.Timeout(settings.helper_timeout_seconds, connect=5),
            follow_redirects=False,
        ) as client:
            response = client.post(
                settings.base_url + "/responses",
                headers={"Authorization": "Bearer " + settings.api_key.get_secret_value()},
                json={
                    "model": MODEL,
                    "store": False,
                    "max_output_tokens": 2400,
                    "reasoning": {"effort": settings.helper_reasoning_effort},
                    "instructions": SYSTEM_PROMPT,
                    "input": [
                        {
                            "role": "developer",
                            "content": json.dumps(
                                {
                                    "platform_evidence": evidence,
                                    "allowed_actions": {
                                        k: v.model_dump() for k, v in actions.items()
                                    },
                                },
                                ensure_ascii=False,
                                allow_nan=False,
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "question": payload.message,
                                    "ui_context": payload.context.model_dump(mode="json"),
                                    "conversation_history": [
                                        m.model_dump() for m in payload.history
                                    ],
                                },
                                ensure_ascii=False,
                                allow_nan=False,
                            ),
                        },
                    ],
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "platform_help",
                            "strict": True,
                            "schema": schema,
                        }
                    },
                },
            )
            response.raise_for_status()
            body = response.json()
        if body.get("status") != "completed":
            return fallback("ASTRA не завершила ответ. Повторите вопрос; пока доступна справка.")
        returned_model = body.get("model", "")
        if returned_model != MODEL and not returned_model.startswith(MODEL + "-"):
            return fallback("Сервис вернул другую модель вместо ASTRA. Проверьте подключение.")
        text = "".join(
            content["text"]
            for item in body["output"]
            if item.get("type") == "message"
            for content in item.get("content", [])
            if content.get("type") == "output_text"
        )
        generated = HelpGeneration.model_validate_json(text)
        sources = {
            item["id"]: HelpSource(**{k: item[k] for k in ("id", "title", "view")})
            for item in evidence
        }
        if (
            not set(generated.source_ids) <= sources.keys()
            or not set(generated.action_ids) <= actions.keys()
        ):
            raise ValueError("Unrecognized source or action")
        return HelpAnswer(
            provider="openai",
            model=returned_model,
            text=generated.text,
            sources=[sources[key] for key in dict.fromkeys(generated.source_ids)],
            actions=[actions[key] for key in dict.fromkeys(generated.action_ids)],
            prompt_version=PROMPT_VERSION,
        )
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status in (401, 403):
            message = "OpenAI не подтвердил доступ к ASTRA. Проверьте серверный ключ и права."
        elif status == 429:
            message = "Достигнут лимит OpenAI. Пока доступна справка по платформе."
        elif status == 404:
            message = "ASTRA недоступна по указанному адресу OpenAI. Проверьте настройки сервера."
        else:
            message = "OpenAI временно недоступен. Пока доступна справка по платформе."
        return fallback(message)
    except httpx.TimeoutException:
        return fallback("ASTRA не ответила вовремя. Повторите вопрос; пока доступна справка.")
    except httpx.HTTPError:
        return fallback("Не удалось связаться с OpenAI. Пока доступна справка по платформе.")
    except (ValueError, KeyError, TypeError, AttributeError):
        return fallback("Ответ ASTRA не удалось проверить. Пока доступна справка по платформе.")
    finally:
        _slots.release()
