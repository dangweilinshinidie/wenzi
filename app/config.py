import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 服务配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # 临时文件目录
    TEMP_DIR: str = "./tmp"

    # 临时文件最大保留时间（秒）
    TEMP_FILE_MAX_AGE: int = 3600

    # ASR 模型配置
    ASR_MODEL: str = "paraformer-zh"
    ASR_VAD_MODEL: str = "fsmn-vad"
    ASR_PUNC_MODEL: str = "ct-punc"
    ASR_DEVICE: str = "cpu"
    ASR_BATCH_SIZE_S: int = 300

    # 下载超时（秒）
    DOWNLOAD_TIMEOUT: int = 600

    # 最大任务数
    MAX_TASKS: int = 100

    # Cookie Vault 目录及兼容旧配置
    YTDLP_COOKIE_DIR: str = "./data/cookies"
    YTDLP_COOKIE_FILE: str = ""
    # 浏览器同步来源，例如 chrome、edge 或 firefox；留空表示不自动读取浏览器
    YTDLP_COOKIES_FROM_BROWSER: str = ""
    # yt-dlp 代理（示例：socks5://127.0.0.1:7890 或 http://127.0.0.1:7890）
    YTDLP_PROXY: str = ""
    # 可选的现代浏览器 UA 覆盖值
    YTDLP_USER_AGENT: str = ""

    # ffmpeg 路径
    FFMPEG_PATH: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "vendor", "ffmpeg", "ffmpeg.exe"
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
