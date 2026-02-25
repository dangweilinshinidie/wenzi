from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.models import (
    ExtractRequest,
    ExtractResponse,
    TaskResult,
    TaskStatus,
    VideoInfoResponse,
)
from app.services.asr import recognize
from app.services.audio import convert_to_16k_wav
from app.services.downloader import download_audio, extract_info
from app.task_manager import task_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.post("/extract", response_model=ExtractResponse)
async def create_extract_task(request: ExtractRequest) -> ExtractResponse:
    task_id = await task_manager.create_task()
    asyncio.create_task(
        _process_task(task_id, request.url, request.enable_timestamp),
        name=f"extract-{task_id}",
    )
    return ExtractResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="Task created.",
    )


@router.get("/task/{task_id}", response_model=TaskResult)
async def get_task_result(task_id: str) -> TaskResult:
    task = await task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/info", response_model=VideoInfoResponse)
async def get_video_info(
    url: str = Query(..., min_length=1, description="视频 URL"),
) -> VideoInfoResponse:
    try:
        info = await extract_info(url)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to extract video info: {exc}",
        ) from exc

    return VideoInfoResponse(
        title=info.get("title") or "",
        duration=float(info.get("duration") or 0.0),
        thumbnail=info.get("thumbnail"),
        uploader=info.get("uploader"),
        description=info.get("description"),
    )


async def _process_task(task_id: str, url: str, enable_timestamp: bool) -> None:
    task_tmp_dir = Path(settings.TEMP_DIR) / task_id
    task_tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        await task_manager.update_task(
            task_id,
            status=TaskStatus.DOWNLOADING,
            progress="Downloading audio.",
        )
        audio_path, video_info = await download_audio(url, str(task_tmp_dir), task_id)
        await task_manager.update_task(
            task_id,
            video_title=video_info.get("title"),
            video_duration=video_info.get("duration"),
        )

        converted_audio_path = task_tmp_dir / f"{task_id}_16k.wav"
        await task_manager.update_task(
            task_id,
            status=TaskStatus.CONVERTING,
            progress="Converting audio.",
        )
        wav_path = await convert_to_16k_wav(audio_path, str(converted_audio_path))

        await task_manager.update_task(
            task_id,
            status=TaskStatus.RECOGNIZING,
            progress="Recognizing speech.",
        )
        text, segments = await recognize(wav_path, enable_timestamp=enable_timestamp)

        await task_manager.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress="Completed.",
            text=text,
            segments=segments if enable_timestamp else None,
            error=None,
        )
    except Exception as exc:
        logger.exception("Task %s failed", task_id)
        await task_manager.update_task(
            task_id,
            status=TaskStatus.FAILED,
            progress="Failed.",
            error=str(exc),
        )
    finally:
        shutil.rmtree(task_tmp_dir, ignore_errors=True)
