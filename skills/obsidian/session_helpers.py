"""
session_helpers.py — Wrappers around the optional ``SessionMemory`` module.

Centralizes the small helpers that bridge ``SessionMemory`` (persisted
in the user's home directory) to the rest of the codebase. All helpers
no-op silently when ``SessionMemory`` is unavailable, which is the
default for tests and minimal installs.

Previously these helpers were duplicated in ``log_writer``, ``linker``,
``ingest_service``, and ``obsidian_writer``; consolidating them here
removes that duplication and keeps the dependency graph one-directional.
"""

from __future__ import annotations

from pathlib import Path

try:
    from .linker import suggestion_keywords_from_stem
except ImportError:  # script-mode fallback
    from linker import suggestion_keywords_from_stem  # type: ignore[no-redef]


def _import_session_memory():
    """Import ``SessionMemory`` lazily so missing deps don't break imports."""

    try:
        try:
            from .session_memory import SessionMemory  # type: ignore[attr-defined]
            return SessionMemory
        except ImportError:
            from session_memory import SessionMemory  # type: ignore[no-redef]
            return SessionMemory
    except ImportError:
        return None


def safe_session_memory(vault: Path):
    """Return a ``SessionMemory`` instance for ``vault`` or ``None``."""

    SessionMemory = _import_session_memory()
    if SessionMemory is None:
        return None
    try:
        return SessionMemory(vault, persist=True)
    except Exception:
        return None


def session_rejected_targets(vault: Path, source_note: str) -> set[str]:
    """Targets rejected in the current session for ``source_note``."""

    session = safe_session_memory(vault)
    if session is None:
        return set()
    try:
        rejected = session.to_dict().get("rejected_targets", {}).get(source_note, [])
    except Exception:
        return set()
    return {str(item).strip() for item in rejected if str(item).strip()}


def record_session_note(vault: Path, note_type: str, filepath: Path) -> None:
    """Record an explicit note write or update in session memory."""

    session = safe_session_memory(vault)
    if session is None:
        return
    try:
        session.add_note(filepath.name)
        if note_type == "topic" or "Topics" in filepath.parts:
            session.add_topic(filepath.stem)
    except Exception:
        return


def record_session_query(vault: Path, query_text: str) -> None:
    """Record a user query into session memory."""

    session = safe_session_memory(vault)
    if session is None:
        return
    try:
        session.add_query(query_text)
    except Exception:
        return


def resolve_session_note_refs(vault: Path, names: list[str]) -> list[Path]:
    """Resolve session note/topic names to concrete vault paths when they exist."""

    resolved: list[Path] = []
    seen: set[Path] = set()
    for name in names:
        label = str(name).strip()
        if not label:
            continue
        path = vault / label if label.endswith(".md") else None
        if path is not None and path.exists():
            if path not in seen:
                resolved.append(path)
                seen.add(path)
            continue
        pattern = label if label.endswith(".md") else f"{label}.md"
        matches = list(vault.rglob(pattern))
        for match in matches:
            if match not in seen:
                resolved.append(match)
                seen.add(match)
    return resolved


def find_session_relevant_notes(
    vault: Path, query_text: str = "", limit: int = 5
) -> list[Path]:
    """Rank current-session notes/topics ahead of wider vault fallback.

    Signals: active topics before active notes; query keyword overlap;
    recency within the session lists.
    """

    session = safe_session_memory(vault)
    if session is None:
        return []
    try:
        state = session.to_dict()
    except Exception:
        return []

    active_topics = list(state.get("active_topics", []))
    active_notes = list(state.get("active_notes", []))
    query_words = {word.lower() for word in suggestion_keywords_from_stem(query_text)}

    candidates: list[tuple[int, int, Path]] = []
    seen: set[Path] = set()

    for idx, path in enumerate(resolve_session_note_refs(vault, active_topics)):
        if path in seen:
            continue
        score = 100 - idx
        stem_words = {word.lower() for word in suggestion_keywords_from_stem(path.stem)}
        overlap = len(query_words & stem_words)
        score += overlap * 50
        if query_words and overlap == 0:
            score -= 60
        candidates.append((score, idx, path))
        seen.add(path)

    for idx, path in enumerate(resolve_session_note_refs(vault, active_notes)):
        if path in seen:
            continue
        score = 50 - idx
        stem_words = {word.lower() for word in suggestion_keywords_from_stem(path.stem)}
        overlap = len(query_words & stem_words)
        score += overlap * 50
        if query_words and overlap == 0:
            score -= 30
        candidates.append((score, idx, path))
        seen.add(path)

    candidates.sort(key=lambda item: (-item[0], item[1], str(item[2])))
    return [path for _, _, path in candidates[:limit]]
