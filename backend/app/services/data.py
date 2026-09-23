import hashlib
import json

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.schemas.data import DataSummary, TimeConfiguration, TurbineDataSummary


class DataService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def summary(self) -> DataSummary:
        try:
            audit = json.loads(self.settings.audit_file.read_text(encoding="utf-8"))
            items = []
            for source in audit["turbines"]:
                turbine_id = source["turbine_id"]
                if type(turbine_id) is not int or turbine_id not in (1, 2):
                    raise ValueError("Unknown turbine in audit")
                filename = f"turbine_{turbine_id}.csv"
                if source["file"] != filename:
                    raise ValueError("Audit filename must identify its turbine")
                with (self.settings.input_dir / filename).open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                fields = (
                    "turbine_id",
                    "file",
                    "sha256",
                    "rows",
                    "missing_percent",
                    "missing_10min_records",
                    "full_hours",
                    "partial_hours",
                    "empty_hours",
                    "january_2026_complete",
                    "records_from_february_2026",
                )
                items.append(
                    TurbineDataSummary(
                        **{key: source[key] for key in fields},
                        start_local=source["start"],
                        end_local=source["end"],
                        source_matches_audit=digest == source["sha256"],
                    )
                )
            if sorted(item.turbine_id for item in items) != [1, 2]:
                raise ValueError("Audit must contain both turbines exactly once")
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise AppError(
                503,
                "DATA_QUALITY_ERROR",
                "Исходные CSV или отчёт аудита недоступны либо имеют неверный формат.",
            ) from exc
        warnings = []
        if self.settings.missing_time_settings:
            warnings.append("Настройки времени исходных измерений ещё не подтверждены.")
        if any(not item.source_matches_audit for item in items):
            warnings.append("CSV изменился после аудита: обновите отчёт перед расчётом.")
        actuals = all(item.records_from_february_2026 > 0 for item in items)
        if not actuals:
            warnings.append("В исходных данных нет фактов за февраль для обеих турбин.")
        return DataSummary(
            time_configuration=TimeConfiguration(
                source_timezone=self.settings.source_timezone,
                timestamp_meaning=self.settings.timestamp_meaning,
                confirmed=not self.settings.missing_time_settings,
                missing_fields=self.settings.missing_time_settings,
            ),
            turbines=sorted(items, key=lambda item: item.turbine_id),
            february_actuals_available=actuals,
            warnings=warnings,
        )

    def require_current_audit(self) -> None:
        if any(not item.source_matches_audit for item in self.summary().turbines):
            raise AppError(
                409, "DATA_QUALITY_ERROR", "Исходные данные изменились; требуется новый аудит."
            )
