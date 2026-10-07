# Wenzi 项目代码地图

> 基于当前源码整理，2026-10-03。本文用于维护者快速了解模块边界；普通用户请以根目录 `README.md` 和 `docs/project-status.md` 为准。

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
| `app/services/downloader.py` | yt-dlp 元信息提取和音频下载，含 Bilibili playurl 兜底 | `_base_ydl_options`, `_extract_info_sync`, `_download_audio_sync`, `_bilibili_stream`, `extract_info`, `download_audio` | 被 routes 调用；同步工作提交到 `ThreadPoolExecutor(max_workers=3)`；按 URL 选择 Cookie 和 Referer |
| `app/services/cookies.py` | 多平台 Cookie Vault、解析、原子合并、健康元数据、浏览器导入 | `CookieVault`, `parse_cookie_input`, `infer_domain`, `normalize_domain`, `browser_cookies` | 被 routes 和 downloader 调用；源文件按 domain 隔离 |
| `app/services/platforms.py` | 平台能力提示表、最长域名优先识别 | `Platform`, `ResolvedTier`, `detect`, `all_platforms`, `unsupported_hint` | 被 routes 和 urlnorm 调用；只提供提示，不决定任务路由 |
| `app/services/urlnorm.py` | 分享文案提取、短链解析、跟踪参数清理与缓存 | `clean_share_text`, `resolve_short_link`, `strip_tracking` | 被 routes 调用；解析失败时保留原 URL |
| `tests/` | 本次交付目录不保留测试源码 | 整理前已完成 29 项回归测试 | 测试源码应在独立开发分支维护 |
| `app/services/audio.py` | ffmpeg 音频规格转换 | `convert_to_16k_wav` | 被 `_process_task` 调用；异步子进程执行 ffmpeg |
| `app/services/asr.py` | FunASR 模型单例与识别 | `load_model`, `_recognize_sync`, `recognize` | 启动时预加载，任务中调用；线程池 `max_workers=2` |
| `app/static/index.html` | 单页工作台：视频信息、任务轮询、分段展示、Markdown 导出、抖音 Cookie 配置 | `fetchVideoInfo`, `startExtract`, `pollTaskOnce`, `buildDocumentMarkdown`, `exportDocument`, `saveCookieAndCheck` | 调用 `/api/info`、`/api/extract`、`/api/task/{id}`、`/api/cookie/*` |
| `tools/setup_douyin_cookie.py` | 命令行将 Cookie 请求头写为 Netscape 文件，可选 yt-dlp 检测并更新 `.env` | `read_raw_cookie`, `parse_cookie_pairs`, `write_netscape_cookie_file`, `check_cookie_works`, `main` | 独立脚本，使用 yt-dlp |
| `tools/setup_douyin_cookie.bat` | Windows CLI 包装入口 | - | 调用同目录 Python 脚本 |
| `requirements.txt` | Python 后端依赖 | - | 环境安装输入 |
| `dev/` | 开发历史已从交付目录移除 | 仅保留在 Git 历史中 | 不影响运行 |
| `docs/platform-plan.md` | task-019 至 task-026 的平台策略计划 | 四档分流与任务拆分 | 设计约束参考 |

## 3. 入口、API 与接口契约

`app/main.py` 注册 CORS（允许任意 origin/method/header，不允许 credentials）、`/api` 路由和 `/static` 挂载。`GET /` 返回健康 JSON；`GET /ui` 和 `/test` 返回 `app/static/index.html`。ASR 模型在 lifespan 启动阶段同步加载。

