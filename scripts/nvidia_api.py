"""Check NVIDIA NIM connectivity or request advice on past validation results."""

import argparse
import json
from pathlib import Path

from src.nvidia_api import NvidiaClient, NvidiaError, NvidiaSettings


def training_summary(path: Path) -> dict:
    report = json.loads(path.read_text())
    if report.get("selection_months") != ["2025-11", "2025-12"]:
        raise ValueError("Ожидаются результаты отбора только за ноябрь–декабрь 2025.")
    if report.get("january_used_for_search") is not False:
        raise ValueError("Отчёт не подтверждает исключение января из подбора.")
    # Whitelist fields. January/February targets and raw observations are never sent.
    candidates = [
        {"config": row["config"], "validation_metrics": row["metrics"]}
        for row in report["ranking"][:5]
    ]
    if not candidates:
        raise ValueError("В отчёте нет завершённых кандидатов.")
    return {
        "selection_months": report["selection_months"],
        "best_candidates": candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "training-advice"])
    parser.add_argument(
        "--selection", type=Path, default=Path("artifacts/gfs-search/selection.json")
    )
    args = parser.parse_args()
    try:
        settings = NvidiaSettings()
        if args.action == "check":
            instructions = "Ответь коротко по-русски."
            data = {"question": "Соединение работает?"}
        else:
            data = training_summary(args.selection)
            instructions = (
                "Дай до трёх рекомендаций для следующего эксперимента прогноза ВЭС, по-русски. "
                "Используй только переданные конфигурации и метрики ноября–декабря 2025. "
                "Признаки погоды должны быть доступны на момент исторического прогноза. "
                "Январь и февраль исключены из подбора. Не придумывай улучшения или метрики. "
                "Рекомендации рассматривает разработчик; никаких команд к выполнению."
            )
        reply = NvidiaClient(settings).chat(instructions, data)
    except NvidiaError as error:
        parser.exit(1, f"{error}\n")
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(1, "Проверьте настройки NVIDIA и формат отчёта отбора.\n")
    print(f"NVIDIA NIM: {settings.model}\n{reply}")
    if args.action == "training-advice":
        print(
            "\nРекомендации не меняют настройки и не запускают обучение автоматически."
        )


if __name__ == "__main__":
    main()
