"""Environment / credential bootstrap for ONYX.

Reads GROQ_API_KEY and OBSIDIAN_VAULT_PATH from the environment, falling back
to ~/.onyx-vault/.env, and interactively prompting (and persisting) anything
still missing.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from dotenv import load_dotenv, set_key
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

CONFIG_DIR = Path.home() / ".onyx-vault"
ENV_PATH = CONFIG_DIR / ".env"
TEMP_DIR = CONFIG_DIR / "temp"

CHUNK_SECONDS = 300  # 5-minute recording interval

REQUIRED_KEYS = ["GROQ_API_KEY", "OBSIDIAN_VAULT_PATH"]

LICENSE_CODE_KEY = "ONYX_ACCESS_CODE"
LICENSE_ENDPOINT_KEY = "ONYX_LICENSE_ENDPOINT"
LICENSE_TIMEOUT_SECONDS = 10
LICENSE_USER_AGENT = "ONYX-CLI/1.0"

console = Console()


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load required config, prompting interactively for anything missing."""
    ensure_dirs()

    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH)

    missing = [key for key in REQUIRED_KEYS if not os.environ.get(key)]
    if missing:
        _prompt_for_missing(missing)

    vault_path = Path(os.environ["OBSIDIAN_VAULT_PATH"]).expanduser().resolve()
    if not vault_path.exists():
        console.print(
            f"[bold red]Oh, fantastic.[/] The vault path '{vault_path}' doesn't even "
            "exist. Creating it because apparently I have to do everything myself."
        )
        vault_path.mkdir(parents=True, exist_ok=True)

    return {
        "GROQ_API_KEY": os.environ["GROQ_API_KEY"],
        "OBSIDIAN_VAULT_PATH": str(vault_path),
    }


def _prompt_for_missing(missing: list[str]) -> None:
    ensure_dirs()
    if not ENV_PATH.exists():
        ENV_PATH.touch()

    console.print(
        "[bold bright_cyan]ONYX needs a couple of things before it can tolerate "
        "your presence.[/]"
    )
    for key in missing:
        if key == "GROQ_API_KEY":
            value = Prompt.ask("[bright_cyan]Enter your GROQ_API_KEY[/]", password=True)
        elif key == "OBSIDIAN_VAULT_PATH":
            value = Prompt.ask(
                "[bright_cyan]Enter the absolute path to your Obsidian vault[/]"
            )
        else:  # pragma: no cover - defensive, REQUIRED_KEYS is fixed
            value = Prompt.ask(f"[bright_cyan]Enter value for {key}[/]")

        os.environ[key] = value
        set_key(str(ENV_PATH), key, value)

    console.print(f"[dim]Saved to {ENV_PATH}. Try not to lose it.[/]\n")


def _get_machine_id() -> str:
    return str(uuid.getnode())


def _check_access_code(code: str, endpoint: str) -> bool:
    """Verify an access code + machine id against the Cloudflare Worker API."""
    query = urllib.parse.urlencode({"code": code, "machine_id": _get_machine_id()})
    url = f"{endpoint}?{query}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": LICENSE_USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=LICENSE_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False
    return payload.get("valid") is True


def ensure_license() -> None:
    """Gate ONYX behind a Cloudflare-verified access code before any recording starts.

    Reads ONYX_ACCESS_CODE from ~/.onyx-vault/.env; if missing, prompts for it
    interactively. Either way, the code is re-verified against the license API on
    every launch so a revoked code stops working even after being cached locally.
    """
    ensure_dirs()
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH)

    endpoint = os.environ.get(LICENSE_ENDPOINT_KEY, "").strip().rstrip("/")
    if not endpoint:
        console.print(
            f"[bold red]{LICENSE_ENDPOINT_KEY} is not set.[/] Add it to {ENV_PATH} "
            "(the base URL of your Cloudflare Worker license endpoint) before ONYX "
            "can verify anything."
        )
        sys.exit(1)

    code = os.environ.get(LICENSE_CODE_KEY)
    first_time = not code
    if not code:
        code = Prompt.ask("[bright_cyan]Enter your ONYX Access Code[/]")

    if not _check_access_code(code, endpoint):
        console.print(
            Panel(
                "[bold red]✗ Access denied.[/] That code did not verify against the "
                "license server. Fix your code — or your life choices — and try again.",
                title="[bold red]ONYX LICENSE CHECK FAILED[/]",
                border_style="red",
            )
        )
        sys.exit(1)

    if first_time:
        if not ENV_PATH.exists():
            ENV_PATH.touch()
        os.environ[LICENSE_CODE_KEY] = code
        set_key(str(ENV_PATH), LICENSE_CODE_KEY, code)
        console.print(f"[dim]License verified. Saved to {ENV_PATH} for future launches.[/]")
    else:
        console.print("[dim]License verified.[/]")


def print_disclaimer_banner() -> None:
    """Print the mandatory sarcastic recording-consent disclaimer, in ONYX's voice."""
    console.print(
        Panel(
            "[bold]Make sure you actually have permission from your professor to "
            "record this lecture[/] before running this, unless you're aiming for a "
            "guest spot in front of the academic integrity board.\n\n"
            "ONYX records what it hears; it doesn't pay your tuition if you get "
            "kicked out.",
            title="[bold red]⚠ LEGAL DISCLAIMER / ONYX VOICE[/]",
            border_style="red",
        )
    )
    console.print()
