# Wenzi 当前项目状态

> 本文面向维护者。普通用户请先阅读根目录 [`README.md`](../README.md)。

## 当前能力

Wenzi 是一个本地优先的视频/音频转文字服务，当前主链路包括：

- FastAPI + Uvicorn Web 服务，默认端口 `8000`，默认只监听 `127.0.0.1`。
- yt-dlp 视频信息、字幕和媒体提取；无 extractor 时支持媒体直链兜底。
- 字幕优先路由：`A / subtitle`、`A_LOCKED`、`B1 / ASR`、`B2 / ASR`、`C / direct`。
- FFmpeg 音频转换和 FunASR `paraformer-zh + fsmn-vad + ct-punc` 本地识别。
- Cookie Vault、Chrome/Edge 本地扩展同步、批量任务、SQLite 历史、缓存与 Markdown/TXT/SRT/JSON 导出。
- 单页 Web 工作台、Swagger API 文档和健康检查。

## 交付目录

```text
wenzi/
├── app/                      # FastAPI 后端和服务模块
│   ├── main.py               # 应用入口和生命周期
│   ├── routes.py             # API、任务编排和 Cookie 路由
│   ├── models.py             # 请求、响应和任务模型
│   ├── task_manager.py       # 任务管理
│   ├── services/             # 下载、字幕、音频、ASR、存储等服务
│   └── static/index.html     # Web 工作台
├── browser-extension/       # Chrome/Edge 未打包 Cookie 扩展
├── docs/                    # 架构、平台、Cookie 和许可证说明
├── tools/                   # 兼容性的本地 Cookie 命令行工具
├── vendor/                  # 可选的本地依赖源码/FFmpeg（不纳入 Git）
├── data/                    # 运行期数据库、Cookie、导出结果
├── tmp/                     # 运行期临时媒体和中间文件
├── .env.example             # 配置模板
├── requirements.txt         # Python 运行依赖
├── install_windows.bat      # Windows 安装入口
├── install.sh               # Linux/macOS 安装入口
├── run.py                   # 启动入口
└── README.md                # 用户唯一主说明
```

`data/`、`tmp/`、`.env`、`vendor/` 和 Python 缓存均为本机数据或可再生内容，不应提交。交付目录不包含回归测试、截图、日志、浏览器 profile 副本和 Agent 历史脚手架。历史回归验证在本次整理前已完成：编译检查通过，全量 29 项测试通过。

## 运行和数据流

```text
用户 URL / 分享文案
  -> URL 清洗、短链解析、平台识别
  -> 视频级运行时探测
       | A: 字幕获取 -> VTT/SRT/平台 JSON -> Segment
       | A_LOCKED: 登录/权限提示，可由用户选择 ASR 降级
       | B1/B2: yt-dlp -> FFmpeg -> FunASR
       | C: 媒体直链 -> FFmpeg/识别
  -> TaskManager + SQLite
  -> Web 结果、历史和导出文件
```

关键模块：

| 模块 | 职责 |
|---|---|
| `app/services/router.py` | 根据单个视频运行时结果选择处理档位 |
| `app/services/subtitles.py` | VTT、SRT 和 B 站字幕 JSON 解析 |
| `app/services/downloader.py` | yt-dlp 探测、音频下载、平台请求头和 Cookie 选择 |
| `app/services/cookies.py` | 分平台 Cookie Vault 和浏览器 Cookie 导入 |
| `app/services/audio.py` | FFmpeg 转 16 kHz、单声道、16-bit WAV |
| `app/services/asr.py` | FunASR 模型单例和异步识别 |
| `app/services/storage.py` | SQLite、任务结果、缓存和 Markdown 落盘 |

## 接口入口

- `GET /`：健康检查。
- `GET /ui`：Web 工作台。
- `GET /docs`：Swagger API 文档。
- `POST /api/extract`：创建单个转写任务。
- `GET /api/task/{task_id}`：查询任务。
- `POST /api/extract/batch`、`GET /api/batch/{batch_id}`：批量任务。
- `GET /api/history`：历史记录。
- `GET /api/task/{task_id}/export?format=md|txt|srt|json`：结果导出。
- `/api/cookie/*`：Cookie 配置、检查、列表、删除和浏览器同步。

## 安装和维护

普通用户使用根目录的 `install_windows.bat` 或 `install.sh` 创建虚拟环境。手动方式和 Chrome 扩展安装方式见 [`README.md`](../README.md)。

维护者常用检查：

```bash
python -m compileall -q app run.py tools/setup_douyin_cookie.py
python run.py
```

运行期真实平台验证不得把 Cookie、签名直链或个人视频内容写入提交。项目没有账号认证和多租户隔离，服务不应直接暴露到公网。

## 依赖和许可证

完整依赖说明见 [`reference-notes.md`](reference-notes.md) 和根目录 README 的“依赖项目与致谢”。Wenzi 直接使用 FastAPI、Uvicorn、yt-dlp、FunASR、PyTorch、FFmpeg 等项目，并参考了 AI-Video-Transcriber 的字幕解析思路；各项目许可证和模型许可需要分别遵守。
