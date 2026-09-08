"""Async producer-consumer worker: WAV chunk -> Groq Whisper -> Groq Llama 3.3 -> standalone chunk note."""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Callable, Optional

import aiofiles
from groq import AsyncGroq, RateLimitError
from rapidfuzz import fuzz, process

from onyx_vault.persona import get_system_prompt
from onyx_vault.vault import VaultIndex, sanitize_topic

TRANSCRIBE_MODEL = "whisper-large-v3-turbo"
CHAT_MODEL = "openai/gpt-oss-120b"

MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 1.0

MAX_TOPIC_RELATIVES = 3
TOPIC_RELATIVE_THRESHOLD = 45

NEXT_PART_LINE = re.compile(r"\*\*Next Part:\*\* .*")

FLASHCARD_HEADER = "### 🎴 Auto-Generated Flashcards (Anki / Quizlet)"
FLASHCARD_SPLIT = re.compile(
    r"\n?-{3,}\n+" + re.escape(FLASHCARD_HEADER), re.MULTILINE
)
FALLBACK_FLASHCARDS = (
    f"{FLASHCARD_HEADER}\n"
    "- **Front**: [No flashcards generated for this chunk] :: "
    "**Back**: [Model omitted the flashcards block]\n"
)


class ProcessorStats:
    """Shared, mutable counters the live dashboard polls each render tick."""

    def __init__(self):
        self.tokens_consumed = 0
        self.chunks_processed = 0
        self.last_block = ""
        self.last_transcript = ""
        self.last_note_path = ""


async def _with_backoff(coro_fn, *args, **kwargs):
    """Retry a Groq call with exponential backoff, but only on 429s."""
    delay = INITIAL_BACKOFF_SECONDS
    for attempt in range(MAX_RETRIES):
        try:
            return await coro_fn(*args, **kwargs)
        except RateLimitError:
            if attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")  # pragma: no cover


