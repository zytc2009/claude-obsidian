"""
Async import task runner for claude-obsidian.

Commands:
  submit  --vault VAULT --url URL [--url URL ...]   Add URLs to queue, print task IDs
  run     --vault VAULT [--workers N]               Run all pending tasks concurrently
  status  --vault VAULT                             Print current task states
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .task_queue import TaskQueue, TaskStatus

try:
    from .importers.router import _fetch_async
except ImportError:
    from importers.router import _fetch_async  # type: ignore[no-redef]

try:
    from .obsidian_writer import write_note
except ImportError:
    from obsidian_writer import write_note  # type: ignore[no-redef]


async def _run_task(queue: TaskQueue, task_id: str, vault: Path) -> None:
    queue.update(task_id, status=TaskStatus.RUNNING, progress=10, message="Fetching...")
    task = queue.get(task_id)
    if task is None:
        return
    try:
        result = await _fetch_async(task.url)
        queue.update(task_id, progress=60, message="Writing note...")

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
            vault=vault,
            note_type="literature",
            title=result.title,
            fields=fields,
            is_draft=False,
        )
        queue.update(
            task_id,
            status=TaskStatus.DONE,
            progress=100,
            message="Done",
            result_path=str(filepath),
        )
        print(f"[{task_id}] Done → {filepath.relative_to(vault)}")
    except Exception as exc:
        queue.update(task_id, status=TaskStatus.FAILED, error=str(exc), message="Failed")
        print(f"[{task_id}] Failed: {exc}", file=sys.stderr)


async def _run_all(queue: TaskQueue, vault: Path, workers: int) -> None:
    pending = queue.pending()
    if not pending:
        print("No pending tasks.")
        return
    sem = asyncio.Semaphore(workers)

    async def _guarded(task_id: str) -> None:
        async with sem:
            await _run_task(queue, task_id, vault)

    await asyncio.gather(*[_guarded(t.task_id) for t in pending])


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
