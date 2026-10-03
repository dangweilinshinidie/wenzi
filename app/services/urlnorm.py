from __future__ import annotations

import asyncio
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.services.platforms import detect

URL_PATTERN = re.compile(
    r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+",
    re.IGNORECASE,
)
TRACKING_KEYS = {"timestamp", "share_token"}
_SHORT_LINK_DOMAINS = {
    domain
    for platform in (detect("https://v.douyin.com/"), detect("https://v.kuaishou.com/"),
                     detect("https://xhslink.com/"), detect("https://b23.tv/"),
                     detect("https://vm.tiktok.com/"))
    for domain in platform.short_link_domains
}
_CACHE_TTL_SECONDS = 24 * 60 * 60
_CACHE_MAX_ENTRIES = 1024
_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
_cache_lock = threading.Lock()

_MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)


def clean_share_text(raw: str) -> str:
    """Extract the first URL from pasted share text and trim surrounding punctuation."""

    text = (raw or "").strip()
    match = URL_PATTERN.search(text)
    if not match:
        return text
    value = match.group(0).rstrip("，。！？；：、,.!?;:）)]}>】」』”’\"'")
    while value and unicodedata.category(value[-1]) in {"So", "Sk", "Mn"}:
        value = value[:-1]
    return value


def strip_tracking(url: str) -> str:
    """Remove sharing/tracking parameters while preserving xsec_token."""

    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return url
    kept = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered.startswith("share_") or lowered in TRACKING_KEYS:
            continue
        kept.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept, doseq=True), parts.fragment))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def is_short_link(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in _SHORT_LINK_DOMAINS)


def _location_response(url: str, method: str, timeout: float) -> str | None:
    opener = build_opener(_NoRedirect)
    request = Request(
        url,
        method=method,
        headers={"User-Agent": _MOBILE_UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
    )
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as exc:
        response = exc
    except (URLError, TimeoutError, OSError):
        raise
    try:
        return response.headers.get("Location")
    finally:
        response.close()


def _resolve_short_link_sync(url: str, timeout: float = 8.0) -> str:
    original = url
    current = url
    visited = {current}
    for _ in range(5):
        try:
            location = _location_response(current, "HEAD", timeout)
        except (URLError, TimeoutError, OSError):
            location = None
        if not location:
            try:
                location = _location_response(current, "GET", timeout)
            except (URLError, TimeoutError, OSError):
                location = None
        if not location:
            return original
        target = urljoin(current, location)
        if target in visited:
            return original
        if (urlsplit(target).scheme or "").lower() not in {"http", "https"}:
            return original
        visited.add(target)
        current = target
        if not is_short_link(current):
            return current
    return original


async def resolve_short_link(url: str) -> str:
    """Resolve known share links with bounded redirects and a 24-hour cache."""

    if not is_short_link(url):
        return url
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(url)
        if cached and cached[0] > now:
            _cache.move_to_end(url)
            return cached[1]
        if cached:
            _cache.pop(url, None)

    resolved = await asyncio.to_thread(_resolve_short_link_sync, url)
    with _cache_lock:
        _cache[url] = (time.monotonic() + _CACHE_TTL_SECONDS, resolved)
        _cache.move_to_end(url)
        while len(_cache) > _CACHE_MAX_ENTRIES:
            _cache.popitem(last=False)
    return resolved


async def normalize_video_url(raw: str, *, logger=None) -> tuple[str, str]:
    """Run share-text extraction, short-link resolution, tracking cleanup and detection."""

    cleaned = clean_share_text(raw)
    current = cleaned
    try:
        current = await resolve_short_link(current)
    except Exception as exc:
        if logger:
            logger.warning("Short-link resolution failed; retaining original URL: %s", exc)
        current = cleaned
    try:
        normalized = strip_tracking(current)
        platform = detect(normalized).key
        return normalized, platform
    except Exception as exc:
        if logger:
            logger.warning("URL normalization failed; retaining generic URL: %s", exc)
        return cleaned, "generic"
