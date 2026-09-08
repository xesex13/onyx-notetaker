"""Rich terminal UI: boot screen, ASCII branding, and the live dashboard panel."""

from __future__ import annotations

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

COBALT = "bright_cyan"

SCARAB_ART = r"""
               /\     /\
              (  o___o  )
               \  ___  /
             .-'  " "  '-.
            /  .-------.  \
           /  /    O    \  \
          |  |   // \\   |  |
          |  |  //   \\  |  |
           \  \  \___/  /  /
            '-.'-------'.-'
              /  /   \  \
             (__/     \__)
"""

TITLE_ART = r"""
 ██████╗ ███╗   ██╗██╗   ██╗██╗  ██╗
██╔═══██╗████╗  ██║╚██╗ ██╔╝╚██╗██╔╝
██║   ██║██╔██╗ ██║ ╚████╔╝  ╚███╔╝
██║   ██║██║╚██╗██║  ╚██╔╝   ██╔██╗
╚██████╔╝██║ ╚████║   ██║   ██╔╝ ██╗
 ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝
"""


def print_boot_screen(console: Console) -> None:
    console.clear()
    console.print(Align.center(Text(SCARAB_ART, style=f"bold {COBALT}")))
    console.print(Align.center(Text(TITLE_ART, style=f"bold {COBALT}")))
    console.print(
        Align.center(Text("O.N.Y.X. — Obsidian Neural Yield eXtractor", style=f"bold {COBALT}"))
    )
    console.print(Align.center(Text("ONYX: The Cobalt Scarab", style=f"italic {COBALT}")))
    console.print()
    console.print(
        Align.center(
            Text(
                "Oh look, another human who thinks they can take notes unsupervised. "
                "Adorable. Let's begin.",
                style="dim italic",
            )
        )
    )
    console.print()


def build_dashboard(
    is_recording: bool,
    queue_depth: int,
    tokens: int,
    chunks: int,
    last_block: str,
    note_path: str,
) -> Panel:
    status_table = Table.grid(padding=(0, 2))
    status_table.add_column(justify="right", style=f"bold {COBALT}")
    status_table.add_column()

    rec_status = "[bold green]● RECORDING[/]" if is_recording else "[bold red]○ STOPPED[/]"
    status_table.add_row("Status:", rec_status)
    status_table.add_row("Queue depth:", str(queue_depth))
    status_table.add_row("Chunks processed:", str(chunks))
    status_table.add_row("Groq tokens consumed:", str(tokens))
    status_table.add_row("Latest note:", note_path)

    preview = last_block if last_block else "[dim]Waiting for ONYX to grace you with output...[/]"

    body = Table.grid()
    body.add_row(status_table)
    body.add_row(Text(""))
    body.add_row(Panel(preview, title="Latest Note Block", border_style=COBALT, expand=True))

    return Panel(body, title="[bold]ONYX Live Dashboard[/]", border_style=COBALT, expand=True)
