from __future__ import annotations

import asyncio
import json
import logging
import re
from urllib.parse import urlencode, urlsplit
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError

from app.config import settings
from app.services.cookies import cookie_vault, infer_domain

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=3)
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

    ffmpeg_path = Path(settings.FFMPEG_PATH)
    if ffmpeg_path.exists():
        opts["ffmpeg_location"] = str(ffmpeg_path.parent)

    cookie_opts = cookie_vault.ydl_cookie_opts(url) if url else {}
    if cookie_opts:
        opts.update(cookie_opts)
    elif settings.YTDLP_COOKIE_FILE and url:
        legacy_cookie = Path(settings.YTDLP_COOKIE_FILE).expanduser()
        try:
            legacy_domain = infer_domain(url) == ".douyin.com"
        except ValueError:
            legacy_domain = False
        if legacy_domain and legacy_cookie.is_file():
            opts["cookiefile"] = str(legacy_cookie)

    if settings.YTDLP_PROXY:
        opts["proxy"] = settings.YTDLP_PROXY

    browser_spec = (settings.YTDLP_COOKIES_FROM_BROWSER or "").strip()
    if browser_spec:
        browser_name, _, profile = browser_spec.partition(":")
        browser_name = browser_name.lower()
        if browser_name in {"chrome", "edge", "firefox"}:
            opts["cookiesfrombrowser"] = (browser_name, profile or None, None, None)
        else:
            logger.warning("Ignoring unsupported YTDLP_COOKIES_FROM_BROWSER=%s", browser_spec)

    headers = {"User-Agent": settings.YTDLP_USER_AGENT or _DEFAULT_USER_AGENT}
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        host = ""
    if host.endswith(("bilibili.com", "b23.tv")):
        headers["Referer"] = "https://www.bilibili.com/"
    opts["http_headers"] = headers

    return opts


_BILIBILI_BV_PATTERN = re.compile(r"\b(BV[0-9A-Za-z]+)\b", re.IGNORECASE)


def _extract_bilibili_bvid(url: str) -> str | None:
    match = _BILIBILI_BV_PATTERN.search(url)
    return match.group(1) if match else None


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
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        info = _pick_video_entry(info)
        return _normalize_video_info(info)
    except DownloadError:
        if not _extract_bilibili_bvid(url):
            raise
        with yt_dlp.YoutubeDL(opts) as ydl:
            _, info = _bilibili_stream(ydl, url)
        return _normalize_video_info(info)


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


def _download_audio_sync(url: str, output_dir: str, task_id: str) -> tuple[str, dict[str, Any]]:
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
            info = ydl.extract_info(url, download=True)
        info = _pick_video_entry(info)
        audio_file = _resolve_downloaded_wav(info, output_path, task_id)
        return str(audio_file.resolve()), _normalize_video_info(info)
    except DownloadError:
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


async def download_audio(url: str, output_dir: str, task_id: str) -> tuple[str, dict[str, Any]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _download_audio_sync, url, output_dir, task_id)
