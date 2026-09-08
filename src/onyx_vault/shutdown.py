"""Graceful shutdown: drain the queue, then run a Map-Reduce pass over the full
transcript to produce a standalone master summary note with an executive
summary and Anki flashcards."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiofiles
from groq import AsyncGroq
from rich.console import Console

from onyx_vault.persona import SHUTDOWN_MAP_PROMPT, SHUTDOWN_REDUCE_PROMPT
from onyx_vault.vault import sanitize_topic

CHAT_MODEL = "openai/gpt-oss-120b"
MAP_CHUNK_CHARS = 6000


async def run_shutdown_pipeline(
    client: AsyncGroq,
    transcript_parts: list[str],
    course_dir: Path,
    meta: dict,
    console: Console,
) -> None:
    """Map each transcript segment to bullet facts, then reduce to a standalone
    master summary note with an executive summary and Anki deck."""
    full_transcript = "\n".join(transcript_parts).strip()
    if not full_transcript:
        console.print(
            "[dim]No transcript captured. Skipping the summary. Groundbreaking session, truly.[/]"
        )
        return

    console.print(
        "[bold bright_cyan]Running final Map-Reduce pass... don't touch anything, you'll break it.[/]"
    )

    segments = [
        full_transcript[i : i + MAP_CHUNK_CHARS]
        for i in range(0, len(full_transcript), MAP_CHUNK_CHARS)
    ]

    mapped = await asyncio.gather(*(_map_segment(client, segment) for segment in segments))
    consolidated = "\n".join(mapped)

    final_block = await _reduce(client, consolidated)
    note_path = await _write_master_summary(course_dir, meta, final_block)

    console.print(f"[bold green]Master summary written to {note_path}. You're welcome.[/]")


async def _map_segment(client: AsyncGroq, segment: str) -> str:
    response = await client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": SHUTDOWN_MAP_PROMPT},
            {"role": "user", "content": segment},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content


async def _reduce(client: AsyncGroq, consolidated: str) -> str:
    response = await client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": SHUTDOWN_REDUCE_PROMPT},
            {"role": "user", "content": consolidated},
        ],
        temperature=0.6,
    )
    return response.choices[0].message.content


async def _write_master_summary(course_dir: Path, meta: dict, block: str) -> Path:
    clean_topic = sanitize_topic(meta["topic"])
    note_path = course_dir / f"Lecture_{meta['lecture_num']}_00_MASTER_SUMMARY_{clean_topic}.md"

    frontmatter = (
        "---\n"
        f"subject: {meta['subject']}\n"
        f"professor: {meta['professor']}\n"
        f"lecture: {meta['lecture_num']}\n"
        f"topic: {meta['topic']}\n"
        "generated_by: ONYX (The Cobalt Scarab)\n"
        "tags: [onyx, master-summary]\n"
        "---\n\n"
        f"# {meta['subject']} — Lecture {meta['lecture_num']}: {meta['topic']} — Master Summary\n\n"
    )

    async with aiofiles.open(note_path, "w", encoding="utf-8") as f:
        await f.write(frontmatter + block + "\n")

    return note_path
