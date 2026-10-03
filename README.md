# Wenzi ASR

Wenzi 是一个基于 FastAPI、yt-dlp、ffmpeg 和 FunASR 的视频/音频转文字服务。输入在线视频 URL 后，服务会先做平台识别和视频级探测，再按实际结果选择字幕快路径、下载音频后 ASR、Cookie 提示或直链兜底。

## 当前能力

- **A 字幕路径**：探测到可用字幕时优先下载并解析 VTT/SRT，跳过音频下载和 ASR；返回 `source=subtitle` 和 `subtitle_lang`。
- **A_LOCKED**：检测到字幕但平台要求登录时，默认明确提示配置 Cookie；可通过 `fallback_asr=true` 主动降级到 ASR。
- **B1**：无字幕且无需 Cookie，下载音频、ffmpeg 转换并使用 FunASR 识别。
- **B2**：无字幕或平台需要登录，按 URL 从 Cookie Vault 选择对应平台 Cookie 后下载和识别。
- **C**：没有 yt-dlp extractor 的平台返回直链引导；用户提供 `.mp4`、`.m3u8`、`.mp3`、`.m4a`、`.wav` 或 `.flac` 直链时可跳过平台探测进入直链处理。
- 批量提交、异步队列、任务取消、结果缓存、SQLite 持久化、历史记录和 `md/txt/srt/json` 导出。
- 前端工作台：平台提示、任务轮询、档位展示、批量面板、历史记录、Cookie 状态和导出。

平台表只是能力提示，不决定单个视频的档位。同一平台的视频会根据运行时探测结果分别走 A、A_LOCKED、B1 或 B2。

## 启动

```bash
python run.py
```

默认地址：`http://127.0.0.1:8000`

- 健康检查：`GET /`
- Swagger：`http://127.0.0.1:8000/docs`
- 工作台：`http://127.0.0.1:8000/ui`

首次启动需要下载 FunASR 模型。Windows 环境请确认 Python、ffmpeg、yt-dlp 依赖可用；初始化脚本为 `guifan/init.bat`。

## API

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/api/extract` | 创建单条转写任务，支持 `enable_timestamp`、`fallback_asr`、`force_asr` |
| `GET` | `/api/task/{task_id}` | 查询任务状态和结果 |
| `DELETE` | `/api/task/{task_id}` | 取消未完成任务 |
| `POST` | `/api/extract/batch` | 提交 URL 数组或整段文本，默认最多 20 条 |
| `GET` | `/api/batch/{batch_id}` | 查询批次汇总和逐条任务 |
| `GET` | `/api/task/{task_id}/export?format=md\|txt\|srt\|json` | 导出任务结果 |
| `GET` | `/api/history` | 分页、平台筛选和关键词搜索历史记录 |
| `DELETE` | `/api/history/{task_id}` | 删除历史记录及落盘文案 |
| `GET` | `/api/platforms` | 获取平台能力提示表 |
| `POST` | `/api/detect` | 清洗 URL 并返回平台提示，不返回运行时档位 |
| `GET` | `/api/queue` | 查看队列和执行计数 |
| `GET` | `/api/cache/stats` | 查看缓存统计 |
| `DELETE` | `/api/cache` | 清理缓存索引 |
| `GET` | `/api/cookie/list` | 查看 Cookie 域名和健康元数据，不返回 Cookie 值 |
| `POST` | `/api/cookie/config` | 保存请求头、Netscape 或插件 JSON Cookie |
| `POST` | `/api/cookie/sync-browser` | 尝试从 Chrome、Edge 或 Firefox 导入 |
| `POST` | `/api/cookie/check` | 检查指定平台 Cookie |

单条任务示例：

```json
{
  "url": "https://www.youtube.com/watch?v=...",
  "enable_timestamp": true,
  "fallback_asr": false,
  "force_asr": false
}
```

完成结果包含 `resolved_tier`、`source`、`platform`、`normalized_url`、`language`、`subtitle_lang`、`text` 和可选 `segments`。A_LOCKED 默认失败是有意设计，避免未经用户确认就消耗 ASR 资源。

## 数据与目录

```text
app/services/router.py       # 视频级档位判定和错误分类
app/services/subtitles.py    # VTT/SRT 解析和字幕快路径
app/services/cookies.py      # 多平台 Cookie Vault
app/services/storage.py      # SQLite、缓存和文案落盘
app/services/downloader.py   # yt-dlp 探测、下载和平台请求头
app/static/index.html         # 工作台

data/app.db                  # SQLite 任务和历史数据（运行期）
data/output/<platform>/       # Markdown 文案（运行期）
data/cookies/                 # 分平台 Cookie 源文件（运行期）
tmp/                          # 下载和中间音频（运行期）
```

`data/`、`tmp/`、Cookie 数据、数据库和模型依赖不应提交到 Git。Cookie API 不回传 Cookie 明文。

## 配置

`.env.example` 已包含当前配置。重要项：

- `PORT`：默认 `8000`
- `PROBE_TIMEOUT`、`DOWNLOAD_TIMEOUT`、`TASK_TIMEOUT`：探测、下载和任务总超时
- `YTDLP_COOKIE_DIR`、`YTDLP_COOKIES_FROM_BROWSER`、`YTDLP_PROXY`、`YTDLP_USER_AGENT`
- `YTDLP_RATE_LIMIT`、`YTDLP_MAX_WORKERS`、`YTDLP_PROXY_DIRECT_DOMAINS`
- `MIN_FREE_SPACE_MB`、`DOWNLOAD_WORKERS`、`ASR_WORKERS`
- `BATCH_MAX_ITEMS`、`CACHE_TTL_DAYS`

## Cookie 与平台限制

Cookie 获取和 Windows DPAPI/浏览器占用处理见 [`guifan/COOKIE_GUIDE.md`](guifan/COOKIE_GUIDE.md)。

- 快手、微信视频号、小宇宙没有原生 extractor 时需要抓取可用直链。
- 小红书图文笔记不提供视频转写路径。
- 会员、私密或登录墙内容需要对应账号 Cookie；不提供绕过付费墙的能力。
- CDN 直链带时效签名，过期后需要重新抓包。
- 平台风控和 extractor 会变化，B2/直链结果取决于当前网络、账号和链接有效期。

## 测试

```bash
python -m unittest discover -s tests -v
python -m compileall -q app tests run.py scripts/setup_douyin_cookie.py
```

task-026 的实际验收记录见 [`guifan/progress.txt`](guifan/progress.txt)，完整架构说明见 [`PROJECT_DOCUMENT.md`](PROJECT_DOCUMENT.md)。
