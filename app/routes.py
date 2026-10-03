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
    PlatformInfo,
    CookieSyncResponse,
    DetectRequest,
    DetectResponse,
    ExtractRequest,
    ExtractResponse,
    Segment,
    TranscriptSource,
    TaskResult,
    TaskStatus,
    VideoInfoResponse,
)
from app.services.asr import recognize
from app.services.audio import convert_to_16k_wav
from app.services.cookies import browser_cookies, cookie_vault, infer_domain, normalize_domain
from app.services.downloader import download_audio, extract_info
from app.services.platforms import ResolvedTier, all_platforms, detect, unsupported_hint
from app.services.router import classify_error, is_direct_media_url, resolve_video, sanitize_url
from app.services.subtitles import fetch_subtitles
from app.services.urlnorm import clean_share_text, is_short_link, resolve_short_link, strip_tracking
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


async def _normalize_task_url(raw_url: str) -> tuple[str, str]:
    cleaned = clean_share_text(raw_url)
    logger.info("URL normalization clean_share_text: %s -> %s", raw_url, cleaned)
    if not cleaned.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Invalid URL format")

    resolved = cleaned
    resolution_failed = False
    try:
        resolved = await resolve_short_link(cleaned)
        resolution_failed = resolved == cleaned and is_short_link(cleaned)
        logger.info("URL normalization resolve_short_link: %s -> %s", cleaned, resolved)
        if resolution_failed:
            logger.warning("URL short-link resolution returned the original short URL: %s", cleaned)
    except Exception as exc:
        resolution_failed = True
        logger.warning("URL short-link resolution failed for %s: %s", cleaned, exc)

    normalized = strip_tracking(resolved)
    platform = detect(normalized)
    platform_key = "generic" if resolution_failed else platform.key
    logger.info("URL normalization strip_tracking: %s -> %s", resolved, normalized)
    logger.info("URL normalization detect: %s -> %s", normalized, platform_key)
    return normalized, platform_key


@router.post("/extract", response_model=ExtractResponse)
async def create_extract_task(request: ExtractRequest) -> ExtractResponse:
    normalized_url, platform_key = await _normalize_task_url(request.url)
    task_id = await task_manager.create_task()
    asyncio.create_task(
        _process_task(task_id, normalized_url, request.enable_timestamp, request.fallback_asr, platform_key),
        name=f"extract-{task_id}",
    )
    return ExtractResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="Task created.",
    )


@router.get("/platforms", response_model=list[PlatformInfo])
async def list_platforms() -> list[PlatformInfo]:
    return [
        PlatformInfo(
            key=platform.key,
            name=platform.name,
            domains=list(platform.domains),
            short_link_domains=list(platform.short_link_domains),
            has_extractor=platform.has_extractor,
            may_have_subtitle=platform.may_have_subtitle,
            may_need_cookie=platform.may_need_cookie,
            cookie_names=list(platform.cookie_names),
        )
        for platform in all_platforms()
    ]


def _cookie_ready_for_url(url: str, platform) -> bool:
    if not platform.may_need_cookie:
        return True
    try:
        if cookie_vault._source_path(infer_domain(url)).is_file():
            return True
    except ValueError:
        pass
    legacy = Path(settings.YTDLP_COOKIE_FILE).expanduser() if settings.YTDLP_COOKIE_FILE else None
    return bool(legacy and legacy.is_file())


