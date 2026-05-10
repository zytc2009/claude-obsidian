"""Tests for skills.obsidian.pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.obsidian.pipeline import Pipeline, Step
from skills.obsidian.runs import RunStatus, RunStore


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    return root


@pytest.fixture
def store(vault: Path) -> RunStore:
    return RunStore(vault)


class TestApplyMode:
    def test_runs_steps_in_order_and_passes_context(self, store: RunStore) -> None:
        order: list[str] = []

        def step_a(ctx: dict) -> dict:
            order.append("a")
            return {"a_value": 1}

        def step_b(ctx: dict) -> dict:
            order.append("b")
            return {"b_value": ctx["a_value"] + 1}

        pipeline = Pipeline("test", [Step("a", step_a), Step("b", step_b)])
        run = store.create("test")
        result = pipeline.run(run)

        assert order == ["a", "b"]
        assert result.status == RunStatus.DONE
        assert result.context == {"a_value": 1, "b_value": 2}
        assert [s.status for s in result.steps] == ["done", "done"]

    def test_emits_step_started_and_step_done_events(self, store: RunStore) -> None:
        pipeline = Pipeline(
            "test",
            [Step("only", lambda ctx: {"count": 5})],
        )
        run = store.create("test")
        pipeline.run(run)

        types = [ev["event_type"] for ev in run.iter_events()]
        assert "step_started" in types
        assert "step_done" in types
        assert types[-1] == "run_done"

    def test_step_failure_halts_pipeline(self, store: RunStore) -> None:
        ran: list[str] = []

        def good(ctx: dict) -> dict:
            ran.append("good")
            return {}

        def bad(ctx: dict) -> dict:
            ran.append("bad")
            raise RuntimeError("nope")

        def never(ctx: dict) -> dict:
            ran.append("never")
            return {}

        pipeline = Pipeline(
            "test",
            [Step("good", good), Step("bad", bad), Step("never", never)],
        )
        run = store.create("test")
        result = pipeline.run(run)

        assert ran == ["good", "bad"]
        assert result.status == RunStatus.FAILED
        assert result.steps[-1].status == "failed"
        assert "RuntimeError" in result.steps[-1].error

    def test_failure_emits_run_failed(self, store: RunStore) -> None:
        def boom(ctx: dict) -> dict:
            raise ValueError("kaboom")

        pipeline = Pipeline("t", [Step("boom", boom)])
        run = store.create("t")
        pipeline.run(run)

        types = [ev["event_type"] for ev in run.iter_events()]
        assert "step_failed" in types
        assert types[-1] == "run_failed"

    def test_step_returning_none_does_not_break_context(self, store: RunStore) -> None:
        pipeline = Pipeline("t", [Step("noop", lambda ctx: None)])
        run = store.create("t")
        result = pipeline.run(run, context={"keep": True})
        assert result.context == {"keep": True}
        assert result.status == RunStatus.DONE


class TestDryRun:
    def test_runs_no_step_fn_in_dry_run(self, store: RunStore) -> None:
        ran: list[str] = []

        def step(ctx: dict) -> dict:
            ran.append("ran")
            return {}

        pipeline = Pipeline(
            "t",
            [
                Step("a", step, plan_fn=lambda ctx: {"would_do": "fetch"}),
                Step("b", step),
            ],
        )
        run = store.create("t")
        result = pipeline.run(run, dry_run=True)

        assert ran == []
        assert result.status == RunStatus.DONE
        assert [s.status for s in result.steps] == ["planned", "planned"]

    def test_dry_run_emits_step_planned_events(self, store: RunStore) -> None:
        pipeline = Pipeline(
            "t",
            [Step("a", lambda c: {}, plan_fn=lambda c: {"x": 1})],
        )
        run = store.create("t")
        pipeline.run(run, dry_run=True)

        events = list(run.iter_events())
        planned = [e for e in events if e["event_type"] == "step_planned"]
        assert planned and planned[0]["x"] == 1

    def test_dry_run_without_plan_fn_emits_empty_planned(
        self, store: RunStore
    ) -> None:
        pipeline = Pipeline("t", [Step("a", lambda c: {})])
        run = store.create("t")
        result = pipeline.run(run, dry_run=True)
        assert result.steps[0].status == "planned"
        assert result.steps[0].data == {}


class TestSummaryFormatting:
    def test_default_summary_renders_compact_kv(self, store: RunStore) -> None:
        pipeline = Pipeline(
            "t",
            [Step("a", lambda c: {"count": 3, "items": [1, 2, 3], "ok": True})],
        )
        run = store.create("t")
        result = pipeline.run(run)
        s = result.steps[0].summary
        assert "count=3" in s
        assert "items=<3>" in s
        assert "ok=True" in s

    def test_custom_summary_format_used(self, store: RunStore) -> None:
        pipeline = Pipeline(
            "t",
            [
                Step(
                    "a",
                    run_fn=lambda c: {"n": 7},
                    summary_format=lambda u: f"saw {u['n']} things",
                )
            ],
        )
        run = store.create("t")
        result = pipeline.run(run)
        assert result.steps[0].summary == "saw 7 things"
