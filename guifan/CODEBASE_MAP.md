# Wenzi 项目代码地图

> 基于当前工作区源码梳理，2026-10-03。工作区包含尚未提交的 Cookie API、静态前端和 Bilibili 下载兜底改动；以下记录的是实际文件现状，不代表这些改动已提交或端到端验收。

## 1. 项目概况

Wenzi 是一个 FastAPI 视频/音频转文字服务。当前主链路由 yt-dlp 获取元信息和音频、ffmpeg 转换为 16 kHz 单声道 16-bit WAV、FunASR `paraformer-zh + fsmn-vad + ct-punc` 输出中文文本及可选时间戳。任务状态放在进程内存，服务重启后不可恢复。

## 2. 模块清单

| 文件 | 职责 | 关键函数 / 对象 | 调用关系 |
|---|---|---|---|
| `run.py` | 以配置的 HOST/PORT 启动 Uvicorn | `__main__` | 启动 `app.main:app` |
| `app/main.py` | FastAPI 入口、生命周期、CORS、页面路由和静态文件挂载 | `lifespan`, `read_root`, `ui_page`, `test_page` | 注册 `app.routes.router`；启动时创建临时目录并调用 `asr.load_model` |
| `app/config.py` | `.env` / 环境变量配置及全局单例 | `Settings`, `settings` | 被服务、路由和任务管理器读取 |
| `app/models.py` | API 请求/响应、任务状态和分段数据模型 | `TaskStatus`, `ExtractRequest`, `TaskResult`, Cookie 模型 | 被 `routes.py`、`task_manager.py`、`asr.py` 使用 |
| `app/task_manager.py` | 进程内任务 CRUD 和已结束任务清理 | `TaskManager.create_task/update_task/get_task/_cleanup_old_tasks` | 被 `routes.py` 调用；用 `asyncio.Lock` 串行保护字典操作 |
| `app/routes.py` | API 端点、输入 URL 清理、Cookie 单文件接口、后台任务编排 | `_normalize_input_url`, `_parse_cookie_pairs`, `_write_netscape_cookie_file`, `_resolve_cookie_file_path`, `_persist_cookie_file_path`, `_process_task` | 调用 task manager、downloader、audio、ASR |
| `app/services/downloader.py` | yt-dlp 元信息提取和音频下载，含 Bilibili playurl 兜底 | `_base_ydl_options`, `_extract_info_sync`, `_download_audio_sync`, `_bilibili_stream`, `extract_info`, `download_audio` | 被 routes 调用；同步工作提交到 `ThreadPoolExecutor(max_workers=3)` |
| `app/services/audio.py` | ffmpeg 音频规格转换 | `convert_to_16k_wav` | 被 `_process_task` 调用；异步子进程执行 ffmpeg |
| `app/services/asr.py` | FunASR 模型单例与识别 | `load_model`, `_recognize_sync`, `recognize` | 启动时预加载，任务中调用；线程池 `max_workers=2` |
| `app/static/index.html` | 单页工作台：视频信息、任务轮询、分段展示、Markdown 导出、抖音 Cookie 配置 | `fetchVideoInfo`, `startExtract`, `pollTaskOnce`, `buildDocumentMarkdown`, `exportDocument`, `saveCookieAndCheck` | 调用 `/api/info`、`/api/extract`、`/api/task/{id}`、`/api/cookie/*` |
| `scripts/setup_douyin_cookie.py` | 命令行将 Cookie 请求头写为 Netscape 文件，可选 yt-dlp 检测并更新 `.env` | `read_raw_cookie`, `parse_cookie_pairs`, `write_netscape_cookie_file`, `check_cookie_works`, `main` | 独立脚本，使用 yt-dlp |
| `scripts/setup_douyin_cookie.bat` | Windows CLI 包装入口 | - | 调用同目录 Python 脚本 |
| `requirements.txt` | Python 后端依赖 | - | 环境安装输入 |
| `guifan/task.json` | 任务定义和 passes 状态 | task-001 至 task-026 | Agent 工作流程输入；task-001 至 task-018 为 true，019 起为 false |
| `guifan/progress.txt` | 任务过程、验证证据和遗留信息 | Session 记录 | 后续开发交接依据 |
| `guifan/PLAN_PLATFORM.md` | task-019 至 task-026 的平台策略计划 | 四档分流与任务拆分 | 设计约束参考 |

## 3. 入口、API 与接口契约

`app/main.py` 注册 CORS（允许任意 origin/method/header，不允许 credentials）、`/api` 路由和 `/static` 挂载。`GET /` 返回健康 JSON；`GET /ui` 和 `/test` 返回 `app/static/index.html`。ASR 模型在 lifespan 启动阶段同步加载。

