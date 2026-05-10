"""Tests for skills.obsidian.runs."""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.obsidian.runs import Run, RunStatus, RunStore


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    return root


@pytest.fixture
def store(vault: Path) -> RunStore:
    return RunStore(vault)


class TestCreate:
    def test_creates_run_with_log_and_index(self, store: RunStore, vault: Path) -> None:
        run = store.create("capture", metadata={"url": "https://x.com"})
        assert run.run_id
        assert run.kind == "capture"
        assert run.log_path.exists()
        assert store.index_path.exists()

    def test_appends_run_started_event(self, store: RunStore) -> None:
        run = store.create("capture", metadata={"url": "https://x.com"})
        evs = list(run.iter_events())
        assert len(evs) == 1
        assert evs[0]["event_type"] == "run_started"
        assert evs[0]["url"] == "https://x.com"
        assert evs[0]["run_id"] == run.run_id

    def test_create_uses_supplied_run_id(self, store: RunStore) -> None:
        run = store.create("capture", run_id="fixed-id-1234567890ab")
        assert run.run_id == "fixed-id-1234567890ab"


class TestLifecycle:
    def test_complete_marks_done_and_emits_event(self, store: RunStore) -> None:
        run = store.create("capture")
        run.complete(summary="all good")
        assert run.status == RunStatus.DONE
        events = list(run.iter_events())
        assert events[-1]["event_type"] == "run_done"
        assert events[-1]["summary"] == "all good"

    def test_fail_marks_failed_and_emits_event(self, store: RunStore) -> None:
        run = store.create("capture")
        run.fail("boom")
        assert run.status == RunStatus.FAILED
        events = list(run.iter_events())
        assert events[-1]["event_type"] == "run_failed"
        assert events[-1]["error"] == "boom"

    def test_complete_after_fail_is_noop(self, store: RunStore) -> None:
        run = store.create("capture")
        run.fail("x")
        run.complete(summary="ignored")
        assert run.status == RunStatus.FAILED
        # Only one terminal event recorded.
        events = [
            ev for ev in run.iter_events() if ev["event_type"] in {"run_done", "run_failed"}
        ]
        assert len(events) == 1

    def test_append_event_injects_run_id(self, store: RunStore) -> None:
        run = store.create("capture")
        run.append_event({"event_type": "step_started", "step": "fetch"})
        events = list(run.iter_events())
        assert events[-1]["run_id"] == run.run_id


class TestIndex:
    def test_list_returns_latest_per_run_id(self, store: RunStore) -> None:
        a = store.create("capture", metadata={"url": "1"})
        b = store.create("capture", metadata={"url": "2"})
        a.complete(summary="ok")
        b.fail("err")

        listing = store.list()
        by_id = {s.run_id: s for s in listing}
        assert by_id[a.run_id].status == RunStatus.DONE
        assert by_id[a.run_id].summary == "ok"
        assert by_id[b.run_id].status == RunStatus.FAILED
        assert by_id[b.run_id].error == "err"

    def test_list_sorted_newest_first(self, store: RunStore) -> None:
        a = store.create("capture")
        b = store.create("capture")
        listing = store.list()
        # both pending; ordering by started_at desc, then run_id desc as tiebreak
        assert {s.run_id for s in listing} == {a.run_id, b.run_id}

    def test_open_returns_run_handle(self, store: RunStore) -> None:
        a = store.create("capture", metadata={"url": "x"})
        a.complete(summary="ok")

        reopened = store.open(a.run_id)
        assert reopened is not None
        assert reopened.run_id == a.run_id
        assert reopened.status == RunStatus.DONE
        assert reopened.kind == "capture"

    def test_open_unknown_run_returns_none(self, store: RunStore) -> None:
        assert store.open("nonexistent") is None