@router.post("/detect", response_model=DetectResponse)
async def detect_platform(request: DetectRequest) -> DetectResponse:
    normalized_url, platform_key = await _normalize_task_url(request.url)
    platform = detect(normalized_url) if platform_key != "generic" else detect("")
    return DetectResponse(
        platform=platform_key,
        has_extractor=platform.has_extractor,
        may_have_subtitle=platform.may_have_subtitle,
        may_need_cookie=platform.may_need_cookie,
        cookie_ready=_cookie_ready_for_url(normalized_url, platform),
        normalized_url=normalized_url,
        hint=unsupported_hint(platform),
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


async def _process_task(
    task_id: str,
    url: str,
    enable_timestamp: bool,
    fallback_asr: bool = False,
    platform_key: str | None = None,
) -> None:
    task_tmp_dir = Path(settings.TEMP_DIR) / task_id
    task_tmp_dir.mkdir(parents=True, exist_ok=True)

    async def run_pipeline() -> None:
        platform = detect(url)
        await task_manager.update_task(task_id, platform=platform_key or platform.key, normalized_url=url)
        decision = await resolve_video(url)
        await task_manager.update_task(
            task_id,
            resolved_tier=decision.tier.value,
            platform=platform_key or decision.platform.key,
            normalized_url=url,
            video_title=(decision.info or {}).get("title"),
            video_duration=(decision.info or {}).get("duration"),
        )
        if decision.tier == ResolvedTier.A_LOCKED and not fallback_asr:
            raise RuntimeError(decision.message)
        if decision.tier == ResolvedTier.A_LOCKED and fallback_asr:
            await task_manager.update_task(task_id, resolved_tier="B1")
        if decision.tier == ResolvedTier.C and not is_direct_media_url(url):
            raise RuntimeError(decision.message)
        if decision.error_type:
            raise RuntimeError(decision.message)

        if decision.tier == ResolvedTier.A:
            await task_manager.update_task(task_id, status=TaskStatus.FETCHING_SUBTITLE, progress="正在获取字幕。")
            result = await fetch_subtitles(url, decision.info or {})
            if result:
                entries, language = result
                segments = [Segment(**entry) for entry in entries]
                await task_manager.update_task(
                    task_id, status=TaskStatus.COMPLETED, progress="字幕提取完成。",
                    text="\\n".join(item.text for item in segments),
                    segments=segments if enable_timestamp else None,
                    source=TranscriptSource.SUBTITLE, subtitle_lang=language, language=language,
                )
                return
            logger.warning("Task %s subtitle path returned no usable captions; falling back to ASR", task_id)
            await task_manager.update_task(task_id, resolved_tier="B1")

        direct = is_direct_media_url(url)
        try:
            free_bytes = shutil.disk_usage(task_tmp_dir).free
            if free_bytes < settings.MIN_FREE_SPACE_MB * 1024 * 1024:
                raise RuntimeError("磁盘空间不足，请清理临时文件后重试。")
        except OSError:
            pass
        await task_manager.update_task(task_id, status=TaskStatus.DOWNLOADING, progress="正在下载媒体。")
        for attempt in range(3):
            try:
                audio_path, video_info = await download_audio(url, str(task_tmp_dir), task_id, decision.info)
                break
            except Exception as exc:
                error_type = classify_error(exc)
                if error_type not in {"network_error", "rate_limited"} or attempt == 2:
                    raise
                await asyncio.sleep(2 ** (attempt + 1))
        await task_manager.update_task(task_id, video_title=video_info.get("title"), video_duration=video_info.get("duration"))
        converted_audio_path = task_tmp_dir / f"{task_id}_16k.wav"
        await task_manager.update_task(task_id, status=TaskStatus.CONVERTING, progress="正在转换音频。")
        wav_path = await convert_to_16k_wav(audio_path, str(converted_audio_path))
        await task_manager.update_task(task_id, status=TaskStatus.RECOGNIZING, progress="正在识别语音。")
        text, segments = await recognize(wav_path, enable_timestamp=enable_timestamp)
        await task_manager.update_task(
            task_id, status=TaskStatus.COMPLETED, progress="转写完成。", text=text,
            segments=segments if enable_timestamp else None, source=TranscriptSource.DIRECT if direct else TranscriptSource.ASR,
            language="zh", error=None,
        )

    try:
        await asyncio.wait_for(run_pipeline(), timeout=settings.TASK_TIMEOUT)
    except Exception as exc:
        error_type = classify_error(exc)
        message = str(exc)
        if error_type == "cookie_invalid":
            try:
                cookie_vault.mark_check(infer_domain(url), False)
            except ValueError:
                pass
        logger.error("Task %s failed (%s): %s", task_id, error_type, message.replace(url, sanitize_url(url)))
        message = message.replace(url, sanitize_url(url))
        await task_manager.update_task(
            task_id, status=TaskStatus.FAILED, progress="任务失败。", error=message,
            error_type=error_type,
        )
    finally:
        shutil.rmtree(task_tmp_dir, ignore_errors=True)
