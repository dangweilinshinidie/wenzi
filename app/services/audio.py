from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import settings


def _resolve_ffmpeg_executable() -> str:
    configured_path = Path(settings.FFMPEG_PATH)
    if configured_path.exists():
        return str(configured_path)
    return "ffmpeg"


async def convert_to_16k_wav(input_path: str, output_path: str) -> str:
    source = Path(input_path)
    target = Path(output_path)

    if not source.exists():
        raise FileNotFoundError(f"Input audio not found: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)

    process = await asyncio.create_subprocess_exec(
        _resolve_ffmpeg_executable(),
        "-y",
        "-i",
        str(source),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-sample_fmt",
        "s16",
        str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        error_text = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg conversion failed: {error_text}")

    return str(target.resolve())
