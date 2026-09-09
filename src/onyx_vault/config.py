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
from pathlib import Path

from dotenv import load_dotenv, set_key
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from onyx_vault.auth import get_machine_id

CONFIG_DIR = Path.home() / ".onyx-data"
ENV_PATH = CONFIG_DIR / ".env"
TEMP_DIR = CONFIG_DIR / "temp"

CHUNK_SECONDS = 300  # 5-minute recording interval

REQUIRED_KEYS = ["GROQ_API_KEY", "OBSIDIAN_VAULT_PATH"]

LICENSE_CODE_KEY = "ONYX_LICENSE_KEY"
LICENSE_ENDPOINT_KEY = "ONYX_LICENSE_ENDPOINT"
DEFAULT_LICENSE_ENDPOINT = "https://onyx-license-worker.priyor13.workers.dev"
LICENSE_TIMEOUT_SECONDS = 10
LICENSE_USER_AGENT = "ONYX-CLI/1.0"

console = Console()


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load required config, prompting interactively for anything missing."""
    ensure_dirs()

    load_dotenv(dotenv_path=ENV_PATH, override=True)

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


def ensure_groq_key() -> str:
    """Guarantee GROQ_API_KEY is set, prompting in the CLI instead of failing silently.

    Called right before audio capture starts, on top of the load_config() check,
    so a key that was blanked out or revoked mid-session still gets caught.
    """
    ensure_dirs()
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    value = os.environ.get("GROQ_API_KEY", "").strip()
    if not value:
        console.print("[bold yellow][ONYX][/] GROQ_API_KEY missing.")
        return update_groq_key()
    return value


def update_groq_key() -> str:
    """Interactively prompt for a new Groq API key and persist it immediately."""
    ensure_dirs()
    if not ENV_PATH.exists():
        ENV_PATH.touch()

    value = Prompt.ask("[bright_cyan][ONYX] Enter new Groq API Key[/]", password=True)
    os.environ["GROQ_API_KEY"] = value
    set_key(str(ENV_PATH), "GROQ_API_KEY", value)
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    console.print(f"[bold green][ONYX][/] Groq API key updated. Saved to {ENV_PATH}.")
    return value


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


class LicenseCheckResult:
    VALID = "valid"
    INVALID = "invalid"
    NETWORK_ERROR = "network_error"
    DEVICE_MISMATCH = "device_mismatch"


def _check_access_code(code: str, endpoint: str) -> str:
    """Verify a license key + machine id against the Cloudflare Worker API.

    Returns a LicenseCheckResult constant. Network/timeout/malformed-response
    failures are reported distinctly from an explicit invalid/expired verdict
    from the worker, and a 403 (key already bound to a different machine) is
    reported distinctly again, so callers can show the right message instead
    of conflating "server unreachable" with "bad key" with "wrong device".
    """
    query = urllib.parse.urlencode({"key": code, "machine_id": get_machine_id()})
    url = f"{endpoint}/verify?{query}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": LICENSE_USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=LICENSE_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            return LicenseCheckResult.DEVICE_MISMATCH
        return LicenseCheckResult.NETWORK_ERROR
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return LicenseCheckResult.NETWORK_ERROR
    return LicenseCheckResult.VALID if payload.get("valid") is True else LicenseCheckResult.INVALID


MAX_LICENSE_ATTEMPTS = 3

# Machine ids exempt from license verification entirely (dev/owner devices).
# Get a machine's id by running: python -c "from onyx_vault.auth import get_machine_id; print(get_machine_id())"
WHITELISTED_MACHINE_IDS = {
    "5313588979331e19",  # this device
    # "BROTHERS_MACHINE_ID_HERE",
}


def ensure_license() -> None:
    """Gate ONYX behind a Cloudflare-verified license key before any recording starts.

    Reads ONYX_LICENSE_KEY from ~/.onyx-vault/.env; if missing or rejected,
    prompts for it interactively in the terminal (up to MAX_LICENSE_ATTEMPTS
    tries) instead of requiring a manual .env edit. ONYX_LICENSE_ENDPOINT falls
    back to DEFAULT_LICENSE_ENDPOINT so a missing endpoint var never halts the
    app. The key is re-verified against the license API on every launch so a
    revoked key stops working even after being cached locally.
    """
    ensure_dirs()
    load_dotenv(dotenv_path=ENV_PATH, override=True)

    if get_machine_id() in WHITELISTED_MACHINE_IDS:
        console.print("[bold green][ONYX][/] Whitelisted device detected. Skipping license check.")
        return

    endpoint = os.environ.get(LICENSE_ENDPOINT_KEY, "").strip().rstrip("/") or DEFAULT_LICENSE_ENDPOINT

    code = os.environ.get(LICENSE_CODE_KEY)
    if not code:
        console.print("[bold yellow][ONYX][/] License key not found.")

    attempts = 0
    while True:
        if not code:
            code = Prompt.ask("[bright_cyan][ONYX] Please enter your license key[/]", password=True)

        result = _check_access_code(code, endpoint)

        if result == LicenseCheckResult.NETWORK_ERROR:
            console.print(
                Panel(
                    "[bold red]✗ Could not reach the license server.[/] The Cloudflare "
                    f"Worker at {endpoint} timed out or returned an unreadable response. "
                    "Check your network connection and try again.",
                    title="[bold red]ONYX LICENSE CHECK FAILED[/]",
                    border_style="red",
                )
            )
            sys.exit(1)

        if result == LicenseCheckResult.VALID:
            break

        if result == LicenseCheckResult.DEVICE_MISMATCH:
            console.print(
                "[bold red][ONYX] Error: This license key is already in use on "
                "another computer.[/]"
            )
            sys.exit(1)

        attempts += 1
        console.print("[bold red][ONYX][/] Invalid license key. Please try again.")
        code = None
        if attempts >= MAX_LICENSE_ATTEMPTS:
            console.print(
                Panel(
                    "[bold red]Error: Invalid or inactive license key.[/] Please check "
                    "your credentials and try again.",
                    title="[bold red]ONYX LICENSE CHECK FAILED[/]",
                    border_style="red",
                )
            )
            sys.exit(1)

    if not ENV_PATH.exists():
        ENV_PATH.touch()
    os.environ[LICENSE_CODE_KEY] = code
    set_key(str(ENV_PATH), LICENSE_CODE_KEY, code)
    console.print(f"[bold green][ONYX] License verified successfully![/] Saved to {ENV_PATH}.")


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
