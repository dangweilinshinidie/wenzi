from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.models import (
    CookieCheckRequest,
    CookieCheckResponse,
    CookieConfigRequest,
    CookieConfigResponse,
    CookieDomainResponse,
    CookieStatusResponse,
    CookieSyncRequest,
    CookieSyncResponse,
    ExtractRequest,
    ExtractResponse,
    TaskResult,
    TaskStatus,
    VideoInfoResponse,
)
from app.services.asr import recognize
from app.services.audio import convert_to_16k_wav
from app.services.cookies import browser_cookies, cookie_vault, infer_domain, normalize_domain
from app.services.downloader import download_audio, extract_info
from app.task_manager import task_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")
URL_PATTERN = re.compile(r"https?://[^\s<>'\"\u3000]+", re.IGNORECASE)


def _normalize_input_url(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""

    match = URL_PATTERN.search(text)
    if not match:
        return text

    # Strip common trailing punctuation from pasted share text.
    return match.group(0).rstrip("，。！？；：,.!?;:）)]}\"'")


def _resolve_cookie_file_path() -> Path:
    legacy = (settings.YTDLP_COOKIE_FILE or "").strip()
    if legacy:
        return Path(legacy).expanduser()
    return cookie_vault.merged_path()


def _upsert_env_value(env_file: Path, key: str, value: str) -> None:
    lines: list[str] = []
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()

    assign = f"{key}={value}"
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    replaced = False
    updated: list[str] = []

    for line in lines:
        if pattern.match(line):
            updated.append(assign)
            replaced = True
        else:
            updated.append(line)

    if not replaced:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(assign)

    env_file.write_text("\n".join(updated) + "\n", encoding="utf-8")


def _persist_cookie_file_path(cookie_file: Path, *, write_env: bool = True) -> str:
    normalized = str(cookie_file).replace("\\", "/")
    settings.YTDLP_COOKIE_FILE = normalized
    if write_env:
        try:
            _upsert_env_value(Path(".env"), "YTDLP_COOKIE_FILE", normalized)
        except Exception:
            logger.exception("Failed to persist YTDLP_COOKIE_FILE to .env")
    return normalized


def _parse_cookie_pairs(raw_cookie: str) -> list[tuple[str, str]]:
    from app.services.cookies import parse_cookie_input
    return [(item["name"], item["value"]) for item in parse_cookie_input(raw_cookie)]


async def _check_cookie(url: str) -> CookieCheckResponse:
    normalized_url = _normalize_input_url(url)
    if not normalized_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Invalid check URL format")

    try:
        info = await extract_info(normalized_url)
    except Exception as exc:
        return CookieCheckResponse(
            ok=False,
            message=str(exc),
            normalized_url=normalized_url,
        )

    return CookieCheckResponse(
        ok=True,
        message="Cookie check passed.",
        normalized_url=normalized_url,
        title=info.get("title") or "",
    )


@router.post("/extract", response_model=ExtractResponse)
async def create_extract_task(request: ExtractRequest) -> ExtractResponse:
    normalized_url = _normalize_input_url(request.url)
    if not normalized_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Invalid URL format")

    task_id = await task_manager.create_task()
    asyncio.create_task(
        _process_task(task_id, normalized_url, request.enable_timestamp),
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
    normalized_url = _normalize_input_url(url)
    if not normalized_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Invalid URL format")

    try:
        info = await extract_info(normalized_url)
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


@router.get("/cookie/status", response_model=CookieStatusResponse)
async def get_cookie_status() -> CookieStatusResponse:
    legacy = Path(settings.YTDLP_COOKIE_FILE).expanduser() if settings.YTDLP_COOKIE_FILE else None
    source = legacy if legacy and legacy.is_file() else cookie_vault.merged_path()
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines() if source.is_file() else []
    return CookieStatusResponse(
        cookie_file=str(source).replace("\\", "/"),
        exists=source.is_file() or bool(cookie_vault.list_domains()),
        line_count=len(lines),
        cookie_count=sum(1 for line in lines if line.strip() and not line.lstrip().startswith("#")),
    )


@router.get("/cookie/list", response_model=list[CookieDomainResponse])
async def list_cookies() -> list[CookieDomainResponse]:
    return [CookieDomainResponse(**item) for item in cookie_vault.list_domains()]


@router.post("/cookie/config", response_model=CookieConfigResponse)
async def configure_cookie(request: CookieConfigRequest) -> CookieConfigResponse:
    raw = request.raw_cookie.strip()
    try:
        from app.services.cookies import parse_cookie_input
        entries = parse_cookie_input(raw)
        if entries and any(item.get("domain") for item in entries):
            groups: dict[str, list[dict]] = {}
            for item in entries:
                if not item.get("domain"):
                    if not request.domain and not (request.url or request.check_url):
                        raise ValueError("Netscape/JSON Cookie 缺少 domain，请提供 domain 或 url")
                    item["domain"] = normalize_domain(request.domain) if request.domain else infer_domain(request.url or request.check_url or "")
                key = normalize_domain(item["domain"])
                groups.setdefault(key, []).append(item)
            for key, values in groups.items():
                saved = cookie_vault.upsert(key, values, source="manual")
            domain = normalize_domain(request.domain) if request.domain else next(iter(groups))
        else:
            domain = normalize_domain(request.domain) if request.domain else infer_domain(request.url or request.check_url or "")
            saved = cookie_vault.upsert(domain, entries or raw, source="manual")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    check_result = None
    message = "Cookie saved."
    if request.check_url and request.check_url.strip():
        check_result = await _check_cookie(request.check_url)
        cookie_vault.mark_check(domain, check_result.ok)
        message = "Cookie saved and verified." if check_result.ok else "Cookie saved, but verification failed."

    return CookieConfigResponse(
        ok=True,
        message=message,
        cookie_file=str(cookie_vault._source_path(domain)).replace("\\", "/"),
        pair_count=saved["cookie_count"],
        domain=domain,
        check=check_result,
    )


@router.delete("/cookie/{domain}")
async def delete_cookie(domain: str) -> dict[str, bool | str]:
    try:
        normalized = normalize_domain(domain)
        deleted = cookie_vault.delete(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"domain": normalized, "deleted": deleted}


@router.post("/cookie/sync-browser", response_model=CookieSyncResponse)
async def sync_browser_cookies(request: CookieSyncRequest) -> CookieSyncResponse:
    browser = (request.browser or settings.YTDLP_COOKIES_FROM_BROWSER or "").strip().lower()
    if browser not in {"chrome", "edge", "firefox"}:
        raise HTTPException(status_code=422, detail="浏览器仅支持 chrome、edge 或 firefox")
    try:
        entries = await asyncio.to_thread(browser_cookies, browser)
        grouped: dict[str, list[dict]] = {}
        for entry in entries:
            try:
                domain = normalize_domain(entry.get("domain", ""))
            except ValueError:
                continue
            grouped.setdefault(domain, []).append(entry)
        for domain, cookies in grouped.items():
            cookie_vault.upsert(domain, cookies, source="browser")
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if any(token in lowered for token in ("decrypt", "dpapi", "keyring", "database is locked", "permission denied", "could not copy")):
            detail = f"读取{browser} Cookie 失败（Windows 常见原因是浏览器加密或数据库占用）。请关闭所有浏览器窗口后重试，或改用开发者工具手动复制 Cookie 请求头。原始错误：{message}"
            raise HTTPException(status_code=400, detail=detail) from exc
        raise HTTPException(status_code=400, detail=f"浏览器 Cookie 导入失败：{message}") from exc
    return CookieSyncResponse(ok=True, message=f"已从 {browser} 导入 {sum(map(len, grouped.values()))} 项 Cookie", domains=[CookieDomainResponse(**item) for item in cookie_vault.list_domains()])


@router.post("/cookie/check", response_model=CookieCheckResponse)
async def check_cookie(request: CookieCheckRequest) -> CookieCheckResponse:
    try:
        domain = infer_domain(request.url)
    except ValueError:
        domain = None
    if domain and not cookie_vault._source_path(domain).is_file() and not Path(settings.YTDLP_COOKIE_FILE or "").is_file():
        return CookieCheckResponse(ok=False, message=f"未配置 {domain} 的 Cookie", normalized_url=_normalize_input_url(request.url))
    result = await _check_cookie(request.url)
    if domain:
        cookie_vault.mark_check(domain, result.ok)
    return result


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
