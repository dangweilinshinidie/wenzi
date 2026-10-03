import asyncio
import uuid
from datetime import datetime
from typing import Any

from app.models import TaskResult, TaskStatus
from app.config import settings
from app.services import storage


class TaskManager:
    def __init__(self):
        storage.init_db()
        self._tasks: dict[str, TaskResult] = {task.task_id: task for task in storage.load_tasks(settings.MAX_TASKS)}
        self._lock = asyncio.Lock()
        for task in self._tasks.values():
            if task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                task.status = TaskStatus.FAILED
                task.error = "服务重启时任务仍在执行，任务已中止。"
                task.error_type = "service_restarted"
                task.completed_at = datetime.now()
                storage.save_task(task)
        self._queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue(maxsize=settings.MAX_TASKS)
        self._workers_started = False

    async def create_task(self, task: TaskResult | None = None) -> str:
        task_id = task.task_id if task else uuid.uuid4().hex[:8]
        task = task or TaskResult(task_id=task_id)
        async with self._lock:
            self._tasks[task_id] = task
            storage.save_task(task)
            await self._cleanup_old_tasks()
        return task_id

    async def update_task(self, task_id: str, **kwargs: Any) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            for key, value in kwargs.items():
                if key not in TaskResult.model_fields:
                    continue
                setattr(task, key, value)
            task.updated_at = datetime.now()
            if kwargs.get("status") in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                task.completed_at = datetime.now()
            if task.status == TaskStatus.COMPLETED and not task.file_path:
                try:
                    task.file_path = storage.write_output(task)
                except Exception:
                    # Output failure must never change a successful transcription into failure.
                    task.progress = f"{task.progress}（文案落盘失败）"
            storage.save_task(task)
            if task.status == TaskStatus.COMPLETED and task.normalized_url:
                storage.put_cache(storage.cache_key(task.platform, task.normalized_url), task)

    async def get_task(self, task_id: str) -> TaskResult | None:
        async with self._lock:
            return self._tasks.get(task_id)

    async def _cleanup_old_tasks(self) -> None:
        if len(self._tasks) <= settings.MAX_TASKS:
            return
        completed = [(tid, t) for tid, t in self._tasks.items() if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)]
        completed.sort(key=lambda x: x[1].created_at)
        for tid, _ in completed[: len(self._tasks) - settings.MAX_TASKS]:
            self._tasks.pop(tid, None)

    def queue_stats(self) -> dict[str, int]:
        tasks = list(self._tasks.values())
        return {
            "queued": sum(t.status == TaskStatus.PENDING for t in tasks),
            "in_progress": sum(t.status not in (TaskStatus.PENDING, TaskStatus.COMPLETED, TaskStatus.FAILED) for t in tasks),
            "completed": sum(t.status == TaskStatus.COMPLETED for t in tasks),
        }



task_manager = TaskManager()