class NoteProcessor:
    """Consumes recorded chunks, transcribes + structures them, and writes each
    one to its own standalone chunk note in the course directory."""

    def __init__(
        self,
        client: AsyncGroq,
        queue: "asyncio.Queue[Optional[Path]]",
        vault_index: VaultIndex,
        course_dir: Path,
        meta: dict,
        persona: str,
        stats: ProcessorStats,
        on_update: Optional[Callable[[], None]] = None,
    ):
        self.client = client
        self.queue = queue
        self.vault_index = vault_index
        self.course_dir = course_dir
        self.meta = meta
        self.clean_topic = sanitize_topic(meta["topic"])
        self.persona = persona
        self.stats = stats
        self.on_update = on_update
        self.full_transcript_parts: list[str] = []
        self.part_index = 0
        self.previous_note_path: Optional[Path] = None
        self._stopped = False

    async def run(self) -> None:
        while True:
            filepath = await self.queue.get()
            try:
                if filepath is None:
                    break
                await self._process_chunk(filepath)
            finally:
                self.queue.task_done()

    async def stop(self) -> None:
        """Signal the run() loop to exit after any already-queued chunks drain."""
        self._stopped = True
        await self.queue.put(None)

    async def _process_chunk(self, filepath: Path) -> None:
        try:
            transcript = await self._transcribe(filepath)
            if not transcript or not transcript.strip():
                return

            self.full_transcript_parts.append(transcript)
            self.stats.last_transcript = transcript

            note_block = await self._structure(transcript)
            note_block = self.vault_index.validate_backlinks(note_block)

            note_path = await self._write_chunk_note(note_block)
            self.stats.last_block = note_block
            self.stats.last_note_path = str(note_path)
            self.stats.chunks_processed += 1
        finally:
            filepath.unlink(missing_ok=True)
            if self.on_update:
                self.on_update()

    async def _transcribe(self, filepath: Path) -> str:
        async def _do():
            audio_bytes = filepath.read_bytes()
            return await self.client.audio.transcriptions.create(
                file=(filepath.name, audio_bytes),
                model=TRANSCRIBE_MODEL,
                response_format="text",
            )

        result = await _with_backoff(_do)
        return result if isinstance(result, str) else getattr(result, "text", str(result))

    async def _structure(self, transcript: str) -> str:
        system_prompt = get_system_prompt(self.persona)
        vault_context = self.vault_index.context_blob()

        async def _do():
            return await self.client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "Existing vault notes you may ONLY link to via [[Backlink]]:\n"
                            f"{vault_context}\n\n"
                            f"Lecture transcript chunk:\n{transcript}"
                        ),
                    },
                ],
                temperature=0.8,
            )

        response = await _with_backoff(_do)
        if response.usage:
            self.stats.tokens_consumed += response.usage.total_tokens
        return response.choices[0].message.content

    async def _write_chunk_note(self, block: str) -> Path:
        self.part_index += 1
        part_index = self.part_index
        meta = self.meta

        filename = f"Lecture_{meta['lecture_num']}_Part_{part_index:02d}_{self.clean_topic}.md"
        note_path = self.course_dir / filename

        previous_title = self.previous_note_path.stem if self.previous_note_path else None
        previous_link = f"[[{previous_title}]]" if previous_title else "None (Lecture Start)"
        next_link = "None (Lecture End)"

        relatives = self._find_topic_relatives(exclude={note_path.stem, previous_title})
        relatives_text = (
            ", ".join(f"[[{title}]]" for title in relatives) if relatives else "None found"
        )

        timestamp = time.strftime("%H:%M:%S")
        frontmatter = (
            "---\n"
            f"subject: {meta['subject']}\n"
            f"professor: {meta['professor']}\n"
            f"lecture: {meta['lecture_num']}\n"
            f"part: {part_index:02d}\n"
            f"topic: {meta['topic']}\n"
            "generated_by: ONYX (The Cobalt Scarab)\n"
            "tags: [onyx, lecture-notes]\n"
            "---\n\n"
            f"# {meta['subject']} — Lecture {meta['lecture_num']} Part {part_index:02d}: {meta['topic']}\n\n"
            f"*Professor: {meta['professor']} · Recorded: {timestamp}*\n\n"
        )

        brother_links = (
            "\n---\n\n"
            "### 🔗 Brother Links\n"
            f"- **Previous Part:** {previous_link}\n"
            f"- **Next Part:** {next_link}\n"
            f"- **Topic Relatives:** {relatives_text}\n"
        )

        main_block, flashcards_block = self._split_flashcards(block)
        flashcards_section = f"\n---\n\n{flashcards_block}"

        async with aiofiles.open(note_path, "w", encoding="utf-8") as f:
            await f.write(frontmatter + main_block + "\n" + brother_links + flashcards_section)

        if self.previous_note_path is not None:
            await self._patch_previous_next_link(self.previous_note_path, note_path.stem)

        self.previous_note_path = note_path
        return note_path

    async def _patch_previous_next_link(self, previous_path: Path, new_title: str) -> None:
        async with aiofiles.open(previous_path, "r", encoding="utf-8") as f:
            content = await f.read()

        content = NEXT_PART_LINE.sub(f"**Next Part:** [[{new_title}]]", content, count=1)

        async with aiofiles.open(previous_path, "w", encoding="utf-8") as f:
            await f.write(content)

    def _split_flashcards(self, block: str) -> tuple[str, str]:
        """Pull the flashcards block out so it can be re-attached at the true end
        of the note, after the Brother Links footer, instead of wherever the model
        placed it."""
        match = FLASHCARD_SPLIT.search(block)
        if not match:
            return block.rstrip() + "\n", FALLBACK_FLASHCARDS
        main = block[: match.start()].rstrip() + "\n"
        flashcards = block[match.end() - len(FLASHCARD_HEADER) :].rstrip() + "\n"
        return main, flashcards

    def _find_topic_relatives(self, exclude: set) -> list[str]:
        stems = [p.stem for p in self.course_dir.glob("*.md") if p.stem not in exclude]
        if not stems:
            return []

        matches = process.extract(
            self.meta["topic"], stems, scorer=fuzz.WRatio, limit=MAX_TOPIC_RELATIVES
        )
        return [title for title, score, _ in matches if score >= TOPIC_RELATIVE_THRESHOLD]