| 方法 | 路径 | 请求 | 成功响应 / 作用 | 错误行为 |
|---|---|---|---|---|
| `POST` | `/api/extract` | `ExtractRequest {url, enable_timestamp}` | `ExtractResponse {task_id,status,message}`；清洗并规范化 URL 后创建后台 asyncio task | URL 不是 http(s) 返回 422 |
| `GET` | `/api/platforms` | 无 | 平台能力提示列表 | 不包含 `resolved_tier` |
| `POST` | `/api/detect` | `DetectRequest {url}` | `DetectResponse {platform,has_extractor,may_have_subtitle,may_need_cookie,cookie_ready,normalized_url,hint}` | 不探测具体视频、不返回 `resolved_tier` |
| `GET` | `/api/task/{task_id}` | 路径参数 | `TaskResult` | 任务不存在 404 |
| `GET` | `/api/info?url=...` | URL 查询参数 | `VideoInfoResponse {title,duration,thumbnail,uploader,description}` | URL 格式错误 422；提取失败 400 |
| `GET` | `/api/cookie/status` | 无 | `CookieStatusResponse {cookie_file,exists,line_count,cookie_count}`，不返回 Cookie 值 | 读取文件错误目前未专门映射 |
| `POST` | `/api/cookie/config` | `CookieConfigRequest {raw_cookie,domain,check_url?}` | `CookieConfigResponse {ok,message,cookie_file,pair_count,missing_common,check?}`；写入当前单一 cookie 文件 | 输入不可解析返回 422；检测失败体现在 check.ok=false |
| `POST` | `/api/cookie/check` | `CookieCheckRequest {url}` | `CookieCheckResponse {ok,message,normalized_url,title?}` | 缺少 cookie 文件返回 ok=false；yt-dlp 错误转为 ok=false |

### 后台任务编排

```text
POST /api/extract
  -> clean_share_text 提取 URL
  -> resolve_short_link（最多 5 跳，失败保留原 URL）
  -> strip_tracking（保留 xsec_token）
  -> platforms.detect 并记录平台提示
  -> 校验 http(s)
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

## task-022 平台提示与 URL 规范化

平台能力表覆盖 YouTube、Bilibili、西瓜视频、腾讯视频、优酷、爱奇艺、微博、Facebook、Apple Podcasts、SoundCloud、喜马拉雅、网易云音乐播客、抖音、小红书、Instagram、X/Twitter、TikTok、快手、微信视频号和小宇宙。只有 YouTube 与 Bilibili 的 `may_have_subtitle` 为 true，意为平台可能提供字幕，并不代表每条视频都有。

`detect(url)` 使用完整 hostname 边界匹配并按域名长度降序。`ResolvedTier` 是运行时档位枚举；平台表和检测 API 不按平台静态字段选择档位。

URL 链路为分享文案提取、已知短链 HEAD（失败时 GET 手动跟随，最多 5 跳）、跟踪参数清理、平台识别。短链缓存 24 小时；异常保留原 URL并记录 warning。参数清理移除 `utm_*`、`share_*`、`timestamp`、`share_token`，保留小红书 `xsec_token`。

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
| `YTDLP_COOKIE_DIR` | `./data/cookies` | Cookie Vault 源文件、合并文件和元数据目录 |
| `YTDLP_COOKIE_FILE` | 空 | 旧版单文件兼容配置；新流程按 URL 选择 Vault 文件，旧文件只作为抖音兼容回退 |
| `YTDLP_COOKIES_FROM_BROWSER` | 空 | 可选 `chrome`、`edge`、`firefox` 或 `browser:Profile`，传给 yt-dlp 原生浏览器 Cookie 读取 |
| `YTDLP_PROXY` | 空 | 所有 yt-dlp 请求共用的代理 |
| `YTDLP_USER_AGENT` | 空 | 覆盖默认现代 Chrome UA |
| `FFMPEG_PATH` | 项目路径下 `vendor/ffmpeg/ffmpeg.exe` | ffmpeg 可执行文件；找不到时 audio 服务回退 PATH 中的 `ffmpeg` |

task-021 已增加多平台 Cookie Vault、按 URL 选 Cookie/请求头和浏览器导入配置；task-022 至 task-026 仍计划增加平台能力提示、URL 规范化、独立探测超时、限速/worker 等配置。

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
浏览器 Cookie 请求头 / Netscape 文本 / 插件 JSON
 -> POST /api/cookie/config {raw_cookie, domain? 或 url?}
 -> CookieVault 解析并按规范化域名拆分
 -> data/cookies/<domain>.txt 原子写入
 -> data/cookies/_meta.json 记录 source/时间/check_ok
 -> 重建 data/cookies/_merged.txt（原子替换）
 -> downloader._base_ydl_options(url) 按实际 URL 选择单平台源文件
```

