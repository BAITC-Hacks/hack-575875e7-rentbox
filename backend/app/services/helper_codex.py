"""Local-only ChatGPT authentication through the installed official Codex CLI.

Credentials stay in Codex's credential store. Never extract or copy OAuth tokens.
The website gets a bounded, structured answer, not a general Codex execution API.
"""

import json
import os
import shutil
import signal
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic

MODEL = "gpt-6-astra"
_login_lock = Lock()
_login_cache: tuple[float, bool] = (0, False)


class CodexHelpError(Exception):
    """A safe user-facing message; never include raw CLI output."""


def _environment() -> dict[str, str]:
    # Do not expose application keys, shell hooks or the parent agent's session.
    keys = (
        "PATH", "HOME", "CODEX_HOME", "LANG", "LC_ALL", "TMPDIR",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "no_proxy",
    )
    return {key: os.environ[key] for key in keys if key in os.environ}


def chatgpt_configured() -> bool:
    global _login_cache
    with _login_lock:
        now = monotonic()
        if now - _login_cache[0] < 15:
            return _login_cache[1]
        binary = shutil.which("codex")
        available = False
        if binary:
            try:
                result = subprocess.run(
                    [binary, "login", "status"], capture_output=True, text=True,
                    timeout=4, env=_environment(), check=False,
                )
                available = result.returncode == 0 and "using ChatGPT" in (
                    result.stdout + result.stderr
                )
            except (OSError, subprocess.SubprocessError):
                pass
        _login_cache = (now, available)
        return available


def generate_chatgpt(
    *, instructions: str, evidence: dict, question: dict, schema: dict,
    timeout: float, reasoning: str,
) -> tuple[str, str]:
    binary = shutil.which("codex")
    if not binary or not chatgpt_configured():
        raise CodexHelpError("Войдите в ChatGPT через ./run.sh settings на этом компьютере.")
    with TemporaryDirectory(prefix="windcast-help-") as directory:
        root = Path(directory)
        prompt = root / "instructions.md"
        output = root / "answer.json"
        output_schema = root / "schema.json"
        prompt.write_text(instructions, encoding="utf-8")
        output_schema.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
        config = {
            "model_provider": "openai",
            "forced_login_method": "chatgpt",
            "model_reasoning_effort": reasoning,
            "model_instructions_file": str(prompt),
            "developer_instructions": json.dumps(evidence, ensure_ascii=False, allow_nan=False),
            "approval_policy": "never",
            "project_doc_max_bytes": 0,
            "web_search": "disabled",
            "history.persistence": "none",
            "analytics.enabled": False,
            "log_dir": str(root / "logs"),
            "features.skip_host_skill_discovery": True,
        }
        # Isolate configuration from the user's coding setup and remove executable tools.
        for feature in (
            "shell_tool", "unified_exec", "apps", "plugins", "hooks", "multi_agent",
            "browser_use", "browser_use_external", "computer_use", "image_generation",
            "code_mode", "code_mode_host", "view_image", "skill_search", "memories",
            "goals", "sleep_tool", "remote_plugin", "workspace_dependencies",
        ):
            config[f"features.{feature}"] = False
        command = [
            binary, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
            "--skip-git-repo-check", "--sandbox", "read-only", "--model", MODEL,
            "--cd", directory, "--json", "--color", "never",
            "--output-schema", str(output_schema), "--output-last-message", str(output),
        ]
        for key, value in config.items():
            command.extend(["-c", key + "=" + json.dumps(value, ensure_ascii=False)])
        command.append("-")
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, cwd=directory, env=_environment(), start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(
                    json.dumps(question, ensure_ascii=False, allow_nan=False), timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise CodexHelpError("ASTRA не ответила вовремя. Попробуйте ещё раз.") from None
        except OSError:
            raise CodexHelpError("Не удалось запустить локальный Codex CLI.") from None
        if process.returncode:
            # Classify without disclosing credentials, account details or upstream responses.
            reason = (stdout + stderr).casefold()
            if "limit" in reason or "quota" in reason or "429" in reason:
                message = "Достигнут лимит аккаунта ChatGPT. Повторите позже или выберите API key."
            elif "not supported" in reason or "model_not_found" in reason:
                message = "Этот аккаунт ChatGPT не предоставляет доступ к GPT-6 Astra."
            else:
                message = "ChatGPT не завершил запрос. Проверьте вход через ./run.sh settings."
            raise CodexHelpError(message)
        completed = False
        for line in stdout.splitlines():
            event = json.loads(line)
            if event.get("type") == "turn.completed":
                completed = True
            if event.get("type") == "item.completed" and event.get("item", {}).get("type") not in (
                "agent_message", "reasoning", "error",
            ):
                raise CodexHelpError("Ответ помощника содержал недопустимое действие.")
        if not completed or not output.is_file() or output.stat().st_size > 32_000:
            raise CodexHelpError("ASTRA не вернула полный ответ. Попробуйте ещё раз.")
        return output.read_text(encoding="utf-8"), MODEL
