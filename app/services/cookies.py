from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.config import settings

COOKIE_ATTR_NAMES = {
    "path", "domain", "expires", "max-age", "secure", "httponly", "samesite", "priority",
}
DOMAIN_ALIASES = {
    "youtu.be": ".youtube.com",
    "b23.tv": ".bilibili.com",
    "xhslink.com": ".xiaohongshu.com",
    "vm.tiktok.com": ".tiktok.com",
}
COOKIE_LOCK = threading.Lock()


def normalize_domain(domain: str) -> str:
    value = (domain or "").strip().lower().rstrip(".")
    if value.startswith("http://") or value.startswith("https://"):
        value = urlsplit(value).hostname or ""
    value = value.lstrip(".")
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for ch in value):
        raise ValueError("Invalid cookie domain")
    if value.startswith("www."):
        value = value[4:]
    return "." + value


def infer_domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("URL must contain a hostname")
    for alias, domain in DOMAIN_ALIASES.items():
        if host == alias or host.endswith("." + alias):
            return domain
    parts = host.split(".")
    if len(parts) >= 3 and parts[0] == "www":
        host = ".".join(parts[1:])
    return normalize_domain(host)


def _safe_cookie(name: Any, value: Any) -> tuple[str, str] | None:
    key = str(name or "").strip()
    val = str(value or "").strip()
    if not key or key.lower() in COOKIE_ATTR_NAMES or any(ch in key for ch in "\t\r\n"):
        return None
    return key.replace("\t", "").replace("\r", "").replace("\n", ""), val.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def parse_cookie_input(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return []
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()

    entries: list[dict[str, Any]] = []
    if text.startswith("# Netscape HTTP Cookie File") or text.startswith("# HTTP Cookie File"):
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 7:
                continue
            pair = _safe_cookie(fields[5], fields[6])
            if pair:
                entries.append({"domain": fields[0], "name": pair[0], "value": pair[1], "path": fields[2] or "/", "secure": fields[3].upper() == "TRUE", "expires": _int_or_zero(fields[4])})
        return _dedupe_entries(entries)

    if text.startswith("[") or text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            payload = payload.get("cookies", [payload])
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                pair = _safe_cookie(item.get("name"), item.get("value"))
                if not pair:
                    continue
                domain = str(item.get("domain") or "")
                entries.append({"domain": domain, "name": pair[0], "value": pair[1], "path": str(item.get("path") or "/").replace("\t", ""), "secure": bool(item.get("secure", True)), "expires": _int_or_zero(item.get("expirationDate") or item.get("expires")), "http_only": bool(item.get("httpOnly", item.get("httponly", False)))})
            return _dedupe_entries(entries)

    cookie = SimpleCookie()
    try:
        cookie.load(text.replace("\r", " ").replace("\n", ";"))
    except Exception:
        return []
    for name, morsel in cookie.items():
        pair = _safe_cookie(name, morsel.value)
        if pair:
            entries.append({"domain": morsel["domain"], "name": pair[0], "value": pair[1], "path": morsel["path"] or "/", "secure": bool(morsel["secure"]), "expires": _int_or_zero(morsel["expires"]), "http_only": bool(morsel["httponly"])})
    return _dedupe_entries(entries)


def _int_or_zero(value: Any) -> int:
    try:
        return int(float(value)) if value else 0
    except (TypeError, ValueError):
        return 0


def _dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexes: dict[tuple[str, str, str], int] = {}
    result: list[dict[str, Any]] = []
    for entry in entries:
        pair = _safe_cookie(entry.get("name"), entry.get("value"))
        if not pair:
            continue
        entry = {**entry, "name": pair[0], "value": pair[1]}
        key = (str(entry.get("domain") or "").lower(), pair[0], str(entry.get("path") or "/"))
        if key in indexes:
            result[indexes[key]] = entry
        else:
            indexes[key] = len(result)
            result.append(entry)
    return result


def _netscape_lines(entries: list[dict[str, Any]], domain: str | None = None) -> list[str]:
    lines = ["# Netscape HTTP Cookie File", "# Generated by Wenzi CookieVault"]
    for item in entries:
        cookie_domain = str(item.get("domain") or domain or "")
        if not cookie_domain:
            continue
        if domain and not item.get("domain"):
            cookie_domain = domain
        cookie_domain = cookie_domain.lower()
        include_subdomains = "TRUE" if cookie_domain.startswith(".") else "FALSE"
        expires = _int_or_zero(item.get("expires")) or 2147483647
        lines.append("\t".join([
            cookie_domain,
            include_subdomains,
            str(item.get("path") or "/").replace("\t", ""),
            "TRUE" if item.get("secure", True) else "FALSE",
            str(expires),
            str(item["name"]).replace("\t", ""),
            str(item["value"]).replace("\t", " "),
        ]))
    return lines


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


class CookieVault:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or (Path("data") / "cookies"))
        self.meta_path = self.root / "_meta.json"
        self._lock = COOKIE_LOCK

    def merged_path(self) -> Path:
        return self.root / "_merged.txt"

    def _source_path(self, domain: str) -> Path:
        normalized = normalize_domain(domain)
        return self.root / f"{normalized.lstrip('.')}.txt"

    def _read_meta(self) -> dict[str, Any]:
        try:
            value = json.loads(self.meta_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_meta(self, meta: dict[str, Any]) -> None:
        _atomic_write(self.meta_path, json.dumps(meta, ensure_ascii=False, indent=2) + "\n")

    def _read_source(self, path: Path) -> list[str]:
        try:
            return path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

    def list_domains(self) -> list[dict[str, Any]]:
        meta = self._read_meta()
        result = []
        for path in sorted(self.root.glob("*.txt")):
            if path.name.startswith("_"):
                continue
            domain = normalize_domain(path.stem)
            rows = [line for line in self._read_source(path) if line.strip() and not line.lstrip().startswith("#")]
            result.append({"domain": domain, "cookie_count": len(rows), **meta.get(domain, {})})
        return result

    def get(self, domain: str) -> str | None:
        path = self._source_path(domain)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def upsert(self, domain: str, raw: str | list[dict[str, Any]], *, source: str = "manual") -> dict[str, Any]:
        normalized = normalize_domain(domain)
        entries = parse_cookie_input(raw) if isinstance(raw, str) else _dedupe_entries(raw)
        if not entries:
            raise ValueError("没有解析到有效 Cookie")
        for entry in entries:
            if not entry.get("domain"):
                entry["domain"] = normalized
        content = "\n".join(_netscape_lines(entries, normalized)) + "\n"
        with self._lock:
            _atomic_write(self._source_path(normalized), content)
            meta = self._read_meta()
            meta[normalized] = {"source": source, "updated_at": datetime.now(timezone.utc).isoformat(), "check_ok": None, "checked_at": None}
            self._write_meta(meta)
            self._rebuild_merged_locked()
        return {"domain": normalized, "cookie_count": len(entries), **meta[normalized]}

    def delete(self, domain: str) -> bool:
        normalized = normalize_domain(domain)
        with self._lock:
            path = self._source_path(normalized)
            existed = path.exists()
            path.unlink(missing_ok=True)
            meta = self._read_meta()
            meta.pop(normalized, None)
            self._write_meta(meta)
            self._rebuild_merged_locked()
        return existed

    def _rebuild_merged_locked(self) -> Path:
        lines = ["# Netscape HTTP Cookie File", "# Generated by Wenzi CookieVault"]
        for path in sorted(self.root.glob("*.txt")):
            if path.name.startswith("_"):
                continue
            lines.extend(line for line in self._read_source(path) if line.strip() and not line.startswith("#"))
        _atomic_write(self.merged_path(), "\n".join(lines) + "\n")
        return self.merged_path()

    def rebuild_merged(self) -> Path:
        with self._lock:
            return self._rebuild_merged_locked()

    def mark_check(self, domain: str, ok: bool) -> None:
        normalized = normalize_domain(domain)
        with self._lock:
            meta = self._read_meta()
            if normalized not in meta:
                meta[normalized] = {"source": "unknown", "updated_at": None}
            meta[normalized].update({"check_ok": bool(ok), "checked_at": datetime.now(timezone.utc).isoformat()})
            self._write_meta(meta)

    def ydl_cookie_opts(self, url: str) -> dict[str, str]:
        try:
            domain = infer_domain(url)
        except ValueError:
            return {}
        path = self._source_path(domain)
        if path.is_file():
            return {"cookiefile": str(path)}
        if self.list_domains():
            return {}
        merged = self.merged_path()
        return {"cookiefile": str(merged)} if merged.is_file() else {}


cookie_vault = CookieVault(settings.YTDLP_COOKIE_DIR)


def browser_cookies(browser: str) -> list[dict[str, Any]]:
    from yt_dlp.cookies import extract_cookies_from_browser

    jar = extract_cookies_from_browser(browser)
    entries = []
    for cookie in jar:
        pair = _safe_cookie(cookie.name, cookie.value)
        if not pair or not cookie.domain:
            continue
        entries.append({"domain": cookie.domain, "name": pair[0], "value": pair[1], "path": cookie.path or "/", "secure": bool(cookie.secure), "expires": _int_or_zero(cookie.expires), "http_only": bool(cookie.has_nonstandard_attr("HttpOnly"))})
    return _dedupe_entries(entries)
