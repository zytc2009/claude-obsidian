"""
pipeline.py — Composable Steps over a Run.

Pipelines model multi-stage flows (capture → write → relation extract
→ topic candidate → cascade) so each stage emits structured events
into a shared :class:`runs.Run`. A failure in step N halts the
pipeline; the run is marked failed, but events from steps 0..N-1 are
preserved for inspection.

Two execution modes:

  - ``apply`` (default): each step's ``run_fn(ctx)`` executes; events
    ``step_started`` and ``step_done``/``step_failed`` bracket it.
  - ``dry_run``: no step executes; instead each step emits a single
    ``step_planned`` event with whatever ``plan_fn(ctx)`` returns
    (or an empty dict if no planner is provided).

Per the design discussion: interactive Claude Code calls default to
``apply`` (the user is in the loop already); cron / automated callers
may opt into ``dry_run`` to preview a plan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

try:
    from . import events
    from .runs import Run, RunStatus
except ImportError:  # script-mode fallback
    import events  # type: ignore[no-redef]
    from runs import Run, RunStatus  # type: ignore[no-redef]

StepFn = Callable[[dict[str, Any]], dict[str, Any] | None]
PlanFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class Step:
    """One stage of a pipeline.

    ``run_fn`` receives the current context dict and may return a dict
    of *updates* to merge into the context. Returning ``None`` means
    "no context changes". The returned dict is also stored verbatim as
    the step's ``summary_data`` event payload, so callers can attach
    counts, paths, etc. for later inspection.
    """

    name: str
    run_fn: StepFn
    plan_fn: PlanFn | None = None
    """Optional dry-run preview. Receives context, returns planned changes."""

    summary_format: Callable[[dict[str, Any]], str] | None = None
    """Optional formatter for the human-readable step summary string."""


@dataclass
class StepResult:
    name: str
    status: str  # "done" | "failed" | "planned"
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class PipelineResult:
    status: RunStatus
    steps: list[StepResult]
    context: dict[str, Any]


@dataclass
class Pipeline:
    """Ordered sequence of :class:`Step` objects."""

    name: str
    steps: list[Step]

    def run(
        self,
        run: Run,
        context: dict[str, Any] | None = None,
        *,
        dry_run: bool = False,
    ) -> PipelineResult:
        ctx: dict[str, Any] = dict(context or {})
        results: list[StepResult] = []

        if dry_run:
            for step in self.steps:
                planned = step.plan_fn(ctx) if step.plan_fn else {}
                run.append_event(events.step_planned(run.run_id, step.name, **planned))
                results.append(
                    StepResult(name=step.name, status="planned", data=planned)
                )
            run.complete(summary=f"dry-run: {len(self.steps)} step(s) planned")
            return PipelineResult(status=RunStatus.DONE, steps=results, context=ctx)

        for step in self.steps:
            run.append_event(events.step_started(run.run_id, step.name))
            try:
                updates = step.run_fn(ctx) or {}
            except Exception as exc:  # noqa: BLE001 — propagate as failure event
                error_msg = f"{type(exc).__name__}: {exc}"
                run.append_event(
                    events.step_failed(run.run_id, step.name, error=error_msg)
                )
                results.append(
                    StepResult(name=step.name, status="failed", error=error_msg)
                )
                run.fail(error=f"step '{step.name}' failed: {error_msg}")
                return PipelineResult(
                    status=RunStatus.FAILED, steps=results, context=ctx
                )

            ctx.update(updates)
            summary_str = (
                step.summary_format(updates)
                if step.summary_format
                else _default_summary(updates)
            )
            event_payload = _event_safe_payload(updates)
            run.append_event(
                events.step_done(
                    run.run_id, step.name, summary=summary_str, **event_payload
                )
            )
            results.append(
                StepResult(
                    name=step.name,
                    status="done",
                    summary=summary_str,
                    data=dict(updates),
                )
            )

        run.complete(summary=f"{len(results)} step(s) completed")
        return PipelineResult(status=RunStatus.DONE, steps=results, context=ctx)


def _event_safe_payload(updates: dict[str, Any]) -> dict[str, Any]:
    """Project ``updates`` to a JSON-safe subset for event payloads.

    Convention: keys starting with ``_`` are treated as private
    context-only state and dropped from the event log. Values that
    can't round-trip through JSON are likewise dropped (they may still
    flow between steps via the context).
    """

    safe: dict[str, Any] = {}
    for key, value in updates.items():
        if key.startswith("_"):
            continue
        try:
            json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            # Non-serializable value — skip from the event, but the
            # caller already merged it into ctx.
            continue
        safe[key] = value
    return safe


def _default_summary(updates: dict[str, Any]) -> str:
    """Render ``updates`` as a compact ``key=value`` string for logs.

    Skips ``_``-prefixed keys (private context flow).
    """

    if not updates:
        return ""
    parts = []
    for key, value in updates.items():
        if key.startswith("_"):
            continue
        if isinstance(value, (str, int, float, bool)):
            parts.append(f"{key}={value}")
        elif isinstance(value, (list, tuple, set)):
            parts.append(f"{key}=<{len(value)}>")
        elif isinstance(value, dict):
            parts.append(f"{key}=<dict:{len(value)}>")
        else:
            parts.append(f"{key}=<{type(value).__name__}>")
    return " ".join(parts)


def make_step(name: str, fn: StepFn, **kwargs: Any) -> Step:
    """Convenience constructor for ad-hoc steps in tests / scripts."""

    return Step(name=name, run_fn=fn, **kwargs)