Task-021 五项问题的复现结果与修复证据：

| # | 复现结果 | 根因 | 修复与证据 |
|---|---|---|---|
| 1 | 当前原路由写入 domain 参数本身没有写死 `.douyin.com`；隔离端点传 `.xiaohongshu.com` 后生成文件首列为 `.xiaohongshu.com` | task 描述的 domain 写死问题在当前工作树已由先前未提交实现部分修正 | `CookieVault.normalize_domain` 统一域名；路由可传 `domain` 或 `url` 推断。TestClient 对三个平台的配置均返回 200，且源文件按对应域名生成 |
| 2 | 先后配置抖音与小红书时，旧路由写入同一个 `YTDLP_COOKIE_FILE`，第二次写入覆盖第一次 | 单文件配置没有按平台隔离 | 新结构分别写入 `douyin.com.txt`、`xiaohongshu.com.txt`，重建 `_merged.txt`；隔离测试同时配置抖音/B站/小红书后 `/list` 有 3 项 |
| 3 | 旧 downloader 向任意 URL 提供同一 `cookiefile`；yt-dlp 会按 Netscape domain 过滤，但调用层无法保证 URL 只选择对应平台来源 | 单文件无 URL/domain 选择 | `_base_ydl_options(url)` 使用 `cookie_vault.ydl_cookie_opts(url)`；三个 URL 测试分别命中对应域名文件，且非目标平台不带抖音 Cookie |
| 4 | 旧 options 对抖音、小红书也带 `Referer: https://www.bilibili.com/` | 请求头全平台共用 | 现仅 Bilibili/B23 URL 注入 B站 Referer；隔离检查确认抖音和小红书 options 不含 Referer，UA 可配置覆盖 |
| 5 | 原实现没有持久 `_meta`；一次检测失败不会保存健康状态 | Cookie 健康结果只在响应中返回 | 新增 `_meta.json` 原子更新；`mark_check` 持久记录 `check_ok/checked_at`，配置时可选检测，后续任务可读取状态 |

新增 API：`GET /api/cookie/list`（仅域名/数量/来源/健康状态，不返回值）、`DELETE /api/cookie/{domain}`、`POST /api/cookie/sync-browser`。原有 `/status`、`/config`、`/check` 保留兼容。浏览器同步支持 Chrome/Edge/Firefox；Windows DPAPI/数据库锁类错误返回关闭浏览器或手动粘贴的中文降级提示。

其他仍然存在的项目级限制：
- URL 解析只提取首个 URL 和去尾标点，不解析短链、不清理跟踪参数（task-022 范围）。
- 任务字典只在进程内；服务重启后任务与结果丢失（task-024 范围）。
- `TEMP_FILE_MAX_AGE` 当前没有清理任务；不过单任务目录在结束 finally 清理。
- `/api/info` 把底层异常文本直接返回客户端；服务没有认证，且 CORS 对任意来源开放。

> 当前 Cookie 相关源码来自 task-021 开始前的用户未提交工作区，未将其追认为旧提交内容。验证只使用临时目录和虚构 Cookie 值，没有写入用户真实 Cookie；真实浏览器导入是否成功以当前 Windows 浏览器 DPAPI/占用状态为准。

## 9. task-001 至 task-018 交付边界

历史任务日志已从用户交付目录移除；当前能力以源码、README 和 docs 文档为准。

## 10. 后续任务接入约束

- 平台能力表是提示，不是每个视频的固定分流规则；实际档位必须以运行时探测结果决定。
- Cookie 存储按平台隔离，合并产物只供 yt-dlp 请求使用；API 不得回传明文 Cookie。
- 不整体 fork 参考项目；字幕算法移植需保留来源/许可/修改说明。
- 任务改动应维持已有 `/api/extract`、`/api/task/{id}` 和 `/api/info` 契约，回归验证 8000 服务及 UI/API。
