# Wenzi ASR 项目文档

## 1. 项目定位

Wenzi 是一个基于 FastAPI 的视频/音频转文字服务。系统保留现有的 yt-dlp、ffmpeg 和 FunASR 主链路，并合入字幕优先、Cookie Vault、结果持久化、批量队列和缓存能力。

核心原则是：平台表只做能力提示，档位由每个视频的运行时探测决定。同一平台的视频可能分别走字幕、登录提示或 ASR。

## 2. 目录结构

```text
app/
  main.py                    # FastAPI 入口、生命周期、静态页面
  config.py                 # .env/环境变量配置
  models.py                 # API 和任务数据模型
  routes.py                 # API 路由、队列和任务编排
  task_manager.py            # 内存缓存 + SQLite 双写任务管理
  services/
    router.py                # A/A_LOCKED/B1/B2/C 视频级判定
    subtitles.py             # VTT/SRT 字幕抓取与解析
    downloader.py            # yt-dlp 探测、下载、平台请求头
    cookies.py               # 分域 Cookie Vault
    storage.py               # SQLite、缓存、Markdown 落盘
    audio.py                 # ffmpeg 16k/mono/s16 转换
    asr.py                   # FunASR 模型和识别
    platforms.py              # 平台能力提示
    urlnorm.py               # 分享文案、短链和跟踪参数处理
  static/index.html           # 单任务、批量、历史和 Cookie 工作台
vendor/                      # 本地开源依赖，Git 忽略

data/app.db                 # 任务、分段和缓存索引
 data/cookies/               # <domain>.txt、_merged.txt、_meta.json
 data/output/<platform>/     # 完成任务的 Markdown 文案
tmp/                         # 下载和中间 WAV，任务结束清理
```

运行期 `data/` 和 `tmp/` 不提交 Git；真实 Cookie 也不进入日志和截图。

## 3. 端到端数据流

```text
URL/分享文案
  -> clean_share_text
  -> resolve_short_link（最多 5 跳，失败保留原 URL）
  -> strip_tracking
  -> platforms.detect（能力提示）
  -> router.resolve_video（运行时档位）
       | A: fetch_subtitles -> VTT/SRT -> completed
       | A_LOCKED: 明确提示 Cookie；fallback_asr=true 后走 ASR
       | B1/B2: yt-dlp 下载 -> ffmpeg -> FunASR -> completed
       | C: 无 extractor 时提示直链；媒体直链跳过平台探测
  -> TaskManager 内存状态 + SQLite 双写
  -> data/output/<platform>/*.md
```

任务状态为 `pending -> fetching_subtitle/downloading -> converting -> recognizing -> completed/failed`。取消会在阶段边界设置 `cancelled` 并结束任务。下载和 ASR 使用独立的 Semaphore，批量任务通过 asyncio Queue 调度。

## 4. API 契约

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/` | 健康状态 |
| `GET` | `/ui`、`/test` | 工作台 |
| `POST` | `/api/extract` | 单条任务，支持 `enable_timestamp`、`fallback_asr`、`force_asr` |
| `GET` | `/api/task/{id}` | 任务状态、文本、segments、档位和来源 |
| `DELETE` | `/api/task/{id}` | 取消任务 |
| `POST` | `/api/extract/batch` | URL 数组或整段文本批量提交 |
| `GET` | `/api/batch/{batch_id}` | 批次汇总和明细 |
| `GET` | `/api/task/{id}/export?format=md|txt|srt|json` | 四种 UTF-8 导出 |
| `GET` | `/api/history` | 历史分页、平台筛选、关键词搜索 |
| `DELETE` | `/api/history/{id}` | 删除历史和落盘文件 |
| `GET` | `/api/stats` | 任务、失败率、平台和字幕统计 |
| `GET` | `/api/queue` | 队列和 worker 统计 |
| `GET` | `/api/cache/stats`、`DELETE /api/cache` | 缓存管理 |
| `GET` | `/api/platforms`、`POST /api/detect` | 平台能力提示和 URL 识别 |
| `GET/POST/DELETE` | `/api/cookie/*` | Cookie 配置、检测、列表、同步和删除 |
| `GET` | `/api/info` | 视频元信息 |

任务结果的 `resolved_tier` 是 `A`、`A_LOCKED`、`B1`、`B2` 或 `C`；`source` 是 `subtitle`、`asr` 或 `direct`。开启时间戳时 `segments` 统一为秒数区间。

## 5. 持久化与安全

SQLite 使用 WAL、外键和任务/分段索引。任务完成后按平台和日期写入 Markdown，文件名会清理路径字符和 emoji；落盘失败不会把本已完成的识别改成失败。缓存默认 30 天，可通过 `force=true` 绕过。

Cookie Vault 按规范化域名隔离源文件，重建 `_merged.txt` 供下载器使用，并在 `_meta.json` 保存来源与健康状态。下载器按 URL 选择源文件和平台请求头，不向非 B 站请求注入 B 站 Referer。Cookie 使用细节见 [`cookie-guide.md`](cookie-guide.md)。

CDN 签名参数在错误日志中会脱敏；导出和历史接口不返回 Cookie。项目不提供绕过付费墙的能力。

## 6. 配置

`.env.example` 是可复制的配置模板，主要配置包括：

- 服务：`HOST`、`PORT`、`TEMP_DIR`。
- 模型：`ASR_MODEL`、`ASR_VAD_MODEL`、`ASR_PUNC_MODEL`、`ASR_DEVICE`、`ASR_BATCH_SIZE_S`。
- 超时和资源：`PROBE_TIMEOUT`、`DOWNLOAD_TIMEOUT`、`TASK_TIMEOUT`、`MIN_FREE_SPACE_MB`。
- 下载：`YTDLP_RATE_LIMIT`、`YTDLP_MAX_WORKERS`、`YTDLP_PROXY_DIRECT_DOMAINS`、`YTDLP_PROXY`、`YTDLP_USER_AGENT`。
- Cookie：`YTDLP_COOKIE_DIR`、`YTDLP_COOKIE_FILE`、`YTDLP_COOKIES_FROM_BROWSER`。
- 批量和缓存：`BATCH_MAX_ITEMS`、`CACHE_TTL_DAYS`、`DOWNLOAD_WORKERS`、`ASR_WORKERS`。

## 7. 验收与已知边界

本次 task-026 使用真实 Chrome DevTools 在 `http://127.0.0.1:8000/ui` 完成公开 YouTube 字幕链路：任务返回 `A / subtitle`、语言 `en`、123 个递增时间戳分段，文本约 3945 字，历史、Markdown/TXT/SRT/JSON 导出和缓存记录均可访问；浏览器控制台无错误。单元测试和编译检查也通过。

抖音、小红书、Instagram/X、SoundCloud、西瓜、微博等真实账号/链接依赖用户当前 Cookie、网络和内容权限，本环境没有合适的授权素材，因此不能把这些步骤伪称为端到端通过。快手、微信视频号、小宇宙的无 extractor 分支由单元测试和直链策略覆盖，真实 CDN 直链需要用户提供当前未过期的抓包结果。CDN 直链会过期，Cookie 也会失效。

启动：

```bash
python run.py
```

检查：

```bash
python -m unittest discover -s tests -v
python -m compileall -q app run.py tools/setup_douyin_cookie.py
```