| 方法 | 路径 | 请求 | 成功响应 / 作用 | 错误行为 |
|---|---|---|---|---|
| `POST` | `/api/extract` | `ExtractRequest {url, enable_timestamp}` | `ExtractResponse {task_id,status,message}`；创建后台 asyncio task | URL 不是 http(s) 返回 422 |
| `GET` | `/api/task/{task_id}` | 路径参数 | `TaskResult` | 任务不存在 404 |
| `GET` | `/api/info?url=...` | URL 查询参数 | `VideoInfoResponse {title,duration,thumbnail,uploader,description}` | URL 格式错误 422；提取失败 400 |
| `GET` | `/api/cookie/status` | 无 | `CookieStatusResponse {cookie_file,exists,line_count,cookie_count}`，不返回 Cookie 值 | 读取文件错误目前未专门映射 |
| `POST` | `/api/cookie/config` | `CookieConfigRequest {raw_cookie,domain,check_url?}` | `CookieConfigResponse {ok,message,cookie_file,pair_count,missing_common,check?}`；写入当前单一 cookie 文件 | 输入不可解析返回 422；检测失败体现在 check.ok=false |
| `POST` | `/api/cookie/check` | `CookieCheckRequest {url}` | `CookieCheckResponse {ok,message,normalized_url,title?}` | 缺少 cookie 文件返回 ok=false；yt-dlp 错误转为 ok=false |

### 后台任务编排

```text
POST /api/extract
  -> 清理分享文案中的 URL，校验 http(s)
  -> TaskManager.create_task(): pending
  -> asyncio.create_task(_process_task)
      downloading: download_audio(url, task_dir, task_id)
      -> 保存 title / duration
      converting: ffmpeg -> 16kHz / mono / s16 WAV
      recognizing: FunASR recognize(wav, enable_timestamp)
      -> completed: 写入 text / 可选 segments / completed_at
      任一异常 -> failed: 写入 error / completed_at
      finally -> 删除 task_dir

GET /api/task/{id} 从当前进程 TaskManager 查询任务。
```

## 4. 任务状态机

```text
pending -> downloading -> converting -> recognizing -> completed
     \             \             \             \-> failed
      \-------------\-------------\--------------> failed
```

代码枚举是 `pending/downloading/converting/recognizing/completed/failed`。`completed_at` 在 manager 收到 completed 或 failed 更新时填充。没有持久化、恢复或跨进程共享。

## 5. 配置项

| 配置 | 默认值 | 含义 / 注意 |
|---|---|---|
| `HOST` | `0.0.0.0` | Uvicorn 监听地址 |
| `PORT` | `8000` | 服务端口 |
| `TEMP_DIR` | `./tmp` | 下载和任务临时目录 |
| `TEMP_FILE_MAX_AGE` | `3600` | 声明的临时文件保留秒数；目前主流程未引用 |
| `ASR_MODEL` | `paraformer-zh` | FunASR 主模型 |
| `ASR_VAD_MODEL` | `fsmn-vad` | VAD 模型 |
| `ASR_PUNC_MODEL` | `ct-punc` | 标点恢复模型 |
| `ASR_DEVICE` | `cpu` | ASR 设备 |
| `ASR_BATCH_SIZE_S` | `300` | FunASR `batch_size_s` |
| `DOWNLOAD_TIMEOUT` | `600` | yt-dlp socket timeout，目前探测与下载共用 |
| `MAX_TASKS` | `100` | 内存任务数量阈值；超量时仅尝试移除已完成/失败的最旧任务 |
| `YTDLP_COOKIE_FILE` | 空 | 当前单一 Netscape cookiefile 路径；缺省回退到 `TEMP_DIR/douyin.cookies.txt` |
| `YTDLP_PROXY` | 空 | 所有 yt-dlp 请求共用的代理 |
| `FFMPEG_PATH` | 项目路径下 `vendor/ffmpeg/ffmpeg.exe` | ffmpeg 可执行文件；找不到时 audio 服务回退 PATH 中的 `ffmpeg` |

本次平台扩展计划预计增加多平台 Cookie Vault、按 URL 选 Cookie/请求头、平台能力提示、URL 规范化、独立探测超时、限速/worker 等配置；具体随 task-021 至 task-026 实现再更新。

## 6. 下载、转码与识别细节

- yt-dlp 基础选项包括 quiet、no_warnings、noplaylist、socket_timeout；若配置路径存在则将 ffmpeg 所在目录传给 yt-dlp。
- 当前全局注入单个 Cookie 文件和单一代理。`http_headers` 全站统一带 `Referer: https://www.bilibili.com/` 与 Chrome 131 UA。
- Bilibili 兜底从 URL 取 BV 号，调用 `/x/player/pagelist` 找首 P 的 cid，再请求 `/x/player/playurl`，优先选 DASH 最大带宽音轨，回退 durl；元信息探测失败或音频下载失败时触发。
- yt-dlp 自带 FFmpegExtractAudio 后处理输出 WAV；之后 audio 服务再次显式转换为 16000 Hz、1 声道、signed 16-bit PCM。
- FunASR 模型由 `load_model()` 加锁单例加载；识别在线程池 2 worker 执行。开启时间戳时传入 `sentence_timestamp=True` 并映射结果为 `Segment(start,end,text)`。

