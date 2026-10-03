from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class RouteContractTests(unittest.TestCase):
    def test_platforms_endpoint_exposes_hints_only(self):
        with TestClient(app) as client:
            response = client.get("/api/platforms")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload), 20)
        self.assertTrue(all("resolved_tier" not in item for item in payload))
        subtitle_items = [item["key"] for item in payload if item["may_have_subtitle"]]
        self.assertEqual(set(subtitle_items), {"youtube", "bilibili"})

    def test_detect_endpoint_does_not_return_resolved_tier(self):
        with patch("app.routes.resolve_short_link", return_value="https://www.xiaohongshu.com/explore/1"):
            with TestClient(app) as client:
                response = client.post(
                    "/api/detect",
                    json={"url": "分享 https://xhslink.com/abc?utm_source=share&xsec_token=keep"},
                )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["platform"], "xiaohongshu")
        self.assertEqual(payload["normalized_url"], "https://www.xiaohongshu.com/explore/1")
        self.assertNotIn("resolved_tier", payload)
        self.assertTrue(payload["may_need_cookie"])
        self.assertIn("可能需要 Cookie", payload["hint"])

    def test_detect_preserves_original_when_short_link_resolution_fails(self):
        with patch("app.routes.resolve_short_link", side_effect=RuntimeError("network down")):
            with TestClient(app) as client:
                response = client.post(
                    "/api/detect",
                    json={"url": "https://b23.tv/abc?utm_source=share"},
                )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["normalized_url"], "https://b23.tv/abc")
        self.assertEqual(payload["platform"], "generic")


if __name__ == "__main__":
    unittest.main()
