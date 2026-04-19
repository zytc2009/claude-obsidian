import time
from pathlib import Path
from skills.obsidian.task_queue import TaskQueue, TaskStatus, Task


class TestTaskQueue:
    def test_submit_creates_pending_task(self, tmp_path):
        q = TaskQueue(tmp_path)
        task_id = q.submit("https://example.com/article")
        task = q.get(task_id)
        assert task is not None
        assert task.url == "https://example.com/article"
        assert task.status == TaskStatus.PENDING
        assert task.progress == 0

    def test_update_changes_status(self, tmp_path):
        q = TaskQueue(tmp_path)
        task_id = q.submit("https://example.com")
        q.update(task_id, status=TaskStatus.RUNNING, progress=50, message="Fetching...")
        task = q.get(task_id)
        assert task.status == TaskStatus.RUNNING
        assert task.progress == 50
        assert task.message == "Fetching..."

    def test_update_nonexistent_task_is_noop(self, tmp_path):
        q = TaskQueue(tmp_path)
        q.update("nonexistent", status=TaskStatus.DONE)  # should not raise

    def test_list_all_returns_all_tasks(self, tmp_path):
        q = TaskQueue(tmp_path)
        q.submit("https://a.com")
        q.submit("https://b.com")
        assert len(q.list_all()) == 2

    def test_pending_filters_by_status(self, tmp_path):
        q = TaskQueue(tmp_path)
        id1 = q.submit("https://a.com")
        id2 = q.submit("https://b.com")
        q.update(id1, status=TaskStatus.DONE)
        pending = q.pending()
        assert len(pending) == 1
        assert pending[0].task_id == id2

    def test_state_persists_across_instances(self, tmp_path):
        q1 = TaskQueue(tmp_path)
        task_id = q1.submit("https://example.com")
        q2 = TaskQueue(tmp_path)
        task = q2.get(task_id)
        assert task is not None
        assert task.url == "https://example.com"

    def test_task_dict_roundtrip(self, tmp_path):
        q = TaskQueue(tmp_path)
        task_id = q.submit("https://example.com")
        q.update(task_id, status=TaskStatus.DONE, result_path="/vault/note.md")
        task = q.get(task_id)
        assert task.status == TaskStatus.DONE
        assert task.result_path == "/vault/note.md"

    def test_state_file_created_in_vault(self, tmp_path):
        q = TaskQueue(tmp_path)
        q.submit("https://example.com")
        state_file = tmp_path / ".obsidian-tasks.json"
        assert state_file.exists()
