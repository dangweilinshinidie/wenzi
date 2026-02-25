from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yt_dlp

from app.config import settings

_executor = ThreadPoolExecutor(max_workers=3)


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


def _base_ydl_options() -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": settings.DOWNLOAD_TIMEOUT,
    }

    ffmpeg_path = Path(settings.FFMPEG_PATH)
    if ffmpeg_path.exists():
        opts["ffmpeg_location"] = str(ffmpeg_path.parent)

    return opts


def _extract_info_sync(url: str) -> dict[str, Any]:
    opts = _base_ydl_options()
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    info = _pick_video_entry(info)
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

    opts = _base_ydl_options()
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

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    info = _pick_video_entry(info)
    audio_file = _resolve_downloaded_wav(info, output_path, task_id)
    return str(audio_file.resolve()), _normalize_video_info(info)


async def extract_info(url: str) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _extract_info_sync, url)


async def download_audio(url: str, output_dir: str, task_id: str) -> tuple[str, dict[str, Any]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _download_audio_sync, url, output_dir, task_id)
