"""Vault indexing and backlink validation.

Scans the Obsidian vault for existing note titles so that Llama 3.3 is given
a closed set of valid [[Backlinks]] to choose from, and so that anything it
hallucinates anyway gets fuzzy-matched or stripped before it hits the note.
"""

from __future__ import annotations

import re
from pathlib import Path

from rapidfuzz import fuzz, process

BACKLINK_PATTERN = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
FUZZY_MATCH_THRESHOLD = 85


def sanitize_topic(topic: str) -> str:
    """Turn a free-form topic string into a filesystem- and Obsidian-link-safe token."""
    return topic.replace(" ", "_").replace("/", "-")


class VaultIndex:
    """An in-memory index of note titles that live in the Obsidian vault."""

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self.titles: list[str] = []
        self.refresh()

    def refresh(self) -> None:
        """Re-scan the vault directory for .md file titles."""
        titles = set()
        if self.vault_path.exists():
            for md_file in self.vault_path.rglob("*.md"):
                titles.add(md_file.stem)
        self.titles = sorted(titles)

    def context_blob(self) -> str:
        """A newline-delimited list of valid backlink targets, for the LLM prompt."""
        if not self.titles:
            return "(The vault is empty. Do not invent any [[Backlinks]].)"
        return "\n".join(f"- [[{title}]]" for title in self.titles)

    def validate_backlinks(self, text: str) -> str:
        """Rewrite or strip any [[Backlink]] that doesn't match a real vault note."""
        self.refresh()

        def _replace(match: re.Match) -> str:
            candidate = match.group(1).strip()
            if candidate in self.titles:
                return match.group(0)
            if not self.titles:
                return candidate

            best = process.extractOne(candidate, self.titles, scorer=fuzz.WRatio)
            if best and best[1] >= FUZZY_MATCH_THRESHOLD:
                return f"[[{best[0]}]]"
            return candidate  # de-link anything ONYX hallucinated out of thin air

        return BACKLINK_PATTERN.sub(_replace, text)
