"""
events.py — Unified event schema and JSONL writer.

Inspired by rowboat's run/event model: every observable mutation in
the system (note written, lint issue detected, suggestion rejected,
pipeline step status, etc.) is a structured event with a stable shape.

Schema versioning:
  - Every event written through this module carries ``schema_version: 1``.
  - Legacy events in ``_events.jsonl`` / ``_corrections.jsonl`` written
    by ``obsidian_writer.py`` lack this field; :func:`read_events` treats
    those as ``schema_version: 0`` and otherwise passes them through, so
    upgrade is non-breaking.
  - Future schema changes bump the version; readers should branch on it.

This module deliberately keeps event payloads as plain dicts rather
than typed dataclasses. The set of event types will grow as we wire in
runs/pipeline/live-note, and a discriminated union of dataclasses adds
import friction without much value when consumers (UI, replay, debug)
just want JSON.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

SCHEMA_VERSION = 1

# Known event types.  This is an open enum: callers may emit unknown
# types; consumers should ignore types they don't recognize.
EVENT_TYPES: frozenset[str] = frozenset(
    {
        # Note lifecycle
        "note_written",
        "note_merged",
        "note_renamed",
        "note_trashed",
        "topic_cascade_updated",
        # Suggestion / feedback
        "suggestion_feedback",  # legacy compat: kept as-is
        "suggestion_rejected",
        # Lint / corrections
        "lint_issue_detected",
        # Run / pipeline lifecycle
        "run_started",
        "run_done",
        "run_failed",
        "step_started",
        "step_done",
        "step_failed",
        "step_planned",  # dry-run
        # Live note lifecycle
        "live_note_run_started",
        "live_note_run_done",
        "live_note_run_failed",
    }
)


def now_iso() -> str:
    """Current timestamp in ISO 8601 (seconds resolution).

    Matches the format used by existing ``obsidian_writer`` callers so
    tooling that joins events across files stays consistent.
    """

    return datetime.now().isoformat(timespec="seconds")


def make_event(event_type: str, **fields: Any) -> dict[str, Any]:
    """Build a stamped event dict.

    The returned dict has these guaranteed keys:
      - ``schema_version`` (always :data:`SCHEMA_VERSION`)
      - ``ts`` (ISO seconds; caller may override)
      - ``event_type``

    All other fields are passed through verbatim. ``ts`` may be
    overridden by passing ``ts=`` explicitly (useful in tests).
    """

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ts": fields.pop("ts", None) or now_iso(),
        "event_type": event_type,
    }
    payload.update(fields)
    return payload


def append(path: Path, event: dict[str, Any]) -> Path:
    """Append a single event to the JSONL file at ``path``.

    Stamps :data:`SCHEMA_VERSION` and a default ``ts`` if missing, so
    callers can also pass through events received from another writer
    without losing version tagging.
    """

    if "schema_version" not in event:
        event = {"schema_version": SCHEMA_VERSION, **event}
    if "ts" not in event:
        event = {"ts": now_iso(), **event}
    if "event_type" not in event:
        raise ValueError("event must include 'event_type'")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


def append_many(path: Path, events: Iterable[dict[str, Any]]) -> Path | None:
    """Append a batch of events. Returns ``None`` if iterable is empty."""

    items = list(events)
    if not items:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for ev in items:
            stamped = ev
            if "schema_version" not in stamped:
                stamped = {"schema_version": SCHEMA_VERSION, **stamped}
            if "ts" not in stamped:
                stamped = {"ts": now_iso(), **stamped}
            if "event_type" not in stamped:
                raise ValueError("event must include 'event_type'")
            fh.write(json.dumps(stamped, ensure_ascii=False) + "\n")
    return path


def read_events(path: Path) -> Iterator[dict[str, Any]]:
    """Yield events from ``path``, normalizing legacy entries.

    Legacy events (no ``schema_version``) are returned with
    ``schema_version: 0`` injected so consumers can branch on version
    without crashing.
    Lines that fail to parse as JSON are skipped silently — the file is
    append-only and partial writes from a crashed process should not
    poison readers.
    """

    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            if "schema_version" not in ev:
                ev["schema_version"] = 0
            yield ev


# ---------------------------------------------------------------------------
# Convenience builders for well-known events
# ---------------------------------------------------------------------------


def note_written(rel_path: str, note_type: str, *, draft: bool = False, **extra: Any) -> dict[str, Any]:
    return make_event(
        "note_written", note=rel_path, note_type=note_type, draft=draft, **extra
    )


def note_renamed(old_rel: str, new_rel: str, *, backlinks_updated: int = 0, **extra: Any) -> dict[str, Any]:
    return make_event(
        "note_renamed",
        old_path=old_rel,
        new_path=new_rel,
        backlinks_updated=backlinks_updated,
        **extra,
    )


def lint_issue_detected(
    rel_path: str, issue_type: str, detail: str, *, detected_by: str = "lint"
) -> dict[str, Any]:
    return make_event(
        "lint_issue_detected",
        note=rel_path,
        issue_type=issue_type,
        detail=detail,
        detected_by=detected_by,
        resolved=False,
    )


def run_started(run_id: str, kind: str, **extra: Any) -> dict[str, Any]:
    return make_event("run_started", run_id=run_id, kind=kind, **extra)


def run_done(run_id: str, *, summary: str = "", **extra: Any) -> dict[str, Any]:
    return make_event("run_done", run_id=run_id, summary=summary, **extra)


def run_failed(run_id: str, *, error: str, **extra: Any) -> dict[str, Any]:
    return make_event("run_failed", run_id=run_id, error=error, **extra)


def step_started(run_id: str, step: str, **extra: Any) -> dict[str, Any]:
    return make_event("step_started", run_id=run_id, step=step, **extra)


def step_done(run_id: str, step: str, *, summary: str = "", **extra: Any) -> dict[str, Any]:
    return make_event("step_done", run_id=run_id, step=step, summary=summary, **extra)


def step_failed(run_id: str, step: str, *, error: str, **extra: Any) -> dict[str, Any]:
    return make_event("step_failed", run_id=run_id, step=step, error=error, **extra)


def step_planned(run_id: str, step: str, **extra: Any) -> dict[str, Any]:
    """Emitted instead of step_started/step_done in dry-run mode."""

    return make_event("step_planned", run_id=run_id, step=step, **extra)
