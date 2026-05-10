"""
live_note.py — Manual-trigger Live Notes.

Inspired by rowboat's ``apps/x/packages/core/src/knowledge/live-note``,
adapted to claude-obsidian's "no scheduler, user always in the loop"
philosophy. A Live Note carries a stated ``objective`` in its
frontmatter; when the user runs ``live-run``, this module gathers
deterministic context (objective + current section bodies + related
notes) so the host LLM (Claude Code) can propose section updates,
which the user then applies via the existing ``cascade-update`` /
``merge-update`` CLI paths.

Frontmatter shape (flat keys; matches the line-level parser):

  live_active: true                # required to be considered "live"
  live_objective: "..."            # one-line stated goal
  live_last_run_at: "2026-05-10T12:00:00"   # ISO 8601, set by runs
  live_last_run_summary: "..."     # one-line summary, set on success
  live_last_run_error: "..."       # message, set on failure (cleared on success)

The module emits ``live_note_run_started`` / ``live_note_run_done`` /
``live_note_run_failed`` events into ``runs/<run_id>.jsonl`` so each
manual run can be inspected, replayed, or audited later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    from . import frontmatter as fm
    from .events import make_event
    from .knowledge_service import organize_vault
    from .runs import RunStore
except ImportError:  # script-mode fallback
    import frontmatter as fm  # type: ignore[no-redef]
    from events import make_event  # type: ignore[no-redef]
    from knowledge_service import organize_vault  # type: ignore[no-redef]
    from runs import RunStore  # type: ignore[no-redef]


# Frontmatter key constants — kept as module-level so callers don't
# hard-code strings.
KEY_ACTIVE = "live_active"
KEY_OBJECTIVE = "live_objective"
KEY_LAST_RUN_AT = "live_last_run_at"
KEY_LAST_RUN_SUMMARY = "live_last_run_summary"
KEY_LAST_RUN_ERROR = "live_last_run_error"


@dataclass
class LiveNoteConfig:
    """Parsed ``live_*`` frontmatter for a single note."""

    active: bool = False
    objective: str = ""
    last_run_at: str = ""
    last_run_summary: str = ""
    last_run_error: str = ""

    @property
    def is_runnable(self) -> bool:
        """True when both ``active`` and ``objective`` are set."""

        return self.active and bool(self.objective.strip())


# ---------------------------------------------------------------------------
# Parsing / state mutation
# ---------------------------------------------------------------------------


def parse_config(fmd: dict[str, str]) -> LiveNoteConfig:
    """Parse a ``LiveNoteConfig`` from a frontmatter dict."""

    return LiveNoteConfig(
        active=_truthy(fmd.get(KEY_ACTIVE, "")),
        objective=fmd.get(KEY_OBJECTIVE, "").strip(),
        last_run_at=fmd.get(KEY_LAST_RUN_AT, "").strip(),
        last_run_summary=fmd.get(KEY_LAST_RUN_SUMMARY, "").strip(),
        last_run_error=fmd.get(KEY_LAST_RUN_ERROR, "").strip(),
    )


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"true", "yes", "1", "on"}


def update_state(
    text: str,
    *,
    last_run_at: str,
    last_run_summary: str = "",
    last_run_error: str = "",
) -> str:
    """Refresh the ``live_last_run_*`` frontmatter fields.

    On success (no error), the previous error field is cleared so a
    later inspector can tell that the most recent run was healthy.
    """

    text = fm.update_field(text, KEY_LAST_RUN_AT, last_run_at)
    text = fm.update_field(text, KEY_LAST_RUN_SUMMARY, last_run_summary)
    text = fm.update_field(text, KEY_LAST_RUN_ERROR, last_run_error)
    return text


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@dataclass
class LiveNoteEntry:
    path: Path
    config: LiveNoteConfig

    @property
    def stem(self) -> str:
        return self.path.stem


def list_live_notes(vault: Path) -> list[LiveNoteEntry]:
    """Return every ``*.md`` in ``vault`` whose ``live_active`` is true.

    Inactive Live Notes (``live_active: false`` or unset) are filtered
    out. The result is sorted by stem for stable display.
    """

    entries: list[LiveNoteEntry] = []
    for path in vault.rglob("*.md"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        config = parse_config(fm.parse_dict(text))
        if config.active:
            entries.append(LiveNoteEntry(path=path, config=config))
    entries.sort(key=lambda e: e.stem)
    return entries


def find_by_stem(vault: Path, stem: str) -> Path | None:
    """Locate a note by stem within ``vault`` (first match wins)."""

    for path in vault.rglob(f"{stem}.md"):
        return path
    return None


# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------


@dataclass
class LiveNoteContext:
    """Deterministic context bundle handed to the host LLM."""

    note_path: Path
    relative_path: str
    config: LiveNoteConfig
    sections: dict[str, str]
    related: list[dict] = field(default_factory=list)
    organize_reasons: list[str] = field(default_factory=list)
    suggested_output: str = ""
    confidence: str = ""

    def to_dict(self) -> dict:
        return {
            "note_path": str(self.note_path),
            "relative_path": self.relative_path,
            "objective": self.config.objective,
            "last_run_at": self.config.last_run_at,
            "last_run_summary": self.config.last_run_summary,
            "last_run_error": self.config.last_run_error,
            "sections": self.sections,
            "related": [
                {
                    "title": item.get("title", ""),
                    "relative_path": item.get("relative_path", ""),
                    "type": item.get("type", ""),
                    "excerpt": item.get("excerpt", ""),
                    "in_session": item.get("in_session", False),
                    "in_inbox": item.get("in_inbox", False),
                    "parent_topics": item.get("parent_topics", []),
                }
                for item in self.related
            ],
            "organize_reasons": self.organize_reasons,
            "suggested_output": self.suggested_output,
            "confidence": self.confidence,
        }


_HEADING_RE = re.compile(r"^# (?P<title>.+)$", re.MULTILINE)


def _collect_top_level_sections(text: str) -> dict[str, str]:
    """Map ``# Heading`` → body for every top-level section."""

    sections: dict[str, str] = {}
    matches = list(_HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        title = m.group("title").strip()
        body_start = m.end() + 1  # skip the trailing newline
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].rstrip()
        sections[title] = body
    return sections


