"""Configure site help without exposing keys or copying Codex credentials."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSIGNMENT = re.compile(r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(.*)")
MANAGED = {"OPENAI_HELPER_AUTH_MODE", "OPENAI_HELPER_ENABLED", "OPENAI_API_KEY"}


@dataclass
class Binding:
    raw: str
    key: str | None = None
    value: str | None = None


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def bindings(text: str) -> list[Binding]:
    """Preserve comments and multiline values; never interpret dotenv as shell."""
    lines = text.splitlines(keepends=True)
    result: list[Binding] = []
    index = 0
    while index < len(lines):
        raw = lines[index]
        index += 1
        match = ASSIGNMENT.match(raw)
        if not match:
            result.append(Binding(raw))
            continue
        key, value = match.groups()
        if value.startswith(("'", '"')):
            quote = value[0]
            offset = 1
            escaped = False
            while True:
                if offset >= len(value):
                    if index == len(lines):
                        raise ValueError("Незакрытая кавычка в .env. Исправьте файл и повторите.")
                    raw += lines[index]
                    value += lines[index]
                    index += 1
                    continue
                char = value[offset]
                if char == quote and not escaped:
                    value = value[1:offset]
                    break
                escaped = char == "\\" and not escaped
                offset += 1
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        result.append(Binding(raw, key, value))
    return result


def write_settings(path: Path, updates: dict[str, str]) -> None:
    """Replace only selected bindings using an owner-only atomic write."""
    if path.is_symlink():
        raise ValueError(f"{path.name} — символическая ссылка; автоматическая запись отменена.")
    original = read_text(path)
    records = bindings(original)
    text = "".join(item.raw for item in records if item.key not in updates)
    if text and not text.endswith(("\n", "\r")):
        text += "\n"
    text += "\n# Помощник Windcast: ./run.sh settings\n"
    text += "".join(
        f"{key}={json.dumps(value, ensure_ascii=False)}\n" for key, value in updates.items()
    )
    handle_id, name = tempfile.mkstemp(prefix=".env.openai-", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(handle_id, 0o600)
        with os.fdopen(handle_id, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if read_text(path) != original:
            raise ValueError("Файл .env изменился во время настройки. Повторите сохранение.")
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def chatgpt_logged_in(binary: str) -> bool:
    try:
        result = subprocess.run(
            [binary, "login", "status"], capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    # Do not display status output: an API-key login may include a masked key.
    return result.returncode == 0 and "chatgpt" in (result.stdout + result.stderr).lower()


def configure_chatgpt() -> dict[str, str]:
    binary = shutil.which("codex")
    if not binary:
        raise ValueError("Codex CLI не найден. Установите его отдельно или выберите API key.")
    if not chatgpt_logged_in(binary):
        if not sys.stdin.isatty():
            raise ValueError("Сначала выполните codex login в терминале и войдите через ChatGPT.")
        print("Открываю штатный вход Codex через ChatGPT. Завершите вход в браузере.")
        result = subprocess.run([binary, "login"], check=False)
        if result.returncode != 0 or not chatgpt_logged_in(binary):
            raise ValueError("Вход через ChatGPT не подтверждён. Настройки не изменены.")
    print("Используется существующий вход Codex через ChatGPT. Секреты входа не копируются.")
    return {"OPENAI_HELPER_AUTH_MODE": "chatgpt", "OPENAI_HELPER_ENABLED": "true"}


def configure_api_key() -> dict[str, str]:
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            key = getpass.getpass("Вставьте токен OpenAI (API key, ввод скрыт): ").strip()
        except getpass.GetPassWarning as exc:
            raise ValueError(
                "Скрытый ввод недоступен. Запустите ./run.sh settings в терминале."
            ) from exc
    if len(key) < 12 or any(char.isspace() or not char.isprintable() for char in key):
        raise ValueError("Пустой или некорректный API key. Настройки не изменены.")
    if "${" in key:
        raise ValueError("Введите сам API key без dotenv-подстановок.")
    return {
        "OPENAI_HELPER_AUTH_MODE": "api_key", "OPENAI_HELPER_ENABLED": "true",
        "OPENAI_API_KEY": key,
    }


def configure(mode: str) -> None:
    paths = [ROOT / ".env"]
    override = ROOT / "backend/.env"
    if override.exists() and any(item.key in MANAGED for item in bindings(read_text(override))):
        paths.append(override)
    # Check every target before collecting a secret or starting login.
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"{path.name} — символическая ссылка; автоматическая запись отменена.")
        bindings(read_text(path))
    if mode == "chatgpt":
        updates = configure_chatgpt()
    elif mode == "api_key":
        updates = configure_api_key()
    else:
        updates = {"OPENAI_HELPER_ENABLED": "false"}
    for path in paths:
        write_settings(path, updates)
    print("Настройки сохранены в .env, права доступа 600. Остальные переменные сохранены.")
    if len(paths) > 1:
        print("Совпадающие настройки backend/.env также обновлены, чтобы не перекрывать выбор.")
    overrides = [
        name for name in updates if name in os.environ and os.environ[name] != updates[name]
    ]
    if overrides:
        print("В окружении уже заданы другие значения: " + ", ".join(overrides) + ".")
        print("Они имеют приоритет над .env. Уберите эти переменные перед перезапуском.")
    if mode == "chatgpt":
        print(
            "ChatGPT: только локальная проверка, "
            "отдельная история .run/chatgpt/forecasts.duckdb."
        )
    elif mode == "api_key":
        print("API key: прежний запуск через Docker или локальное окружение.")
    else:
        print("ASTRA отключена. На сайте остаётся обычная справка платформы.")
    print("Применить настройки: ./run.sh all")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("chatgpt", "api_key", "off"))
    args = parser.parse_args()
    mode = args.mode
    if mode is None:
        print("\nНастройки OpenAI — помощник Windcast")
        print("  1  Аккаунт ChatGPT — существующий вход Codex, локальная проверка")
        print("  2  API key — вставить токен OpenAI, подходит для развёртывания")
        print("  3  Отключить ASTRA — оставить справку платформы")
        print("  0  Назад без изменений")
        selected = input("Выберите способ подключения [1]: ").strip() or "1"
        if selected == "0":
            return
        mode = {"1": "chatgpt", "2": "api_key", "3": "off"}.get(selected)
        if mode is None:
            raise ValueError("Нет такого пункта. Выберите 1, 2, 3 или 0.")
    configure(mode)


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print("\nНастройка отменена.", file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, ValueError) as error:
        print(f"Ошибка настройки: {error}", file=sys.stderr)
        raise SystemExit(1) from None
