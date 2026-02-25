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
