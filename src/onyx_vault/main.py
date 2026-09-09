"""ONYX entrypoint: boot screen, setup wizard, live session orchestration."""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

import typer
from groq import AsyncGroq
from rich.console import Console
from rich.live import Live
from rich.prompt import Prompt

from onyx_vault import __version__
from onyx_vault.config import ensure_groq_key, ensure_license, load_config, print_disclaimer_banner, update_groq_key
from onyx_vault.processor import NoteProcessor, ProcessorStats
from onyx_vault.recorder import AudioRecorder
from onyx_vault.shutdown import run_shutdown_pipeline
from onyx_vault.ui import build_dashboard, print_boot_screen
from onyx_vault.vault import VaultIndex

app = typer.Typer(
    add_completion=False,
    help="ONYX: The Cobalt Scarab — a condescending AI note-taker for Obsidian.",
)
console = Console()

SKIP_WARNING = (
    '⚠️  "Fine, skip it. But don\'t come crying to me when your Obsidian vault turns '
    'into an unorganized, chaotic pile of trash because you were too lazy to type '
    'four words."'
)

DEFAULTS = {
    "subject": "MISC",
    "professor": "Unknown",
    "lecture_num": "00",
    "topic": "Untitled",
}


def _ask_metadata() -> dict:
    console.print(
        "[bold bright_cyan]Alright, toddler. Answer these four questions before I "
        "lift a finger.[/]"
    )

    prompts = [
        ("subject", "Subject / Course Code (e.g. LAW101)"),
        ("professor", "Professor Name (e.g. Dr. Aris)"),
        ("lecture_num", "Lecture Number (e.g. 04)"),
        ("topic", "Specific Lecture Topic (e.g. Tort Law & Negligence)"),
    ]

    fields = {}
    skipped = False
    for key, label in prompts:
        value = Prompt.ask(f"[bright_cyan]{label}[/]", default="")
        if not value:
            skipped = True
            value = DEFAULTS[key]
        fields[key] = value

    if skipped:
        console.print(f"\n[bold red]{SKIP_WARNING}[/]\n")

    return fields


def _init_course_dir(vault_path: Path, meta: dict) -> Path:
    course_dir = vault_path / meta["subject"]
    course_dir.mkdir(parents=True, exist_ok=True)
    return course_dir


@app.callback(invoke_without_command=True)
def start(
    ctx: typer.Context,
    persona: str = typer.Option(
        "onyx",
        "--persona",
        help="Persona to use: 'onyx' (default, condescending) or 'academic' (neutral).",
    ),
) -> None:
    """Start an ONYX live note-taking session."""
    if ctx.invoked_subcommand is not None:
        return

    if persona not in ("onyx", "academic"):
        console.print(f"[bold red]Unknown persona '{persona}'. Use 'onyx' or 'academic'.[/]")
        raise typer.Exit(code=1)

    asyncio.run(_run_session(persona))


async def _run_session(persona: str) -> None:
    print_boot_screen(console)
    ensure_license()
    print_disclaimer_banner()
    cfg = load_config()

    meta = _ask_metadata()
    vault_path = Path(cfg["OBSIDIAN_VAULT_PATH"])
    course_dir = _init_course_dir(vault_path, meta)

    vault_index = VaultIndex(str(vault_path))
    ensure_groq_key()
    client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stats = ProcessorStats()

    recorder = AudioRecorder(loop, queue)
    processor = NoteProcessor(
        client=client,
        queue=queue,
        vault_index=vault_index,
        course_dir=course_dir,
        meta=meta,
        persona=persona,
        stats=stats,
    )

    processor_task = asyncio.create_task(processor.run())
    recorder.start()

    stop_requested = asyncio.Event()

    def _handle_sigint():
        console.print("\n[bold yellow]Ctrl+C detected. Fine. Let me clean up your mess.[/]")
        stop_requested.set()

    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
    except NotImplementedError:
        # Windows' default event loop policy doesn't support add_signal_handler.
        signal.signal(signal.SIGINT, lambda *_: loop.call_soon_threadsafe(_handle_sigint))

    console.print(f"[bold green]Recording started.[/] Course folder: [bright_cyan]{course_dir}[/]")
    console.print("[dim]Press Ctrl+C to stop and generate the final summary + Anki cards.[/]\n")

    with Live(console=console, refresh_per_second=2, screen=False) as live:
        while not stop_requested.is_set():
            panel = build_dashboard(
                is_recording=recorder.is_recording,
                queue_depth=queue.qsize(),
                tokens=stats.tokens_consumed,
                chunks=stats.chunks_processed,
                last_block=stats.last_block,
                note_path=stats.last_note_path or str(course_dir),
            )
            live.update(panel)
            await asyncio.sleep(0.5)

    recorder.stop()
    await queue.join()
    await processor.stop()
    await processor_task

    await run_shutdown_pipeline(client, processor.full_transcript_parts, course_dir, meta, console)
    console.print(
        "[bold bright_cyan]Session closed. Try not to embarrass yourself in the next lecture.[/]"
    )


@app.command()
def version() -> None:
    """Print the ONYX version."""
    console.print(f"ONYX: The Cobalt Scarab — v{__version__}")


def key() -> None:
    """Update the stored Groq API key without touching anything else."""
    update_groq_key()


app.command(name="key")(key)
app.command(name="config")(key)


if __name__ == "__main__":
    app()
