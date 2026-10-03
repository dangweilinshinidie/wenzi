from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.services.platforms import ResolvedTier
from app.services.router import classify_error, is_direct_media_url, resolve_video, sanitize_url
from app.services.subtitles import _normalize_time, _parse_srt, _parse_vtt


class RuntimeRouterTests(unittest.TestCase):
    def test_video_level_subtitle_branching_on_same_platform(self):
        async def run(info):
            with patch("app.services.router.extract_info", return_value=info):
                return await resolve_video("https://www.bilibili.com/video/BV1xx")

        with patch("app.services.router._cookie_available", return_value=False):
            subtitle = asyncio.run(run({"title": "captioned", "subtitles": {"zh-CN": [{"ext": "vtt"}]}}))
            no_subtitle = asyncio.run(run({"title": "plain", "subtitles": {}, "automatic_captions": {}}))
        self.assertEqual(subtitle.tier, ResolvedTier.A)
        self.assertEqual(no_subtitle.tier, ResolvedTier.B1)

    def test_cookie_locked_direct_and_probe_error_branches(self):
        with patch("app.services.router.extract_info") as probe:
            direct = asyncio.run(resolve_video("https://cdn.example/video.mp4?sign=x"))
            unsupported = asyncio.run(resolve_video("https://www.kuaishou.com/short-video/123"))
            probe.assert_not_called()
        self.assertEqual(direct.tier, ResolvedTier.C)
        self.assertEqual(unsupported.tier, ResolvedTier.C)

        with patch("app.services.router.extract_info", side_effect=RuntimeError("HTTP Error 403: login required")):
            locked = asyncio.run(resolve_video("https://www.douyin.com/video/1"))
        self.assertEqual(locked.tier, ResolvedTier.B2)
        self.assertEqual(locked.error_type, "cookie_invalid")

    def test_login_wall_hint(self):
        with patch("app.services.router.extract_info", return_value={"need_login_subtitle": True}):
            decision = asyncio.run(resolve_video("https://www.bilibili.com/video/BV1xx"))
        self.assertEqual(decision.tier, ResolvedTier.A_LOCKED)
        self.assertIn("Cookie", decision.message)

    def test_error_classification_direct_url_and_redaction(self):
        self.assertEqual(classify_error(RuntimeError("429 Too Many Requests")), "rate_limited")
        self.assertEqual(classify_error(RuntimeError("connection timed out")), "network_error")
        self.assertTrue(is_direct_media_url("https://cdn.example/file.m3u8?token=x"))
        self.assertIn("[redacted]", sanitize_url("https://cdn.example/file?sign=secret"))
        self.assertNotIn("secret", sanitize_url("https://cdn.example/file?sign=secret"))


class SubtitleParsingTests(unittest.TestCase):
    def test_vtt_html_entities_and_rolling_prefix_dedup(self):
        content = """WEBVTT

00:00:01.000 --> 00:00:02.000
<b>你好</b>

00:00:02.000 --> 00:00:03.000
你好世界 &amp; 再见
"""
        entries = _parse_vtt(content)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["text"], "你好世界 & 再见")
        self.assertEqual(entries[0]["start"], 2.0)

    def test_srt_fractional_timestamps_and_normalize(self):
        entries = _parse_srt("""1
00:01:02,500 --> 00:01:03,750
<strong>测试字幕</strong>
""")
        self.assertEqual(entries[0]["start"], 62.5)
        self.assertEqual(entries[0]["end"], 63.75)
        self.assertEqual(entries[0]["text"], "测试字幕")
        self.assertEqual(_normalize_time(3661.2), "61:01")


if __name__ == "__main__":
    unittest.main()
