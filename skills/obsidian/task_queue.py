from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Task:
    task_id: str
    url: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    message: str = ""
    result_path: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        d = dict(d)
        d["status"] = TaskStatus(d["status"])
        return cls(**d)


class TaskQueue:
    _STATE_FILE = ".obsidian-tasks.json"

    def __init__(self, vault: Path) -> None:
        self.vault = vault
        self._path = vault / self._STATE_FILE
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Task]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return {tid: Task.from_dict(t) for tid, t in data.items()}
        except (json.JSONDecodeError, KeyError, TypeError):
            return {}

    def _save(self, tasks: dict[str, Task]) -> None:
        self._path.write_text(
            json.dumps(
                {tid: t.to_dict() for tid, t in tasks.items()},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def submit(self, url: str) -> str:
        """Add a URL import task and return its task_id."""
        with self._lock:
            tasks = self._load()
            task_id = uuid.uuid4().hex[:8]
            tasks[task_id] = Task(task_id=task_id, url=url)
            self._save(tasks)
        return task_id

    def update(self, task_id: str, **kwargs: Any) -> None:
        with self._lock:
            tasks = self._load()
            if task_id not in tasks:
                return
            task = tasks[task_id]
            for key, val in kwargs.items():
                setattr(task, key, val)
            task.updated_at = time.time()
            self._save(tasks)

    def get(self, task_id: str) -> Task | None:
        return self._load().get(task_id)

    def list_all(self) -> list[Task]:
        return list(self._load().values())

    def pending(self) -> list[Task]:
        return [t for t in self._load().values() if t.status == TaskStatus.PENDING]
