from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import Segment, TaskResult, TaskStatus, TranscriptSource
from app.services import storage


class StorageTests(unittest.TestCase):
    def test_roundtrip_cache_output_and_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(storage, "DATA_DIR", root / "data"), patch.object(storage, "DB_PATH", root / "data" / "app.db"), patch.object(storage, "OUTPUT_DIR", root / "data" / "output"):
                storage.init_db()
                task = TaskResult(task_id="test024", status=TaskStatus.COMPLETED, normalized_url="https://example.test/v/1", platform="generic", video_title="中文 标题", text="转写内容", source=TranscriptSource.SUBTITLE, segments=[Segment(start=0, end=1.5, text="第一句")])
                task.file_path = storage.write_output(task)
                storage.save_task(task)
                loaded = storage.get_task(task.task_id)
                self.assertEqual(loaded.text, "转写内容")
                self.assertEqual(loaded.segments[0].text, "第一句")
                key = storage.cache_key(task.platform, task.normalized_url)
                storage.put_cache(key, task)
                self.assertEqual(storage.get_cached(key).task_id, task.task_id)
                output = Path(task.file_path)
                self.assertTrue(output.exists())
                self.assertTrue(storage.delete_task(task.task_id))
                self.assertFalse(output.exists())


class RouteTests(unittest.TestCase):
    def test_new_endpoints_are_registered(self):
        paths = {route.path for route in app.routes}
        self.assertTrue({"/api/extract/batch", "/api/batch/{batch_id}", "/api/history", "/api/stats", "/api/queue", "/api/cache/stats", "/api/cache", "/api/task/{task_id}/export"}.issubset(paths))

    def test_batch_limit_and_empty_srt_conflict(self):
        from app.config import settings
        with TestClient(app) as client:
            with patch.object(settings, "BATCH_MAX_ITEMS", 1):
                response = client.post("/api/extract/batch", json={"urls": ["https://example.com/a", "https://example.com/b"]})
            self.assertEqual(response.status_code, 422)
            task = TaskResult(task_id="test-no-segments", status=TaskStatus.COMPLETED, text="text")
            storage.save_task(task)
            try:
                response = client.get("/api/task/test-no-segments/export?format=srt")
                self.assertEqual(response.status_code, 409)
            finally:
                storage.delete_task("test-no-segments")


if __name__ == "__main__":
    unittest.main()
