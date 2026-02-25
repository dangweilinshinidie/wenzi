import uuid
import asyncio
from datetime import datetime
from typing import Any

from app.models import TaskResult, TaskStatus
from app.config import settings


class TaskManager:
    def __init__(self):
        self._tasks: dict[str, TaskResult] = {}
        self._lock = asyncio.Lock()

    async def create_task(self) -> str:
        task_id = uuid.uuid4().hex[:8]
        task = TaskResult(task_id=task_id)
        async with self._lock:
            self._tasks[task_id] = task
            await self._cleanup_old_tasks()
        return task_id

    async def update_task(self, task_id: str, **kwargs: Any) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return

            for key, value in kwargs.items():
                # Ignore unsupported fields to keep updates resilient.
                if key not in TaskResult.model_fields:
                    continue
                setattr(task, key, value)

            if kwargs.get("status") in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                task.completed_at = datetime.now()

    async def get_task(self, task_id: str) -> TaskResult | None:
        async with self._lock:
            return self._tasks.get(task_id)

    async def _cleanup_old_tasks(self) -> None:
        if len(self._tasks) <= settings.MAX_TASKS:
            return

        completed = [
            (tid, t) for tid, t in self._tasks.items()
            if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
        ]
        completed.sort(key=lambda x: x[1].created_at)

        remove_count = len(self._tasks) - settings.MAX_TASKS
        for tid, _ in completed[:remove_count]:
            self._tasks.pop(tid, None)


task_manager = TaskManager()
