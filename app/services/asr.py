import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import List, Optional, Tuple

from funasr import AutoModel

from app.config import settings
from app.models import Segment

_executor = ThreadPoolExecutor(max_workers=2)
_model_lock = threading.Lock()
_model: Optional[AutoModel] = None


def load_model() -> AutoModel:
    """
    Lazily load and cache the FunASR AutoModel instance.
    """
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = AutoModel(
                    model=settings.ASR_MODEL,
                    vad_model=settings.ASR_VAD_MODEL,
                    punc_model=settings.ASR_PUNC_MODEL,
                    trust_remote_code=True,
                )
    return _model


def _extract_segments(raw: List[dict]) -> List[Segment]:
    segments: List[Segment] = []
    for item in raw:
        start = item.get("start", item.get("start_time", 0.0))
        end = item.get("end", item.get("end_time", 0.0))
        text = item.get("text") or item.get("sentence") or ""
        try:
            start_f = float(start)
        except (TypeError, ValueError):
            start_f = 0.0
        try:
            end_f = float(end)
        except (TypeError, ValueError):
            end_f = start_f
        segments.append(Segment(start=start_f, end=end_f, text=text))
    return segments


def _recognize_sync(
    audio_path: str,
    enable_timestamp: bool = False,
) -> Tuple[str, Optional[List[Segment]]]:
    """
    Synchronous recognition wrapper around FunASR AutoModel.generate.
    """
    model = load_model()

    results = model.generate(
        input=audio_path,
        batch_size_s=settings.ASR_BATCH_SIZE_S,
        device=settings.ASR_DEVICE,
        sentence_timestamp=enable_timestamp,
    )

    if not results:
        return "", None

    first = results[0] if isinstance(results, (list, tuple)) else results
    text = first.get("text") or first.get("raw_text") or ""

    segments: Optional[List[Segment]] = None
    if enable_timestamp:
        raw_segments = (
            first.get("segments")
            or first.get("sentence_info")
            or first.get("sentences")
            or []
        )
        if isinstance(raw_segments, list):
            segments = _extract_segments(raw_segments)

    return text, segments


async def recognize(
    audio_path: str,
    enable_timestamp: bool = False,
) -> Tuple[str, Optional[List[Segment]]]:
    """
    Asynchronous API for speech recognition, wrapped with ThreadPoolExecutor.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor,
        partial(_recognize_sync, audio_path, enable_timestamp),
    )

