"""Integration test: task_runner now drives a Run + Pipeline.

Confirms that:
  1. existing TaskQueue summary semantics still work
  2. a runs/<run_id>.jsonl event log is created
  3. capture-pipeline events (step_started/step_done for fetch+write) appear
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from skills.obsidian.importers.base import ImportResult
from skills.obsidian.runs import RunStore, RunStatus
from skills.obsidian.task_queue import TaskQueue, TaskStatus


def _import_result() -> ImportResult:
    return ImportResult(
        title="Test Article",
        content="Body content here.",
        summary="One-line summary.",
        platform="wechat",
        source_url="https://example.com/post/1",
        metadata={"author": "Alice"},
    )


def test_task_creates_run_log_with_capture_events(tmp_path: Path) -> None:
    queue = TaskQueue(tmp_path)
    task_id = queue.submit("https://example.com/post/1")
    task = queue.get(task_id)

    import skills.obsidian.task_runner as tr

    note_path = tmp_path / "Literature - Test Article.md"

    async def go() -> None:
        with patch.object(tr, "_fetch_async", new=AsyncMock(return_value=_import_result())):
            with patch.object(tr, "write_note", return_value=note_path):
                await tr._run_task(queue, task, tmp_path)

    asyncio.run(go())

    final = queue.get(task_id)
    assert final.status == TaskStatus.DONE

    # A run log must exist with the expected step events.
    store = RunStore(tmp_path)
    runs = store.list()
    assert len(runs) == 1
    run_summary = runs[0]
    assert run_summary.kind == "capture"
    assert run_summary.status == RunStatus.DONE

    log_path = store.runs_dir / f"{run_summary.run_id}.jsonl"
    assert log_path.exists()

    types = [
        json.loads(line)["event_type"]
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "run_started" in types
    assert types.count("step_started") == 2  # fetch, write
    assert types.count("step_done") == 2
    assert types[-1] == "run_done"


def test_task_failure_marks_run_failed(tmp_path: Path) -> None:
    queue = TaskQueue(tmp_path)
    task_id = queue.submit("https://example.com/post/1")
    task = queue.get(task_id)

    import skills.obsidian.task_runner as tr

    async def go() -> None:
        with patch.object(
            tr, "_fetch_async", new=AsyncMock(side_effect=RuntimeError("network"))
        ):
            await tr._run_task(queue, task, tmp_path)

    asyncio.run(go())

    final = queue.get(task_id)
    assert final.status == TaskStatus.FAILED
    assert "network" in final.error

    store = RunStore(tmp_path)
    runs = store.list()
    assert len(runs) == 1
    assert runs[0].status == RunStatus.FAILED
    assert "network" in runs[0].error
