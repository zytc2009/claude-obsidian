"""
runs.py — Run model with per-run JSONL event log.

Inspired by rowboat's run log model. A *run* represents one execution
of a long-running operation (URL capture, organize, query, live-note
update). Every event during the run lands in a single
``<vault>/runs/<run_id>.jsonl`` file, so the entire trace can be
inspected, replayed, or resumed.

Public surface:

  - :class:`Run` — in-memory handle for a single run; append events,
    mark done/failed.
  - :class:`RunStore` — vault-bound factory: ``create``, ``open``,
    ``list``.

The store keeps an index file ``<vault>/runs/_index.jsonl`` listing
run summaries (id, kind, status, started_at, ended_at, summary). The
index is *append-only*: status updates write a new row rather than
mutating prior rows, so concurrent writers can't corrupt it. Readers
fold the index by run_id taking the last entry per id.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

try:
    from . import events
except ImportError:  # script-mode fallback
    import events  # type: ignore[no-redef]

RUNS_DIR = "runs"
RUNS_INDEX_FILE = "_index.jsonl"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class RunSummary:
    """Lightweight projection of a run for listing UIs."""

    run_id: str
    kind: str
    status: RunStatus
    started_at: str
    ended_at: str = ""
    summary: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "status": self.status.value,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "summary": self.summary,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunSummary":
        return cls(
            run_id=d["run_id"],
            kind=d.get("kind", ""),
            status=RunStatus(d.get("status", "pending")),
            started_at=d.get("started_at", ""),
            ended_at=d.get("ended_at", ""),
            summary=d.get("summary", ""),
            error=d.get("error", ""),
        )


@dataclass
class Run:
    """Live handle to a single run.

    Created via :meth:`RunStore.create`. Use :meth:`append_event` to
    record domain events, :meth:`complete` to mark a successful end,
    and :meth:`fail` to mark a failure. Both terminal methods write a
    final ``run_done`` / ``run_failed`` event and update the index.
    """

    run_id: str
    kind: str
    log_path: Path
    index_path: Path
    started_at: str
    status: RunStatus = RunStatus.RUNNING
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Event recording
    # ------------------------------------------------------------------

    def append_event(self, event: dict[str, Any]) -> None:
        """Record an event in this run's log.

        ``run_id`` is auto-injected so consumers don't need to pass it
        on every call.
        """

        if "run_id" not in event:
            event = {**event, "run_id": self.run_id}
        events.append(self.log_path, event)

    def append_many(self, batch: Iterable[dict[str, Any]]) -> None:
        events.append_many(
            self.log_path,
            ({**ev, "run_id": self.run_id} if "run_id" not in ev else ev for ev in batch),
        )

    # ------------------------------------------------------------------
    # Terminal transitions
    # ------------------------------------------------------------------

    def complete(self, *, summary: str = "") -> None:
        if self.status not in {RunStatus.RUNNING, RunStatus.PENDING}:
            return
        self.status = RunStatus.DONE
        ended_at = events.now_iso()
        self.append_event(events.run_done(self.run_id, summary=summary))
        _append_index(
            self.index_path,
            RunSummary(
                run_id=self.run_id,
                kind=self.kind,
                status=self.status,
                started_at=self.started_at,
                ended_at=ended_at,
                summary=summary,
            ),
        )

    def fail(self, error: str) -> None:
        if self.status in {RunStatus.DONE, RunStatus.FAILED}:
            return
        self.status = RunStatus.FAILED
        ended_at = events.now_iso()
        self.append_event(events.run_failed(self.run_id, error=error))
        _append_index(
            self.index_path,
            RunSummary(
                run_id=self.run_id,
                kind=self.kind,
                status=self.status,
                started_at=self.started_at,
                ended_at=ended_at,
                error=error,
            ),
        )

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def iter_events(self) -> Iterable[dict[str, Any]]:
        return events.read_events(self.log_path)


class RunStore:
    """Vault-bound factory and lookup for runs."""

    def __init__(self, vault: Path) -> None:
        self._vault = Path(vault)
        self._runs_dir = self._vault / RUNS_DIR
        self._index_path = self._runs_dir / RUNS_INDEX_FILE

    @property
    def runs_dir(self) -> Path:
        return self._runs_dir

    @property
    def index_path(self) -> Path:
        return self._index_path

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def create(
        self,
        kind: str,
        *,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Run:
        run_id = run_id or _new_run_id()
        log_path = self._runs_dir / f"{run_id}.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        started_at = events.now_iso()
        run = Run(
            run_id=run_id,
            kind=kind,
            log_path=log_path,
            index_path=self._index_path,
            started_at=started_at,
            status=RunStatus.RUNNING,
            metadata=metadata or {},
        )
        run.append_event(events.run_started(run_id, kind, **(metadata or {})))
        _append_index(
            self._index_path,
            RunSummary(
                run_id=run_id,
                kind=kind,
                status=RunStatus.RUNNING,
                started_at=started_at,
            ),
        )
        return run

    def open(self, run_id: str) -> Run | None:
        """Re-attach to an existing run by id (for resume / inspection).

        Returns ``None`` if the run's log file does not exist. Note
        that this does not by itself transition status; callers may
        inspect :meth:`Run.iter_events` and/or call
        :meth:`Run.complete` / :meth:`Run.fail` to finalize.
        """

        log_path = self._runs_dir / f"{run_id}.jsonl"
        if not log_path.exists():
            return None
        summary = self._summary_for(run_id)
        if summary is None:
            return None
        return Run(
            run_id=run_id,
            kind=summary.kind,
            log_path=log_path,
            index_path=self._index_path,
            started_at=summary.started_at,
            status=summary.status,
        )

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list(self) -> list[RunSummary]:
        """Return latest summary per run id, newest first by started_at."""

        latest: dict[str, RunSummary] = {}
        if not self._index_path.exists():
            return []
        with self._index_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict) or "run_id" not in record:
                    continue
                summary = RunSummary.from_dict(record)
                latest[summary.run_id] = summary  # last write wins
        return sorted(
            latest.values(),
            key=lambda s: (s.started_at, s.run_id),
            reverse=True,
        )

    def _summary_for(self, run_id: str) -> RunSummary | None:
        for summary in self.list():
            if summary.run_id == run_id:
                return summary
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_run_id() -> str:
    """Generate a sortable, opaque run id."""

    return uuid.uuid4().hex[:16]


def _append_index(path: Path, summary: RunSummary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary.to_dict(), ensure_ascii=False) + "\n")