def gather_context(vault: Path, note_path: Path) -> LiveNoteContext:
    """Build a :class:`LiveNoteContext` for ``note_path``.

    Uses :func:`knowledge_service.organize_vault` keyed on the note's
    objective to find related notes; this leverages the existing
    session-first / topic-first heuristics so live runs benefit from
    in-session context just like manual ``organize`` queries do.
    """

    text = note_path.read_text(encoding="utf-8", errors="replace")
    config = parse_config(fm.parse_dict(text))
    sections = _collect_top_level_sections(text)

    related: list[dict] = []
    organize_reasons: list[str] = []
    suggested_output = ""
    confidence = ""
    if config.objective:
        organized = organize_vault(vault, config.objective, limit=8)
        related = organized.get("matches", [])
        organize_reasons = organized.get("reasons", [])
        suggested_output = organized.get("suggested_output", "")
        confidence = organized.get("confidence", "")

    try:
        rel = str(note_path.relative_to(vault))
    except ValueError:
        rel = str(note_path)

    return LiveNoteContext(
        note_path=note_path,
        relative_path=rel,
        config=config,
        sections=sections,
        related=related,
        organize_reasons=organize_reasons,
        suggested_output=suggested_output,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Run orchestration
# ---------------------------------------------------------------------------


@dataclass
class LiveRunResult:
    success: bool
    run_id: str
    context: LiveNoteContext | None
    error: str = ""


def run_live_note(vault: Path, stem: str) -> LiveRunResult:
    """Execute one manual run for the Live Note named ``stem``.

    Outcomes:
      - The note doesn't exist → returns ``success=False`` *without*
        creating a Run (nothing to attribute the failure to).
      - The note exists but isn't active / has no objective → creates
        a Run and marks it failed with a precise reason. The
        frontmatter ``live_last_run_error`` is updated.
      - Success → emits ``live_note_run_started`` + ``live_note_run_done``,
        updates ``live_last_run_at`` / ``live_last_run_summary``, clears
        ``live_last_run_error``.

    The actual section rewriting is *not* performed here: the run
    yields the deterministic context bundle that the host LLM
    consumes. The user (or an LLM tool call) applies updates via the
    existing ``cascade-update`` / ``merge-update`` CLI paths.
    """

    note_path = find_by_stem(vault, stem)
    if note_path is None:
        return LiveRunResult(
            success=False,
            run_id="",
            context=None,
            error=f"Live note not found: {stem}",
        )

    store = RunStore(vault)
    run = store.create("live_note", metadata={"note": stem})
    run.append_event(make_event("live_note_run_started", note=stem))

    try:
        ctx = gather_context(vault, note_path)
        if not ctx.config.is_runnable:
            reason = (
                f"live_active is false" if not ctx.config.active
                else "live_objective is empty"
            )
            error_msg = f"not runnable: {reason}"
            run.append_event(
                make_event(
                    "live_note_run_failed", note=stem, error=error_msg,
                )
            )
            _persist_state(
                note_path,
                last_run_at=_iso_now(),
                last_run_summary="",
                last_run_error=error_msg,
            )
            run.fail(error=error_msg)
            return LiveRunResult(
                success=False,
                run_id=run.run_id,
                context=ctx,
                error=error_msg,
            )

        ts = _iso_now()
        summary = _summarize_context(ctx)
        run.append_event(
            make_event(
                "live_note_run_done",
                note=stem,
                related_count=len(ctx.related),
                suggested_output=ctx.suggested_output,
                confidence=ctx.confidence,
            )
        )
        _persist_state(
            note_path,
            last_run_at=ts,
            last_run_summary=summary,
            last_run_error="",
        )
        run.complete(summary=summary)
        return LiveRunResult(
            success=True,
            run_id=run.run_id,
            context=ctx,
            error="",
        )
    except Exception as exc:  # noqa: BLE001
        error_msg = f"{type(exc).__name__}: {exc}"
        run.append_event(make_event("live_note_run_failed", note=stem, error=error_msg))
        try:
            _persist_state(
                note_path,
                last_run_at=_iso_now(),
                last_run_summary="",
                last_run_error=error_msg,
            )
        except Exception:
            pass  # best-effort; don't shadow the original failure
        run.fail(error=error_msg)
        return LiveRunResult(
            success=False,
            run_id=run.run_id,
            context=None,
            error=error_msg,
        )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _summarize_context(ctx: LiveNoteContext) -> str:
    parts = [f"objective={ctx.config.objective[:60]}"]
    parts.append(f"related={len(ctx.related)}")
    if ctx.suggested_output:
        parts.append(f"converge={ctx.suggested_output}")
    if ctx.confidence:
        parts.append(f"confidence={ctx.confidence}")
    return " ".join(parts)


def _persist_state(
    note_path: Path,
    *,
    last_run_at: str,
    last_run_summary: str,
    last_run_error: str,
) -> None:
    """Apply ``live_last_run_*`` updates back to the note's frontmatter."""

    text = note_path.read_text(encoding="utf-8", errors="replace")
    new_text = update_state(
        text,
        last_run_at=last_run_at,
        last_run_summary=last_run_summary,
        last_run_error=last_run_error,
    )
    if new_text != text:
        note_path.write_text(new_text, encoding="utf-8")


def format_list(entries: Iterable[LiveNoteEntry]) -> str:
    """Render a human-readable summary of ``list_live_notes`` output."""

    entries = list(entries)
    if not entries:
        return "No active Live Notes found."

    lines = [f"[Live Notes] {len(entries)} active"]
    for entry in entries:
        cfg = entry.config
        lines.append(f"  [[{entry.stem}]]")
        if cfg.objective:
            lines.append(f"    objective: {cfg.objective}")
        if cfg.last_run_at:
            lines.append(f"    last run : {cfg.last_run_at}")
        if cfg.last_run_summary:
            lines.append(f"    summary  : {cfg.last_run_summary}")
        if cfg.last_run_error:
            lines.append(f"    last err : {cfg.last_run_error}")
    return "\n".join(lines)


def format_context(ctx: LiveNoteContext) -> str:
    """Render a context bundle for CLI display."""

    lines = [f"[Live Run] {ctx.relative_path}"]
    lines.append(f"  objective: {ctx.config.objective}")
    if ctx.config.last_run_at:
        lines.append(f"  last run : {ctx.config.last_run_at}")
    if ctx.sections:
        lines.append("\n[Current sections]")
        for title, body in ctx.sections.items():
            preview = body.strip().splitlines()[0] if body.strip() else "(empty)"
            lines.append(f"  # {title} — {preview[:80]}")
    if ctx.related:
        lines.append(f"\n[Related notes] ({len(ctx.related)})")
        for item in ctx.related[:8]:
            markers = []
            if item.get("in_session"):
                markers.append("session")
            if item.get("in_inbox"):
                markers.append("inbox")
            marker_text = f" ({', '.join(markers)})" if markers else ""
            excerpt = f" — {item['excerpt']}" if item.get("excerpt") else ""
            lines.append(f"  [[{item['title']}]]{marker_text}{excerpt}")
    if ctx.suggested_output:
        lines.append(
            f"\n[Suggest] Converge into: {ctx.suggested_output} "
            f"(confidence={ctx.confidence})"
        )
    if ctx.organize_reasons:
        lines.append("[Reasons]")
        for reason in ctx.organize_reasons:
            lines.append(f"  - {reason}")
    lines.append(
        "\n[Next] Use ``--type cascade-update`` (or ``merge-update``) to apply "
        "the LLM-proposed section changes."
    )
    return "\n".join(lines)
