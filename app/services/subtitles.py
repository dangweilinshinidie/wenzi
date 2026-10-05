"""Subtitle parsing adapted from AI-Video-Transcriber (Apache-2.0).
Source: https://github.com/wendy7756/AI-Video-Transcriber
Wenzi modifications: preserve fractional seconds, return Segment-compatible entries,
share Wenzi yt-dlp options, and make acquisition failures fall back to ASR.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yt_dlp

from app.services.downloader import _base_ydl_options

logger = logging.getLogger(__name__)
_TIME = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{1,3})")
_TAG = re.compile(r"<[^>]+>")
_LANGUAGE_PRIORITY = ("en", "en-orig", "zh-Hans", "zh-Hant", "zh", "ja", "ko", "fr", "de", "es")


def _seconds(value: str) -> float:
    match = _TIME.search(value)
    if not match:
        return 0.0
    hours, minutes, seconds, millis = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, "0")) / 1000


def _normalize_time(value: str | float) -> str:
    seconds = _seconds(value) if isinstance(value, str) else float(value)
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def _clean_text(value: str) -> str:
    value = _TAG.sub("", value)
    value = html.unescape(value).replace("\u200b", "")
    return re.sub(r"\s+", " ", value).strip()


def _parse_vtt(content: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    lines = content.replace("\r", "").split("\n")
    index = 0
    while index < len(lines):
        match = _TIME.search(lines[index])
        if not match:
            index += 1
            continue
        times = lines[index].split("-->", 1)
        if len(times) != 2:
            index += 1
            continue
        start, end = _seconds(times[0]), _seconds(times[1])
        index += 1
        text_lines = []
        while index < len(lines) and lines[index].strip():
            if not _TIME.search(lines[index]):
                text_lines.append(lines[index])
            index += 1
        text = _clean_text(" ".join(text_lines))
        if len(text) >= 2 and (not entries or entries[-1]["text"] != text):
            entries.append({"start": start, "end": end, "text": text})
        index += 1

    # YouTube automatic captions may emit rolling prefixes before the final cue.
    filtered = []
    for idx, entry in enumerate(entries):
        rolling = any(
            later["text"].startswith(entry["text"]) and len(later["text"]) > len(entry["text"])
            for later in entries[idx + 1:idx + 4]
        )
        if not rolling:
            filtered.append(entry)
    return filtered


def _parse_srt(content: str) -> list[dict[str, Any]]:
    entries = []
    for block in re.split(r"\n\s*\n", content.replace("\r", "").strip()):
        lines = block.splitlines()
        time_line = next((line for line in lines if "-->" in line and _TIME.search(line)), None)
        if not time_line:
            continue
        left, right = time_line.split("-->", 1)
        text = _clean_text(" ".join(line for line in lines[lines.index(time_line) + 1:] if not line.strip().isdigit()))
        if len(text) >= 2 and (not entries or entries[-1]["text"] != text):
            entries.append({"start": _seconds(left), "end": _seconds(right), "text": text})
    return entries


def _select_track(info: dict[str, Any]) -> tuple[str, list[dict[str, Any]]] | None:
    for field in ("subtitles", "automatic_captions"):
        tracks = info.get(field) or {}
        if not isinstance(tracks, dict):
            continue
        languages = [lang for lang, items in tracks.items() if lang.lower() not in {"live_chat", "danmaku"} and items]
        if not languages:
            continue
        language = next((lang for preferred in _LANGUAGE_PRIORITY for lang in languages if lang.lower() == preferred.lower()), languages[0])
        return language, tracks[language]
    return None


def _download_subtitle_sync(url: str, info: dict[str, Any], output_dir: str) -> tuple[str, Path] | None:
    selected = _select_track(info)
    if not selected:
        return None
    language, tracks = selected
    # Bilibili exposes subtitle JSON through its player API rather than a
    # downloadable VTT/SRT file. Convert that JSON to SRT locally.
    bilibili_track = next((item for item in tracks if item.get("_bilibili_json")), None)
    if bilibili_track:
        options = _base_ydl_options(url)
        headers = options.get("http_headers") or {}
        with yt_dlp.YoutubeDL(options) as ydl:
            response = ydl.urlopen(bilibili_track["url"])
            payload = json.loads(response.read().decode("utf-8"))
        body = payload.get("body") if isinstance(payload, dict) else None
        if not isinstance(body, list):
            return None
        path = Path(output_dir) / "subtitle.srt"
        lines = []
        for index, item in enumerate(body, 1):
            if not isinstance(item, dict):
                continue
            start = float(item.get("from") or 0)
            end = float(item.get("to") or start)
            def stamp(value: float) -> str:
                ms = round(value * 1000)
                hour, rem = divmod(ms, 3600000)
                minute, rem = divmod(rem, 60000)
                second, millis = divmod(rem, 1000)
                return f"{hour:02d}:{minute:02d}:{second:02d},{millis:03d}"
            lines.extend([str(index), f"{stamp(start)} --> {stamp(end)}", str(item.get("content") or ""), ""])
        path.write_text("\n".join(lines), encoding="utf-8")
        return language, path

    options = _base_ydl_options(url)
    options.update({
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [language],
        "subtitlesformat": "vtt/srt/best",
        "outtmpl": str(Path(output_dir) / "subtitle.%(ext)s"),
    })
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.process_ie_result(info, download=True)
    candidates = sorted(Path(output_dir).glob("*.vtt")) + sorted(Path(output_dir).glob("*.srt"))
    if not candidates:
        return None
    return language, candidates[0]


async def fetch_subtitles(url: str, info: dict[str, Any]) -> tuple[list[dict[str, Any]], str] | None:
    """Download one preferred track using already-probed metadata; failures are non-fatal."""
    if not _select_track(info):
        return None
    temp_dir = Path(tempfile.mkdtemp(prefix="wenzi-subtitle-"))
    try:
        downloaded = await asyncio.to_thread(_download_subtitle_sync, url, info, str(temp_dir))
        if not downloaded:
            return None
        language, path = downloaded
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        entries = _parse_vtt(content) if path.suffix.lower() == ".vtt" else _parse_srt(content)
        return (entries, language) if entries else None
    except Exception:
        logger.warning("Subtitle fetch/parse failed; falling back to ASR", exc_info=True)
        return None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


__all__ = ["_normalize_time", "_parse_srt", "_parse_vtt", "fetch_subtitles"]
