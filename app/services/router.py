from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlunsplit
from typing import Any
from urllib.parse import urlsplit

from app.config import settings
from app.services.platforms import Platform, ResolvedTier, detect
from app.services.cookies import cookie_vault, infer_domain
from app.services.downloader import extract_info

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouteDecision:
    tier: ResolvedTier
    platform: Platform
    url: str
    info: dict[str, Any] | None = None
    message: str = ""
    error_type: str | None = None


_DIRECT_MEDIA_SUFFIXES = (".mp4", ".m3u8", ".mp3", ".m4a", ".wav", ".flac", ".webm", ".aac")


def is_direct_media_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith(_DIRECT_MEDIA_SUFFIXES)


def classify_error(exc: BaseException) -> str:
    message = str(exc).lower()
    if any(token in message for token in ("410", "expired", "url has expired")):
        return "link_expired"
    if any(token in message for token in ("429", "too many requests", "rate limit")):
        return "rate_limited"
    if any(token in message for token in ("geo", "region", "country", "not available in your")):
        return "region_blocked"
    if any(token in message for token in ("403", "forbidden", "login required", "sign in", "cookie", "authentication")):
        return "cookie_invalid"
    if any(token in message for token in ("timed out", "timeout", "connection", "network", "temporary")):
        return "network_error"
    if any(token in message for token in ("parse", "unsupported url", "unable to extract", "no video")):
        return "parse_failed"
    return "parse_failed"


def sanitize_url(url: str) -> str:
    """Remove common CDN signature parameters from logs and user-facing errors."""
    try:
        parts = urlsplit(url)
        hidden = {"sign", "a", "bt", "wssecret", "ws_secret", "token", "auth_key"}
        query = [(key, "[redacted]" if key.lower() in hidden else value) for key, value in parse_qsl(parts.query, keep_blank_values=True)]
        sanitized = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        return sanitized.replace("%5Bredacted%5D", "[redacted]")
    except ValueError:
        return "[invalid url]"


def user_error_message(error_type: str, exc: BaseException) -> str:
    messages = {
        "cookie_invalid": "当前视频需要有效 Cookie，请配置或更新 Cookie 后重试。",
        "rate_limited": "平台请求过于频繁，请稍后重试。",
        "region_blocked": "当前内容受地区限制，无法从此网络访问。",
        "link_expired": "直链已过期，请重新抓包。",
        "parse_failed": "无法解析该视频链接，请确认链接有效且内容可访问。",
        "network_error": "网络请求失败，请检查网络或代理后重试。",
    }
    return f"{messages.get(error_type, str(exc))} ({error_type})"


def _has_usable_subtitles(info: dict[str, Any]) -> bool:
    probe = info.get("_subtitle_probe") or {}
    if probe.get("subtitle_count", 0) > 0:
        return True
    for key in ("subtitles", "automatic_captions"):
        tracks = info.get(key) or {}
        if not isinstance(tracks, dict):
            continue
        for language, entries in tracks.items():
            if str(language).lower() in {"live_chat", "danmaku"}:
                continue
            if entries:
                return True
    return False


def _is_locked_subtitle_info(info: dict[str, Any]) -> bool:
    markers = ("need_login_subtitle", "subtitle_login_required", "login_required", "needs_login")
    if any(info.get(marker) for marker in markers):
        return True
    probe = info.get("_subtitle_probe") or {}
    if probe.get("need_login_subtitle"):
        return True
    text = " ".join(str(info.get(key, "")) for key in ("availability", "description", "error"))
    text += " " + " ".join(str(value) for value in info.get("_runtime_warnings", []))
    return bool(
        re.search(
            r"subtitle.{0,120}(login|sign.?in|member|cookie)|"
            r"(login|sign.?in|member|cookie).{0,120}subtitle|"
            r"字幕.{0,40}(登录|登入|會員|会员|cookie)|"
            r"(登录|登入|會員|会员|cookie).{0,40}字幕",
            text,
            re.I,
        )
    )


def _cookie_available(url: str) -> bool:
    try:
        return bool(cookie_vault.ydl_cookie_opts(url))
    except Exception:
        return False


def _needs_cookie(info: dict[str, Any], platform: Platform, url: str) -> bool:
    if any(info.get(key) for key in ("needs_cookie", "cookie_required", "login_required")):
        return True
    if platform.key in {"youtube", "bilibili"}:
        return False
    return platform.may_need_cookie and not _cookie_available(url)


async def resolve_video(url: str) -> RouteDecision:
    platform = detect(url)
    if is_direct_media_url(url):
        return RouteDecision(ResolvedTier.C, platform, url, message="直链将直接下载并转写。")
    if not platform.has_extractor:
        return RouteDecision(
            ResolvedTier.C, platform, url,
            message=f"{platform.name}暂无原生解析器，请提供可访问的媒体直链。",
        )

    try:
        for attempt in range(3):
            try:
                info = await asyncio.wait_for(extract_info(url), timeout=settings.PROBE_TIMEOUT)
                break
            except Exception as exc:
                error_type = classify_error(exc)
                if error_type not in {"network_error", "rate_limited"} or attempt == 2:
                    raise
                await asyncio.sleep(2 ** (attempt + 1))
    except Exception as exc:
        error_type = classify_error(exc)
        if error_type == "cookie_invalid":
            return RouteDecision(
                ResolvedTier.B2, platform, url,
                message=user_error_message(error_type, exc), error_type=error_type,
            )
        return RouteDecision(
            ResolvedTier.B1, platform, url,
            message=user_error_message(error_type, exc), error_type=error_type,
        )

    if _is_locked_subtitle_info(info):
        return RouteDecision(
            ResolvedTier.A_LOCKED, platform, url, info,
            message="检测到字幕轨道，但配置 Cookie 后即可秒出字幕；当前不会静默降级。",
        )
    if _has_usable_subtitles(info):
        return RouteDecision(ResolvedTier.A, platform, url, info, "检测到可用字幕，将优先获取字幕。")
    tier = ResolvedTier.B2 if _needs_cookie(info, platform, url) else ResolvedTier.B1
    return RouteDecision(tier, platform, url, info, "未检测到可用字幕，将使用音频识别。")


__all__ = [
    "RouteDecision", "classify_error", "is_direct_media_url", "resolve_video", "user_error_message",
]
