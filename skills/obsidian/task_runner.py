"""
Async import task runner for claude-obsidian.

Commands:
  submit  --vault VAULT --url URL [--url URL ...]   Add URLs to queue, print task IDs
  run     --vault VAULT [--workers N]               Run all pending tasks concurrently
  status  --vault VAULT                             Print current task states

Each task executes as a :class:`pipeline.Pipeline` over a
:class:`runs.Run`, so detailed events land in ``<vault>/runs/<run_id>.jsonl``
while the user-visible state summary stays in ``.obsidian-tasks.json``
via :class:`TaskQueue`.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .pipeline import Pipeline, Step
from .runs import RunStore
from .task_queue import Task, TaskQueue, TaskStatus

try:
    from .importers.router import _fetch_async
except ImportError:
    from importers.router import _fetch_async  # type: ignore[no-redef]

try:
    from .obsidian_writer import write_note
except ImportError:
    from obsidian_writer import write_note  # type: ignore[no-redef]


def _build_capture_pipeline() -> Pipeline:
    """Build the fetch → write capture pipeline.

    Steps reference the module-level ``_fetch_async`` / ``write_note``
    so tests can swap them via ``unittest.mock.patch.object``.
    """

    def step_fetch(ctx: dict) -> dict:
        url = ctx["url"]
        result = asyncio.run(_fetch_async(url)) if not ctx.get("_inline") else ctx["_fetch_result"]
        # Underscore prefix: keep the heavy ImportResult in ctx but
        # don't write it into the step_done event payload.
        return {"_import_result": result, "url": url}

    def step_write(ctx: dict) -> dict:
        result = ctx["_import_result"]
        fields: dict = {
            "source": result.source_url,
            "platform": result.platform,
            "source_url": result.source_url,
            "核心观点": result.summary,
            "原文主要内容": result.content,
        }
        if isinstance(result.metadata, dict):
            author = result.metadata.get("author", "")
            if author:
                fields["author"] = author

        filepath = write_note(
            vault=ctx["vault"],
            note_type="literature",
            title=result.title,
            fields=fields,
            is_draft=False,
        )
        return {"filepath": filepath, "note_path": str(filepath)}

    return Pipeline(
        name="capture",
        steps=[
            Step(name="fetch", run_fn=step_fetch),
            Step(name="write", run_fn=step_write),
        ],
    )


async def _run_task(queue: TaskQueue, task: "Task", vault: Path) -> None:
    """Execute a single task as a capture pipeline.

    The TaskQueue fields stay the user-facing summary; detailed
    structured events land in ``runs/<run_id>.jsonl``.
    """

    task_id = task.task_id
    queue.update(task_id, status=TaskStatus.RUNNING, progress=10, message="Fetching...")

    store = RunStore(vault)
    run = store.create("capture", metadata={"url": task.url, "task_id": task_id})

    try:
        result = await _fetch_async(task.url)
        queue.update(task_id, progress=60, message="Writing note...")

        # We already awaited the network call above (preserves the
        # existing test seam where _fetch_async is patched); pass the
        # cached result into the pipeline via the ``_inline`` flag.
        pipeline = _build_capture_pipeline()
        outcome = pipeline.run(
            run,
            context={
                "url": task.url,
                "vault": vault,
                "_inline": True,
                "_fetch_result": result,
            },
        )

        if outcome.status.value != "done":
            failed = next((s for s in outcome.steps if s.status == "failed"), None)
            err = failed.error if failed else "pipeline failed"
            raise RuntimeError(err)

        filepath = outcome.context.get("filepath")
        queue.update(
            task_id,
            status=TaskStatus.DONE,
            progress=100,
            message="Done",
            result_path=str(filepath) if filepath else "",
        )
        if filepath:
            print(f"[{task_id}] Done → {filepath.relative_to(vault)}")
        else:
            print(f"[{task_id}] Done")
    except Exception as exc:
        queue.update(task_id, status=TaskStatus.FAILED, error=str(exc), message="Failed")
        # Mark the run as failed for trace consistency. open() may have
        # already been finalized by Pipeline.run if the failure was in
        # a step; fail() is idempotent on terminal status.
        run.fail(error=str(exc))
        print(f"[{task_id}] Failed: {exc}", file=sys.stderr)


async def _run_all(queue: TaskQueue, vault: Path, workers: int) -> None:
    pending = queue.pending()
    if not pending:
        print("No pending tasks.")
        return
    sem = asyncio.Semaphore(workers)

    async def _guarded(task: Task) -> None:
        async with sem:
            await _run_task(queue, task, vault)

    await asyncio.gather(*[_guarded(t) for t in pending])


def cmd_submit(args: argparse.Namespace) -> None:
    vault = Path(args.vault).expanduser()
    queue = TaskQueue(vault)
    for url in args.url:
        task_id = queue.submit(url)
        print(f"Submitted [{task_id}]: {url}")


def cmd_run(args: argparse.Namespace) -> None:
    vault = Path(args.vault).expanduser()
    queue = TaskQueue(vault)
    asyncio.run(_run_all(queue, vault, args.workers))


def cmd_status(args: argparse.Namespace) -> None:
    vault = Path(args.vault).expanduser()
    queue = TaskQueue(vault)
    tasks = queue.list_all()
    if not tasks:
        print("No tasks.")
        return
    status_icons = {"pending": "[pending]", "running": "[running]", "done": "[done]", "failed": "[failed]"}
    for task in sorted(tasks, key=lambda t: t.created_at):
        icon = status_icons.get(task.status.value, "?")
        print(f"{icon} [{task.task_id}] {task.status.value:8s} {task.progress:3d}% | {task.url}")
        if task.result_path:
            print(f"   -> {task.result_path}")
        if task.error:
            print(f"   ERROR: {task.error}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Obsidian import task runner")
    sub = parser.add_subparsers(dest="command", required=True)

    p_submit = sub.add_parser("submit", help="Submit URLs to the import queue")
    p_submit.add_argument("--vault", required=True)
    p_submit.add_argument("--url", required=True, action="append")

    p_run = sub.add_parser("run", help="Run all pending tasks")
    p_run.add_argument("--vault", required=True)
    p_run.add_argument("--workers", type=int, default=3)

    p_status = sub.add_parser("status", help="Show task status")
    p_status.add_argument("--vault", required=True)

    args = parser.parse_args(argv)
    {"submit": cmd_submit, "run": cmd_run, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    main()
