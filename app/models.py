from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    RECOGNIZING = "recognizing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExtractRequest(BaseModel):
    url: str = Field(..., min_length=1, description="视频 URL")
    enable_timestamp: bool = Field(False, description="是否返回时间戳")


class ExtractResponse(BaseModel):
    task_id: str = Field(..., description="任务 ID")
    status: TaskStatus = Field(..., description="任务状态")
    message: str = Field("", description="提示信息")


class Segment(BaseModel):
    start: float = Field(..., description="开始时间（秒）")
    end: float = Field(..., description="结束时间（秒）")
    text: str = Field(..., description="文本内容")


class TaskResult(BaseModel):
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    progress: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    video_title: Optional[str] = None
    video_duration: Optional[float] = None
    text: Optional[str] = None
    segments: Optional[list[Segment]] = None
    error: Optional[str] = None


class VideoInfoResponse(BaseModel):
    title: str = Field(..., description="视频标题")
    duration: float = Field(..., description="视频时长（秒）")
    thumbnail: Optional[str] = Field(None, description="缩略图 URL")
    uploader: Optional[str] = Field(None, description="上传者")
    description: Optional[str] = Field(None, description="视频描述")


class CookieCheckRequest(BaseModel):
    url: str = Field(..., min_length=1, description="用于检测 Cookie 的视频 URL")


class CookieCheckResponse(BaseModel):
    ok: bool = Field(..., description="Cookie 是否可用")
    message: str = Field(..., description="检测结果描述")
    normalized_url: Optional[str] = Field(None, description="规范化后的检测 URL")
    title: Optional[str] = Field(None, description="检测成功时的视频标题")


class CookieConfigRequest(BaseModel):
    raw_cookie: str = Field(..., min_length=1, description="Cookie 请求头、Netscape 文件或插件 JSON")
    domain: Optional[str] = Field(None, min_length=1, description="Cookie domain；不填时从 url 推断")
    url: Optional[str] = Field(None, description="用于推断平台 domain 的 URL")
    check_url: Optional[str] = Field(None, description="可选：保存后立即检测的 URL")


class CookieConfigResponse(BaseModel):
    ok: bool = Field(..., description="保存是否成功")
    message: str = Field(..., description="保存/检测结果描述")
    cookie_file: str = Field(..., description="兼容字段；新接口返回对应域名源文件")
    pair_count: int = Field(..., description="写入的 cookie 项数")
    domain: Optional[str] = Field(None, description="规范化后的 cookie domain")
    missing_common: list[str] = Field(default_factory=list, description="缺失的常见关键 cookie")
    check: Optional[CookieCheckResponse] = Field(None, description="可选：保存后的检测结果")


class CookieDomainResponse(BaseModel):
    domain: str
    cookie_count: int = 0
    source: Optional[str] = None
    updated_at: Optional[str] = None
    check_ok: Optional[bool] = None
    checked_at: Optional[str] = None


class CookieStatusResponse(BaseModel):
    cookie_file: str = Field(..., description="兼容字段；合并 cookiefile 路径")
    exists: bool = Field(..., description="是否存在合并或源 cookie 文件")
    line_count: int = Field(..., description="合并 cookiefile 总行数")
    cookie_count: int = Field(..., description="合并 cookie 条目数量")


class CookieSyncRequest(BaseModel):
    browser: Optional[str] = Field(None, description="chrome、edge 或 firefox；不填时读取 YTDLP_COOKIES_FROM_BROWSER")


class CookieSyncResponse(BaseModel):
    ok: bool
    message: str
    domains: list[CookieDomainResponse] = Field(default_factory=list)
