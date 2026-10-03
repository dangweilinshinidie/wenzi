from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.services import urlnorm
from app.services.platforms import (
    ResolvedTier,
    all_platforms,
    cookie_names_for,
    detect,
    has_extractor,
    may_have_subtitle,
    unsupported_hint,
)


class PlatformDetectionTests(unittest.TestCase):
    def test_resolved_tier_enum(self):
        self.assertEqual({tier.value for tier in ResolvedTier}, {"A", "A_LOCKED", "B1", "B2", "C"})

    def test_supported_domains_and_boundaries(self):
        cases = {
            "https://www.youtube.com/watch?v=abc": "youtube",
            "https://youtu.be/abc": "youtube",
            "https://www.bilibili.com/video/BV1": "bilibili",
            "https://b23.tv/abc": "bilibili",
            "https://www.ixigua.com/abc": "ixigua",
            "https://v.qq.com/x/cover/abc": "tencent",
            "https://www.youku.com/v_show/id_abc": "youku",
            "https://www.iqiyi.com/v_abc.html": "iqiyi",
            "https://weibo.com/123": "weibo",
            "https://www.facebook.com/watch/abc": "facebook",
            "https://podcasts.apple.com/us/podcast/abc": "apple_podcasts",
            "https://soundcloud.com/artist/track": "soundcloud",
            "https://www.ximalaya.com/album/1": "ximalaya",
            "https://music.163.com/#/program?id=1": "netease_podcast",
            "https://www.douyin.com/video/1": "douyin",
            "https://v.douyin.com/abc": "douyin",
            "https://www.xiaohongshu.com/explore/abc": "xiaohongshu",
            "https://xhslink.com/abc": "xiaohongshu",
            "https://www.instagram.com/reel/abc": "instagram",
            "https://x.com/user/status/1": "x",
            "https://www.twitter.com/user/status/1": "x",
            "https://www.tiktok.com/@user/video/1": "tiktok",
            "https://vm.tiktok.com/abc": "tiktok",
            "https://v.kuaishou.com/abc": "kuaishou",
            "https://channels.weixin.qq.com/platform/post/abc": "wechat_channels",
            "https://www.xiaoyuzhoufm.com/episode/abc": "xiaoyuzhou",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(detect(url).key, expected)
        self.assertEqual(detect("https://notyoutube.com/video").key, "generic")

    def test_hints_and_cookie_names(self):
        subtitle_keys = {item.key for item in all_platforms() if item.may_have_subtitle}
        self.assertEqual(subtitle_keys, {"youtube", "bilibili"})
        self.assertTrue(has_extractor(detect("https://www.douyin.com/video/1")))
        self.assertFalse(has_extractor(detect("https://www.kuaishou.com/short-video/1")))
        self.assertIn("SESSDATA", cookie_names_for("bilibili"))
        self.assertIn("可能需要 Cookie", unsupported_hint("douyin"))
        self.assertIn("直链", unsupported_hint("kuaishou"))


class UrlNormalizationTests(unittest.TestCase):
    def test_clean_share_text_handles_chinese_punctuation_and_emoji(self):
        self.assertEqual(
            urlnorm.clean_share_text("复制这条消息🎉 https://v.douyin.com/AbCd/🎉）打开看看"),
            "https://v.douyin.com/AbCd/",
        )

    def test_strip_tracking_preserves_xsec_token(self):
        value = urlnorm.strip_tracking(
            "https://www.xiaohongshu.com/explore/1?utm_source=share&share_token=gone&xsec_token=keep&timestamp=1&foo=bar"
        )
        self.assertEqual(value, "https://www.xiaohongshu.com/explore/1?xsec_token=keep&foo=bar")

    def test_short_link_detection_does_not_match_long_platform_urls(self):
        self.assertTrue(urlnorm.is_short_link("https://v.douyin.com/abc"))
        self.assertFalse(urlnorm.is_short_link("https://www.douyin.com/video/1"))

    def test_short_link_resolves_with_bounded_redirects_and_cache(self):
        urlnorm._cache.clear()
        hops = []

        def fake_location(url, method, timeout):
            hops.append((url, method))
            if method == "HEAD" and url == "https://v.douyin.com/abc":
                return "/step"
            if method == "HEAD" and url == "https://v.douyin.com/step":
                return "https://www.douyin.com/video/123"
            return None

        async def run():
            with patch.object(urlnorm, "_location_response", side_effect=fake_location):
                first = await urlnorm.resolve_short_link("https://v.douyin.com/abc")
                second = await urlnorm.resolve_short_link("https://v.douyin.com/abc")
            return first, second

        first, second = asyncio.run(run())
        self.assertEqual(first, "https://www.douyin.com/video/123")
        self.assertEqual(second, first)
        self.assertEqual(len(hops), 2)

    def test_short_link_loop_falls_back_to_original(self):
        original = "https://v.douyin.com/loop"
        with patch.object(urlnorm, "_location_response", return_value="/loop"):
            self.assertEqual(urlnorm._resolve_short_link_sync(original), original)


if __name__ == "__main__":
    unittest.main()
