from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import yt_dlp
from yt_dlp.utils import DownloadError

from app.config import settings
from app.services.cookies import cookie_vault, infer_domain

logger = logging.getLogger(__name__)


class _YtDlpCaptureLogger:
    """Capture extractor diagnostics so runtime routing can inspect login walls."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def debug(self, message: str) -> None:
        return None

    def info(self, message: str) -> None:
        return None

    def warning(self, message: str) -> None:
        text = str(message)
        self.warnings.append(text)
        logger.warning("yt-dlp: %s", text)

    def error(self, message: str) -> None:
        text = str(message)
        self.warnings.append(text)
        logger.error("yt-dlp: %s", text)


_executor = ThreadPoolExecutor(max_workers=max(1, settings.YTDLP_MAX_WORKERS))
def _is_browser_cookie_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(token in message for token in (
        "could not copy chrome cookie database",
        "failed to decrypt with dpapi",
        "cannot decrypt v10 cookies",
        "cannot decrypt v11 cookies",
    ))


def _browser_cookie_error(exc: BaseException) -> DownloadError:
    return DownloadError(
        "无法自动读取 Chrome Cookie。请确认 Chrome 已登录目标平台，"
        "关闭所有 Chrome 窗口后重试；程序会自动重新读取，不需要手动复制 Cookie。"
    )


_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _pick_video_entry(info: dict[str, Any]) -> dict[str, Any]:
    entries = info.get("entries")
    if not entries:
        return info

    for entry in entries:
        if entry:
            return entry
    return info


def _normalize_video_info(info: dict[str, Any]) -> dict[str, Any]:
    duration = info.get("duration")
    return {
        "title": info.get("title") or "",
        "duration": float(duration) if duration is not None else None,
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "description": info.get("description"),
    }


def _base_ydl_options(url: str = "") -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": settings.DOWNLOAD_TIMEOUT,
    }

    # yt-dlp's current YouTube extractor requires a JS runtime. Prefer Node
    # because it is already supported by the bundled extractor, then Bun.
    if shutil.which("node"):
        opts["js_runtimes"] = {"node": {}}
    elif shutil.which("bun"):
        opts["js_runtimes"] = {"bun": {}}

    ffmpeg_path = Path(settings.FFMPEG_PATH)
    if ffmpeg_path.exists():
        opts["ffmpeg_location"] = str(ffmpeg_path.parent)

    cookie_opts = cookie_vault.ydl_cookie_opts(url) if url else {}
    try:
        from app.services.platforms import detect
        platform = detect(url)
    except Exception:
        platform = None

    # Browser cookies are the default for login-gated platforms. This keeps
    # fresh session cookies in sync without requiring users to paste headers.
    browser_spec = (settings.YTDLP_COOKIES_FROM_BROWSER or "chrome").strip()
    browser_name, _, profile = browser_spec.partition(":")
    browser_name = browser_name.lower()
    use_browser_cookies = bool(
        browser_name in {"chrome", "edge", "firefox"}
        and platform
        and platform.may_need_cookie
    )
    if use_browser_cookies:
        opts["cookiesfrombrowser"] = (browser_name, profile or None, None, None)
    elif cookie_opts:
        opts.update(cookie_opts)
    elif settings.YTDLP_COOKIE_FILE and url:
        legacy_cookie = Path(settings.YTDLP_COOKIE_FILE).expanduser()
        try:
            legacy_domain = infer_domain(url) == ".douyin.com"
        except ValueError:
            legacy_domain = False
        if legacy_domain and legacy_cookie.is_file():
            opts["cookiefile"] = str(legacy_cookie)

    direct_domains = tuple(
        item.strip().lower().lstrip(".")
        for item in settings.YTDLP_PROXY_DIRECT_DOMAINS.split(",")
        if item.strip()
    )
    host = (urlsplit(url).hostname or "").lower() if url else ""
    direct = any(host == domain or host.endswith("." + domain) for domain in direct_domains)
    if settings.YTDLP_PROXY and not direct:
        proxy = settings.YTDLP_PROXY.strip()
        if not proxy.startswith(("http://", "https://", "socks5://")):
            raise ValueError("YTDLP_PROXY 仅支持 http://、https:// 或 socks5:// 代理")
        opts["proxy"] = proxy
    if settings.YTDLP_RATE_LIMIT > 0:
        opts["ratelimit"] = settings.YTDLP_RATE_LIMIT

    if browser_spec and browser_name not in {"chrome", "edge", "firefox"}:
        logger.warning("Ignoring unsupported YTDLP_COOKIES_FROM_BROWSER=%s", browser_spec)

    headers = {"User-Agent": settings.YTDLP_USER_AGENT or _DEFAULT_USER_AGENT}
    try:
        from app.services.platforms import detect
        platform_key = detect(url).key
    except Exception:
        platform_key = "generic"
    referers = {
        "bilibili": "https://www.bilibili.com/",
        "douyin": "https://www.douyin.com/",
        "xiaohongshu": "https://www.xiaohongshu.com/",
        "youtube": "https://www.youtube.com/",
        "tiktok": "https://www.tiktok.com/",
        "instagram": "https://www.instagram.com/",
    }
    referer = referers.get(platform_key)
    if referer:
        headers["Referer"] = referer
    try:
        from app.services.platforms import detect
        platform = detect(url)
        if platform.may_need_cookie and not cookie_opts and not use_browser_cookies:
            logger.warning("Platform %s may require Cookie; configure it via /api/cookie/config or browser sync", platform.key)
    except Exception:
        pass
    opts["http_headers"] = headers

    return opts


_BILIBILI_BV_PATTERN = re.compile(r"\b(BV[0-9A-Za-z]+)\b", re.IGNORECASE)


def _extract_bilibili_bvid(url: str) -> str | None:
    match = _BILIBILI_BV_PATTERN.search(url)
    return match.group(1) if match else None


def _bilibili_subtitle_probe(
    ydl: yt_dlp.YoutubeDL,
    url: str,
    info: dict[str, Any],
) -> dict[str, Any]:
    """Read Bilibili's subtitle permission bit omitted from normal extractor info."""

    bvid = _extract_bilibili_bvid(url)
    if not bvid:
        return {}
    pages = _bilibili_api_json(ydl, "/x/player/pagelist", {"bvid": bvid})
    page_list = pages if isinstance(pages, list) else (pages.get("pages") or []) if isinstance(pages, dict) else []
    page = page_list[0] if page_list else None
    cid = page.get("cid") if isinstance(page, dict) else None
    if not cid:
        return {}
    data = _bilibili_api_json(ydl, "/x/player/wbi/v2", {"bvid": bvid, "cid": cid})
    subtitle = data.get("subtitle") if isinstance(data, dict) else {}
    return {
        "need_login_subtitle": bool(data.get("need_login_subtitle")) if isinstance(data, dict) else False,
        "subtitle_count": len(subtitle.get("subtitles") or []) if isinstance(subtitle, dict) else 0,
        "cid": cid,
    }


