from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit


class ResolvedTier(str, Enum):
    """Runtime result tiers; the platform table never chooses one."""

    A = "A"
    A_LOCKED = "A_LOCKED"
    B1 = "B1"
    B2 = "B2"
    C = "C"


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    domains: tuple[str, ...]
    short_link_domains: tuple[str, ...] = ()
    has_extractor: bool = True
    may_have_subtitle: bool = False
    may_need_cookie: bool = False
    cookie_names: tuple[str, ...] = ()


# may_have_subtitle means that a video on the platform may expose subtitles;
# it does not mean that every video on the platform has subtitles.
_PLATFORMS: tuple[Platform, ...] = (
    Platform(
        "youtube", "YouTube", ("youtube.com",), ("youtu.be",), True, True, True,
        ("LOGIN_INFO", "SAPISID", "SSID"),
    ),
    Platform(
        "bilibili", "Bilibili", ("bilibili.com",), ("b23.tv",), True, True, True,
        ("SESSDATA", "bili_jct", "DedeUserID"),
    ),
    Platform("ixigua", "西瓜视频", ("ixigua.com",), has_extractor=True),
    Platform("tencent", "腾讯视频", ("v.qq.com",), has_extractor=True),
    Platform("youku", "优酷", ("youku.com",), has_extractor=True),
    Platform("iqiyi", "爱奇艺", ("iqiyi.com", "iq.com"), has_extractor=True),
    Platform("weibo", "微博", ("weibo.com", "weibo.cn"), has_extractor=True),
    Platform("facebook", "Facebook", ("facebook.com",), ("fb.watch",), True),
    Platform("apple_podcasts", "Apple Podcasts", ("podcasts.apple.com",), has_extractor=True),
    Platform("soundcloud", "SoundCloud", ("soundcloud.com",), has_extractor=True),
    Platform("ximalaya", "喜马拉雅", ("ximalaya.com",), has_extractor=True),
    Platform("netease_podcast", "网易云音乐播客", ("music.163.com",), has_extractor=True),
    Platform(
        "douyin", "抖音", ("douyin.com", "iesdouyin.com"), ("v.douyin.com",), True, False, True,
        ("s_v_web_id", "ttwid"),
    ),
    Platform(
        "xiaohongshu", "小红书", ("xiaohongshu.com",), ("xhslink.com",), True, False, True,
        ("web_session", "a1"),
    ),
    Platform(
        "instagram", "Instagram", ("instagram.com",), has_extractor=True, may_need_cookie=True,
        cookie_names=("sessionid",),
    ),
    Platform(
        "x", "X / Twitter", ("x.com", "twitter.com"), ("t.co",), True, False, True,
        ("auth_token", "ct0"),
    ),
    Platform(
        "tiktok", "TikTok", ("tiktok.com",), ("vm.tiktok.com",), True, False, True,
        ("sessionid", "sid_tt", "ttwid"),
    ),
    Platform("kuaishou", "快手", ("kuaishou.com", "kwaishop.com"), ("v.kuaishou.com",), False),
    Platform("wechat_channels", "微信视频号", ("channels.weixin.qq.com",), has_extractor=False),
    Platform("xiaoyuzhou", "小宇宙", ("xiaoyuzhoufm.com",), has_extractor=False),
    Platform("generic", "其它网站", (), has_extractor=False),
)

_PLATFORM_BY_KEY = {platform.key: platform for platform in _PLATFORMS}
_DOMAIN_MATCHES = sorted(
    (
        (domain.lower().lstrip("."), platform)
        for platform in _PLATFORMS
        for domain in (*platform.domains, *platform.short_link_domains)
    ),
    key=lambda item: len(item[0]),
    reverse=True,
)


def all_platforms() -> tuple[Platform, ...]:
    """Return the immutable platform hints in display order, excluding generic."""

    return tuple(platform for platform in _PLATFORMS if platform.key != "generic")


def _as_platform(value: Platform | str | None) -> Platform:
    if isinstance(value, Platform):
        return value
    if value and value in _PLATFORM_BY_KEY:
        return _PLATFORM_BY_KEY[value]
    return _PLATFORM_BY_KEY["generic"]


def detect(url: str) -> Platform:
    """Identify a platform by hostname, with longer domains matched first."""

    candidate = (url or "").strip()
    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return _PLATFORM_BY_KEY["generic"]

    for domain, platform in _DOMAIN_MATCHES:
        if host == domain or host.endswith(f".{domain}"):
            return platform
    return _PLATFORM_BY_KEY["generic"]


def has_extractor(platform: Platform | str) -> bool:
    return _as_platform(platform).has_extractor


def may_have_subtitle(platform: Platform | str) -> bool:
    return _as_platform(platform).may_have_subtitle


def cookie_names_for(platform: Platform | str) -> tuple[str, ...]:
    return _as_platform(platform).cookie_names


def unsupported_hint(platform: Platform | str) -> str:
    item = _as_platform(platform)
    if item.has_extractor:
        if item.may_need_cookie:
            return f"{item.name}可能需要 Cookie，实际是否需要要以当前视频探测结果为准。"
        if item.may_have_subtitle:
            return f"{item.name}可能有字幕，实际档位要以当前视频探测结果为准。"
        return f"{item.name}支持尝试解析，实际能力要以当前视频探测结果为准。"
    return f"{item.name}暂无原生解析器，请提供可访问的媒体直链。"


__all__ = [
    "Platform",
    "ResolvedTier",
    "all_platforms",
    "cookie_names_for",
    "detect",
    "has_extractor",
    "may_have_subtitle",
    "unsupported_hint",
]
