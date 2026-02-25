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