def _enrich_bilibili_subtitle_status(
    ydl: yt_dlp.YoutubeDL,
    url: str,
    info: dict[str, Any],
    capture_logger: _YtDlpCaptureLogger,
) -> dict[str, Any]:
    if not _extract_bilibili_bvid(url):
        return info
    try:
        probe = _bilibili_subtitle_probe(ydl, url, info)
    except Exception as exc:
        capture_logger.warning(f"Bilibili subtitle permission probe failed: {exc}")
        return info
    if probe:
        info["_subtitle_probe"] = probe
        if probe.get("need_login_subtitle"):
            info["need_login_subtitle"] = True
    return info


def _bilibili_api_json(ydl: yt_dlp.YoutubeDL, endpoint: str, params: dict[str, Any]) -> Any:
    query = urlencode({key: value for key, value in params.items() if value is not None})
    response = ydl.urlopen(f"https://api.bilibili.com{endpoint}?{query}")
    payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != 0:
        raise DownloadError(
            f"Bilibili API failed: {payload.get('code')} {payload.get('message', '')}".strip()
        )
    return payload.get("data") or {}


def _bilibili_stream(ydl: yt_dlp.YoutubeDL, url: str) -> tuple[str, dict[str, Any]]:
    bvid = _extract_bilibili_bvid(url)
    if not bvid:
        raise DownloadError("Unable to find Bilibili BV id in URL")

    pages = _bilibili_api_json(ydl, "/x/player/pagelist", {"bvid": bvid})
    if isinstance(pages, list):
        page_list = pages
    elif isinstance(pages, dict):
        page_list = pages.get("data") or pages.get("pages") or []
    else:
        page_list = []
    page = page_list[0] if page_list else None
    if not page or not page.get("cid"):
        raise DownloadError(f"Bilibili returned no playable page for {bvid}")

    cid = page["cid"]
    play_data = _bilibili_api_json(
        ydl,
        "/x/player/playurl",
        {"bvid": bvid, "cid": cid, "fnval": 16, "fourk": 1},
    )
    dash_audio = (play_data.get("dash") or {}).get("audio") or []
    stream_url = ""
    if dash_audio:
        best_audio = max(dash_audio, key=lambda item: item.get("bandwidth") or 0)
        stream_url = best_audio.get("baseUrl") or best_audio.get("base_url") or ""
    if not stream_url:
        durl = play_data.get("durl") or []
        if durl:
            stream_url = durl[0].get("url") or ""
    if not stream_url:
        raise DownloadError(f"Bilibili returned no audio stream for {bvid}")

    duration_ms = play_data.get("timelength")
    duration = (float(duration_ms) / 1000) if duration_ms is not None else page.get("duration")
    return stream_url, {
        "id": bvid,
        "title": page.get("part") or bvid,
        "duration": duration,
        "thumbnail": None,
        "uploader": None,
        "description": None,
    }


