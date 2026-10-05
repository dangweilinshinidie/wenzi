from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.services.platforms import ResolvedTier
from app.services.router import classify_error, is_direct_media_url, resolve_video, sanitize_url
from app.services.downloader import _base_ydl_options, _extract_info_sync
from app.services.subtitles import _normalize_time, _parse_srt, _parse_vtt
from app.models import ExtractRequest


class DownloaderProbeTests(unittest.TestCase):
    def test_login_platforms_use_browser_cookies_without_vault_file(self):
        with patch("app.services.downloader.cookie_vault.ydl_cookie_opts", return_value={}), patch(
            "app.services.downloader.settings.YTDLP_COOKIES_FROM_BROWSER", ""
        ), patch("app.services.downloader.settings.YTDLP_COOKIE_FILE", ""):
            opts = _base_ydl_options("https://www.douyin.com/video/123")
        self.assertEqual(opts["cookiesfrombrowser"], ("chrome", None, None, None))
        self.assertNotIn("cookiefile", opts)

    def test_probe_enables_warning_capture_and_returns_warning_metadata(self):
        warning = "Subtitles are only available when logged in. Sign in"

        class FakeYoutubeDL:
            def __init__(self, options):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                self.options["logger"].warning(warning)
                return {"id": "video", "title": "sample", "subtitles": {}}

        with patch("app.services.downloader._base_ydl_options", return_value={}), patch(
            "app.services.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
        ), patch("app.services.downloader._extract_bilibili_bvid", return_value=None):
            info = _extract_info_sync("https://example.com/video")

        self.assertEqual(info["_runtime_warnings"], [warning])
        self.assertEqual(info["subtitles"], {})

    def test_bilibili_permission_probe_extracts_login_flag(self):
        from app.services.downloader import _bilibili_subtitle_probe

        with patch(
            "app.services.downloader._bilibili_api_json",
            side_effect=[[{"cid": 123, "page": 1}], {"need_login_subtitle": True, "subtitle": {"subtitles": []}}],
        ):
            probe = _bilibili_subtitle_probe(object(), "https://www.bilibili.com/video/BV1abc", {})
        self.assertTrue(probe["need_login_subtitle"])
        self.assertEqual(probe["cid"], 123)


class RequestModelTests(unittest.TestCase):
    def test_force_asr_is_explicit(self):
        request = ExtractRequest(url="https://example.com/video", force_asr=True)
        self.assertTrue(request.force_asr)
        self.assertFalse(ExtractRequest(url="https://example.com/video").force_asr)


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

    def test_login_wall_hint_from_extractor_warning(self):
        warning_cases = [
            "Subtitles are only available when logged in. Sign in",
            "字幕仅登录后可用，请配置 Cookie",
        ]
        for warning in warning_cases:
            with self.subTest(warning=warning):
                with patch("app.services.router.extract_info", return_value={"_runtime_warnings": [warning]}):
                    decision = asyncio.run(resolve_video("https://www.bilibili.com/video/BV1xx"))
                self.assertEqual(decision.tier, ResolvedTier.A_LOCKED)
                self.assertIn("Cookie", decision.message)

    def test_bilibili_subtitle_probe_metadata_marks_locked(self):
        info = {
            "subtitles": {},
            "automatic_captions": {},
            "_subtitle_probe": {"need_login_subtitle": True, "cid": 123},
        }
        with patch("app.services.router.extract_info", return_value=info):
            decision = asyncio.run(resolve_video("https://www.bilibili.com/video/BV1xx"))
        self.assertEqual(decision.tier, ResolvedTier.A_LOCKED)

    def test_danmaku_is_not_a_subtitle_track(self):
        with patch("app.services.router.extract_info", return_value={"subtitles": {"danmaku": [{"ext": "xml"}]}}):
            decision = asyncio.run(resolve_video("https://www.bilibili.com/video/BV1xx"))
        self.assertEqual(decision.tier, ResolvedTier.B1)

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