## 7. 前端现状

`app/static/index.html` 是单文件 HTML/CSS/JS。页面有视频链接、时间戳开关、元信息查询、开始任务、状态进度、任务信息、结果文本、分段表、Markdown 预览/下载，以及抖音 Cookie 粘贴/保存检测/状态查询。任务每 2 秒轮询一次 `/api/task/{id}`，遇到 completed/failed 停止轮询。Markdown 由浏览器侧 `buildDocumentMarkdown()` 生成并通过 Blob 下载，不是服务端导出 API。

## 8. Cookie 当前流转与已知问题

```text
浏览器 Cookie 请求头
 -> POST /api/cookie/config {raw_cookie, domain?}
 -> _parse_cookie_pairs (分号/换行分割、过滤常见属性、同名后者覆盖)
 -> _resolve_cookie_file_path (YTDLP_COOKIE_FILE 或 tmp/douyin.cookies.txt)
 -> _write_netscape_cookie_file (所有值写到同一文件，domain 使用请求字段)
 -> _persist_cookie_file_path (改 settings 单例并写入 .env)
 -> downloader._base_ydl_options -> 将同一文件作为 cookiefile 注入所有 URL
```

Task-021 需要实证并修复的五项问题：

| # | 现象与复现 | 根因 | 影响面 |
|---|---|---|---|
| 1 | POST `/api/cookie/config` 传 `domain=www.xiaohongshu.com`，检查 Netscape 文件 domain 列；当前实现应使用传入值，需运行验证确认是否存在既有写死问题 | 路由层已参数化写 domain，但 Cookie 单文件/默认抖音设计仍可能导致前端固定传 `.douyin.com`；此前计划描述的“写死”与当前工作树代码并不完全一致 | 小红书/B站等 Cookie 可能绑定错误域名；需以端点实测及原始提交/脏工作区差异确认 |
| 2 | 先后配置抖音与小红书，检查配置后文件内容 | 单个 `YTDLP_COOKIE_FILE` 每次整体覆盖，没有按平台拆分/合并 | 后一平台覆盖前一平台，多个站点无法稳定共存 |
| 3 | 配置 B站 domain 的 cookie 后观察 yt-dlp 的请求/有效性 | `_base_ydl_options` 将同一文件无差别注入所有请求；Cookie domain 是否匹配由 Netscape 域匹配决定，当前缺乏按 URL 选择机制 | Cookie 可能静默不发送或跨域误带 |
| 4 | 检查 `_base_ydl_options` 的请求头或以本地 mock 捕获不同平台请求头 | Bilibili Referer 全站固定 | 抖音、小红书等非 B站请求带错 Referer，可能触发风控 |
| 5 | 配置失效 cookie 并运行 check，查看持久元数据 | 当前不存在 `_meta` 状态；校验失败仅在单次 HTTP 响应中返回 | 过期状态无法留存或供 UI/后续任务发现 |

其他明确限制：
- `/api/cookie/config` 的 `missing_common` 固定检查抖音 cookie 名称，不适合多平台。
- URL 解析仅抽取第一个 URL 和去尾标点，不解析短链、不清理跟踪参数。
- 任务字典只在进程内；服务重启后任务与结果丢失。
- 声称的 `TEMP_FILE_MAX_AGE` 当前没有清理任务；不过单任务目录在结束 finally 清理。
- 无单元测试目录/自动化测试配置已登记（需随后续任务建立针对性测试）。
- `/api/info` 把底层异常文本直接返回客户端；服务没有认证，且 CORS 对任意来源开放。

> 证据边界：本工作树中 `.env.example`、配置、路由、下载器、静态页、脚本均存在未提交改动。上表以当前实际实现描述，不能据此宣称旧 bug 已在正式历史中复现。task-021 将针对当前运行版本进一步实测，报告差异并补充证据。

## 9. task-001 至 task-018 交付边界

`guifan/task.json` 当前显示 task-001 至 task-018 为 `passes: true`，日志记录了项目脚手架、yt-dlp/FunASR/ffmpeg 依赖、后端与任务编排、端口 8000 Swagger/API 验证、错误输入验证。task-017 的日志记录了 B站短视频完整 ASR 和时间戳验证。task-019 至 task-026 是后续平台化扩展工作。当前工作区增加了 Cookie API 和前端，但这些未提交修改不应误称为既有 task-001~018 的提交内容。

## 10. 后续任务接入约束

- 平台能力表是提示，不是每个视频的固定分流规则；实际档位必须以运行时探测结果决定。
- Cookie 存储按平台隔离，合并产物只供 yt-dlp 请求使用；API 不得回传明文 Cookie。
- 不整体 fork 参考项目；字幕算法移植需保留来源/许可/修改说明。
- 任务改动应维持已有 `/api/extract`、`/api/task/{id}` 和 `/api/info` 契约，回归验证 8000 服务及 UI/API。