def _extract_info_sync(url: str) -> dict[str, Any]:
    opts = _base_ydl_options(url)
    opts["socket_timeout"] = settings.PROBE_TIMEOUT
    capture_logger = _YtDlpCaptureLogger()
    # yt-dlp suppresses report_warning when no_warnings is true. Probes must
    # retain extractor warnings because Bilibili reports login-gated subtitles there.
    opts["no_warnings"] = False
    opts["logger"] = capture_logger
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            info = _pick_video_entry(info)
            info = _enrich_bilibili_subtitle_status(ydl, url, info, capture_logger)
        return {
            **info,
            **_normalize_video_info(info),
            "_runtime_warnings": list(capture_logger.warnings),
        }
    except DownloadError as exc:
        if _is_browser_cookie_error(exc):
            raise _browser_cookie_error(exc) from exc
        if not _extract_bilibili_bvid(url):
            raise
        with yt_dlp.YoutubeDL(opts) as ydl:
            _, info = _bilibili_stream(ydl, url)
        return {
            **info,
            **_normalize_video_info(info),
            "_runtime_warnings": list(capture_logger.warnings),
        }


def _resolve_downloaded_wav(info: dict[str, Any], output_dir: Path, task_id: str) -> Path:
    direct_candidate = output_dir / f"{task_id}.wav"
    if direct_candidate.exists():
        return direct_candidate

    matching = sorted(output_dir.glob(f"{task_id}*.wav"))
    if matching:
        return matching[0]

    requested_downloads = info.get("requested_downloads") or []
    for item in requested_downloads:
        original_path = item.get("filepath")
        if not original_path:
            continue

        original = Path(original_path)
        if original.exists() and original.suffix.lower() == ".wav":
            return original

        converted = original.with_suffix(".wav")
        if converted.exists():
            return converted

    raise FileNotFoundError("Unable to locate downloaded WAV file.")


def _download_audio_sync(
    url: str,
    output_dir: str,
    task_id: str,
    prefetched_info: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    opts = _base_ydl_options(url)
    opts.update(
        {
            "format": "bestaudio/best",
            "outtmpl": str(output_path / f"{task_id}.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "wav",
                    "preferredquality": "0",
                }
            ],
        }
    )

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            if prefetched_info and prefetched_info.get("formats"):
                try:
                    # Probe formats contain signed CDN URLs. Reuse them first,
                    # but refresh from the original URL if a signature expired.
                    info = ydl.process_ie_result(prefetched_info, download=True)
                except DownloadError as exc:
                    if not any(token in str(exc).lower() for token in ("403", "410", "expired")):
                        raise
                    logger.info("Prefetched media URL expired; refreshing formats for %s", url)
                    info = ydl.extract_info(url, download=True)
            else:
                info = ydl.extract_info(url, download=True)
        info = _pick_video_entry(info)
        audio_file = _resolve_downloaded_wav(info, output_path, task_id)
        return str(audio_file.resolve()), _normalize_video_info(info)
    except DownloadError as exc:
        if _is_browser_cookie_error(exc):
            raise _browser_cookie_error(exc) from exc
        if not _extract_bilibili_bvid(url):
            raise

        with yt_dlp.YoutubeDL(opts) as ydl:
            stream_url, info = _bilibili_stream(ydl, url)
            ydl.download([stream_url])
        audio_file = _resolve_downloaded_wav({}, output_path, task_id)
        return str(audio_file.resolve()), _normalize_video_info(info)


async def extract_info(url: str) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _extract_info_sync, url)


async def download_audio(
    url: str,
    output_dir: str,
    task_id: str,
    prefetched_info: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor,
        _download_audio_sync,
        url,
        output_dir,
        task_id,
        prefetched_info,
    )
