"""
session_memory.py - lightweight session-scoped working memory for Obsidian flows.

This module tracks the current session's active topics, notes, recent queries,
rejected suggestion targets, and unresolved loops. It is intentionally small and
stores references, not copied note content.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

_SESSION_MEMORY_FILE = "_session_memory.json"
_MAX_ACTIVE_TOPICS = 5
_MAX_ACTIVE_NOTES = 10
_MAX_RECENT_QUERIES = 10
_MAX_OPEN_LOOPS = 10


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _dedupe_keep_last(values: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in reversed(values):
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    ordered.reverse()
    if len(ordered) > limit:
        ordered = ordered[-limit:]
    return ordered


class SessionMemory:
    def __init__(self, vault: Path, persist: bool = False):
        self.vault = vault
        self.persist = persist
        self._session_path = vault / _SESSION_MEMORY_FILE
        self._state = {
            "session_id": _now_iso(),
            "active_topics": [],
            "active_notes": [],
            "recent_queries": [],
            "rejected_targets": {},
            "open_loops": [],
            "updated_at": _now_iso(),
        }
        self._load()

    def _load(self) -> None:
        if not self.persist or not self._session_path.exists():
            return
        try:
            data = json.loads(self._session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        self._state.update(
            {
                "session_id": str(data.get("session_id") or self._state["session_id"]),
                "active_topics": list(data.get("active_topics") or []),
                "active_notes": list(data.get("active_notes") or []),
                "recent_queries": list(data.get("recent_queries") or []),
                "rejected_targets": dict(data.get("rejected_targets") or {}),
                "open_loops": list(data.get("open_loops") or []),
                "updated_at": str(data.get("updated_at") or self._state["updated_at"]),
            }
        )

    def _touch(self) -> None:
        self._state["updated_at"] = _now_iso()

    def save(self) -> None:
        if not self.persist:
            return
        self._session_path.parent.mkdir(parents=True, exist_ok=True)
        self._session_path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def reset(self) -> None:
        session_id = _now_iso()
        self._state = {
            "session_id": session_id,
            "active_topics": [],
            "active_notes": [],
            "recent_queries": [],
            "rejected_targets": {},
            "open_loops": [],
            "updated_at": session_id,
        }
        self.save()

    def add_topic(self, topic: str) -> None:
        self._state["active_topics"] = _dedupe_keep_last(
            self._state["active_topics"] + [topic],
            _MAX_ACTIVE_TOPICS,
        )
        self._touch()
        self.save()

    def add_note(self, note: str) -> None:
        self._state["active_notes"] = _dedupe_keep_last(
            self._state["active_notes"] + [note],
            _MAX_ACTIVE_NOTES,
        )
        self._touch()
        self.save()

    def add_query(self, query: str) -> None:
        self._state["recent_queries"] = _dedupe_keep_last(
            self._state["recent_queries"] + [query],
            _MAX_RECENT_QUERIES,
        )
        self._touch()
        self.save()

    def reject_target(self, source_note: str, target: str) -> None:
        source = source_note.strip()
        rejected = list(self._state["rejected_targets"].get(source, []))
        self._state["rejected_targets"][source] = _dedupe_keep_last(rejected + [target], 20)
        self._touch()
        self.save()

    def add_open_loop(self, loop: str) -> None:
        self._state["open_loops"] = _dedupe_keep_last(
            self._state["open_loops"] + [loop],
            _MAX_OPEN_LOOPS,
        )
        self._touch()
        self.save()

    def clear_open_loop(self, loop: str) -> None:
        loop = loop.strip()
        self._state["open_loops"] = [item for item in self._state["open_loops"] if item != loop]
        self._touch()
        self.save()

    def is_rejected(self, source_note: str, target: str) -> bool:
        return target in self._state["rejected_targets"].get(source_note, [])

    def to_dict(self) -> dict:
        return {
            "session_id": self._state["session_id"],
            "active_topics": list(self._state["active_topics"]),
            "active_notes": list(self._state["active_notes"]),
            "recent_queries": list(self._state["recent_queries"]),
            "rejected_targets": {
                key: list(value) for key, value in self._state["rejected_targets"].items()
            },
            "open_loops": list(self._state["open_loops"]),
            "updated_at": self._state["updated_at"],
        }

    def format_context(self) -> str:
        lines = ["<session_memory>"]
        if self._state["active_topics"]:
            lines.append("topics: " + ", ".join(self._state["active_topics"]))
        if self._state["active_notes"]:
            lines.append("notes: " + ", ".join(self._state["active_notes"]))
        if self._state["recent_queries"]:
            lines.append("queries: " + " | ".join(self._state["recent_queries"]))
        if self._state["open_loops"]:
            lines.append("open_loops: " + " | ".join(self._state["open_loops"]))
        if len(lines) == 1:
            return ""
        lines.append("</session_memory>")
        return "\n".join(lines)
