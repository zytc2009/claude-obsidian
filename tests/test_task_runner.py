import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skills.obsidian.task_queue import Task, TaskQueue, TaskStatus
from skills.obsidian.importers.base import ImportResult


def _make_import_result(title="Test Article", content="Content here", summary="Summary"):
    return ImportResult(
        title=title,
        content=content,
        summary=summary,
        platform="wechat",
        source_url="https://example.com",
        metadata={"author": "Test Author"},
    )


class TestRunTask:
    def test_success_updates_status_to_done(self, tmp_path):
        queue = TaskQueue(tmp_path)
        task_id = queue.submit("https://example.com")
        task = queue.get(task_id)

        import skills.obsidian.task_runner as tr

        async def run():
            with patch.object(tr, "_fetch_async", new=AsyncMock(return_value=_make_import_result())):
                with patch.object(tr, "write_note", return_value=tmp_path / "note.md"):
                    await tr._run_task(queue, task, tmp_path)

        asyncio.run(run())
        final = queue.get(task_id)
        assert final.status == TaskStatus.DONE
        assert final.progress == 100

    def test_failure_updates_status_to_failed(self, tmp_path):
        queue = TaskQueue(tmp_path)
        task_id = queue.submit("https://example.com")
        task = queue.get(task_id)

        import skills.obsidian.task_runner as tr

        async def run():
            with patch.object(tr, "_fetch_async", new=AsyncMock(side_effect=RuntimeError("network error"))):
                await tr._run_task(queue, task, tmp_path)

        asyncio.run(run())
        final = queue.get(task_id)
        assert final.status == TaskStatus.FAILED
        assert "network error" in final.error


class TestRunAll:
    def test_no_pending_tasks_prints_message(self, tmp_path, capsys):
        queue = TaskQueue(tmp_path)

        import skills.obsidian.task_runner as tr

        asyncio.run(tr._run_all(queue, tmp_path, workers=3))
        assert "No pending tasks" in capsys.readouterr().out

    def test_runs_all_pending_tasks(self, tmp_path):
        queue = TaskQueue(tmp_path)
        id1 = queue.submit("https://a.com")
        id2 = queue.submit("https://b.com")

        import skills.obsidian.task_runner as tr

        async def run():
            with patch.object(tr, "_fetch_async", new=AsyncMock(return_value=_make_import_result())):
                with patch.object(tr, "write_note", return_value=tmp_path / "note.md"):
                    await tr._run_all(queue, tmp_path, workers=2)

        asyncio.run(run())
        assert queue.get(id1).status == TaskStatus.DONE
        assert queue.get(id2).status == TaskStatus.DONE


class TestCmdSubmit:
    def test_submit_creates_tasks(self, tmp_path, capsys):
        import skills.obsidian.task_runner as tr

        args = MagicMock()
        args.vault = str(tmp_path)
        args.url = ["https://a.com", "https://b.com"]

        tr.cmd_submit(args)
        out = capsys.readouterr().out
        assert "Submitted" in out
        assert "https://a.com" in out
        assert "https://b.com" in out
        assert len(TaskQueue(tmp_path).list_all()) == 2


class TestCmdStatus:
    def test_status_shows_pending_tasks(self, tmp_path, capsys):
        queue = TaskQueue(tmp_path)
        queue.submit("https://example.com")

        import skills.obsidian.task_runner as tr

        args = MagicMock()
        args.vault = str(tmp_path)
        tr.cmd_status(args)
        out = capsys.readouterr().out
        assert "pending" in out
        assert "https://example.com" in out

    def test_status_no_tasks_message(self, tmp_path, capsys):
        import skills.obsidian.task_runner as tr

        args = MagicMock()
        args.vault = str(tmp_path)
        tr.cmd_status(args)
        assert "No tasks" in capsys.readouterr().out
