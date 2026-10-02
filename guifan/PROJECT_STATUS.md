# Wenzi 项目当前状态说明

> 更新日期：2026-10-03
>
> 本文是 task-019 至 task-021 完成后的项目交接说明。它描述当前工作区代码，不把未提交的用户改动误记为本轮交付。

## 1. 项目定位

Wenzi 是一个基于 FastAPI 的视频/音频转文字服务：接收在线视频 URL，使用 yt-dlp 获取媒体，ffmpeg 转为 16 kHz、单声道、16-bit WAV，再由 FunASR `paraformer-zh + fsmn-vad + ct-punc` 识别中文文本，并可返回时间戳分段。

当前前三个现状确认任务已完成：

| 任务 | 产物 | 提交 |
|---|---|---|
| task-019 | `guifan/CODEBASE_MAP.md` | `19f73ce` |
| task-020 | `guifan/REFERENCE_NOTES.md` | `15e1150` |
| task-021 | Cookie Vault、多平台 Cookie API、下载器按域名注入 | 当前任务提交后记录 |

`task-022` 是下一项未完成任务，方向是平台能力提示、URL 清洗/短链解析和平台识别。

## 2. 目录结构

```text
wenzi/
├── app/
│   ├── __init__.py
│   ├── config.py                 # BaseSettings 与全局 settings
│   ├── main.py                   # FastAPI 入口、生命周期、CORS、静态页面
│   ├── models.py                 # Pydantic 请求/响应、任务状态、Cookie 模型
│   ├── routes.py                 # API 路由和后台任务编排
│   ├── task_manager.py           # 内存任务管理器
│   ├── services/
│   │   ├── __init__.py
│   │   ├── audio.py              # ffmpeg 转 16k/mono/s16 WAV
│   │   ├── asr.py                # FunASR 模型加载和识别
│   │   ├── cookies.py             # Cookie Vault、解析、合并、浏览器导入
│   │   └── downloader.py          # yt-dlp 元信息和音频下载
│   └── static/
│       └── index.html             # 当前可视化工作台
├── scripts/
│   ├── setup_douyin_cookie.py    # 旧版抖音 Cookie CLI，保持兼容
│   └── setup_douyin_cookie.bat
├── vendor/
│   ├── yt-dlp/                    # 已有开源依赖，.gitignore 排除
│   ├── FunASR/                    # 已有开源依赖，.gitignore 排除
│   ├── ffmpeg/                    # Windows ffmpeg，.gitignore 排除
│   └── AI-Video-Transcriber/      # task-020 参考仓库，.gitignore 排除
├── data/
│   └── cookies/                   # Cookie Vault 运行期数据，.gitignore 排除
├── tmp/                           # 下载/任务临时文件，.gitignore 排除
├── .env.example                   # 配置模板
├── requirements.txt               # Python 运行依赖
├── run.py                         # python run.py 启动入口
└── guifan/
    ├── task.json                  # 任务定义和完成标记
    ├── progress.txt               # 工作日志
    ├── CODEBASE_MAP.md            # 详细代码地图和已知问题
    ├── REFERENCE_NOTES.md         # AI-Video-Transcriber 调研与合规边界
    ├── PROJECT_STATUS.md          # 本说明
    ├── PLAN_PLATFORM.md           # task-019~026 平台化计划
    ├── CLAUDE.md                  # Agent 工作流规范
    └── init.bat                   # Windows 初始化脚本
```

`vendor/`、`data/`、`tmp/` 是运行或依赖目录，不应把 Cookie、数据库、临时媒体或大模型缓存提交到主仓库。当前工作区还存在一些用户预先放置的未跟踪目录/文件，处理时应先看 `git status`，不能批量删除或覆盖。

## 3. 后端入口与 API

启动命令：

```bash
python run.py
```

默认地址：`http://localhost:8000`。

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/` | 返回服务健康状态 |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/ui` | 当前前端工作台 |
| `GET` | `/test` | `/ui` 的兼容入口 |
| `POST` | `/api/extract` | 创建异步转写任务 |
| `GET` | `/api/task/{task_id}` | 查询任务状态和结果 |
| `GET` | `/api/info?url=...` | 获取视频标题、时长等元数据 |
| `GET` | `/api/cookie/status` | 兼容旧前端的 Cookie 总状态 |
| `GET` | `/api/cookie/list` | 列出 Cookie 域名、数量、来源和健康状态，不返回值 |
| `POST` | `/api/cookie/config` | 保存 Cookie 头、Netscape 文本或插件 JSON；支持 `domain`/`url` |
| `DELETE` | `/api/cookie/{domain}` | 删除指定域名 Cookie |
| `POST` | `/api/cookie/sync-browser` | 使用 yt-dlp 原生能力同步 Chrome/Edge/Firefox Cookie |
| `POST` | `/api/cookie/check` | 检查指定 URL 的 Cookie 是否可用，并更新 `_meta.json` |

基础任务请求：

```json
{
  "url": "https://www.bilibili.com/video/BV...",
  "enable_timestamp": true
}
```

基础任务阶段：

```text
pending
  -> downloading
  -> converting
  -> recognizing
  -> completed

任意阶段异常 -> failed
```

`TaskManager` 当前仍是进程内 `dict`，使用 `asyncio.Lock` 保护；服务重启后历史任务会丢失。这是 task-024 的持久化范围，不是 task-021 的修改目标。

## 4. 当前数据流

```text
URL / 分享文案
  -> routes._normalize_input_url
  -> task_manager.create_task
  -> _process_task
      -> downloader.download_audio
          -> _base_ydl_options(url)
              -> CookieVault 按域名选择 cookiefile
              -> 按平台选择 Referer/UA
      -> audio.convert_to_16k_wav
      -> asr.recognize
  -> task_manager.update_task(completed/failed)
  -> finally 删除 tmp/<task_id>
```

当前仍然是 ASR 主流程。字幕优先、逐视频档位判定等方向已经在 `PLAN_PLATFORM.md` 规划，参考算法和许可证边界记录在 `REFERENCE_NOTES.md`，尚未在 task-021 中接入。

## 5. Cookie Vault

运行期文件位于 `data/cookies/`：

```text
data/cookies/
├── douyin.com.txt
├── bilibili.com.txt
├── xiaohongshu.com.txt
├── _merged.txt
└── _meta.json
```

核心规则：

- `normalize_domain()` 统一为 `.example.com` 形式；`infer_domain()` 根据 URL 推断域名，并处理 `b23.tv`、`xhslink.com`、`youtu.be`、`vm.tiktok.com` 别名。
- `parse_cookie_input()` 支持浏览器 Cookie 头、`Cookie:` 前缀、Netscape 原文和插件导出的 JSON 数组。
- 同名 Cookie 后者覆盖；属性名 `path/domain/expires/max-age/secure/httponly/samesite/priority` 不作为 Cookie 项保存；名称、值和路径会去除换行/制表符，避免 Netscape 行注入。
- 每个平台独立源文件，`_merged.txt` 只是合并产物；`downloader._base_ydl_options(url)` 优先使用 URL 对应源文件，避免抖音 Cookie 带到 B 站或小红书。
- `_meta.json` 使用“临时文件写入 + `os.replace`”，合并过程由 `threading.Lock` 保护，记录 `source`、更新时间、`check_ok` 和检测时间。
- `YTDLP_COOKIES_FROM_BROWSER` 支持 `chrome`、`edge`、`firefox`，也支持 `edge:Profile` 形式；Windows DPAPI、数据库占用或权限错误会返回手动复制 Cookie 的中文指引。
- 旧 `YTDLP_COOKIE_FILE` 和 `scripts/setup_douyin_cookie.py` 继续兼容，但旧单文件只作为抖音 URL 的回退来源。
- 绝不在 API 响应中返回 Cookie 明文。

## 6. 配置重点

完整配置表见 `CODEBASE_MAP.md`。当前与 Cookie/下载相关的配置为：

```dotenv
YTDLP_COOKIE_DIR=./data/cookies
YTDLP_COOKIE_FILE=
YTDLP_COOKIES_FROM_BROWSER=
YTDLP_PROXY=
YTDLP_USER_AGENT=
```

服务默认 `PORT=8000`，下载线程池当前为 3 个 worker，ASR 线程池为 2 个 worker。

## 7. 已知限制和后续入口

- 平台能力表、URL 规范化、短链解析和平台识别尚未实现，下一项为 task-022。
- 尚未实现字幕优先运行时判定；当前所有任务仍走下载、转码、FunASR。
- 任务结果未落 SQLite，重启丢失；没有历史、导出 API、缓存和批量队列。
- 短链请求、代理协议校验、限速、探测/下载分离超时和磁盘空间治理待 task-022/023/025。
- 真实平台 Cookie 是否有效取决于账号、平台风控和 Cookie 时效；单元测试使用的是虚构 Cookie 值，不能替代真实账号验证。
- 小红书图文、会员/登录墙内容等平台限制需要在后续运行时档位和错误分类中如实提示，不应把平台名称当作固定路由策略。

继续开发前的最低检查：

```bash
git status --short --branch
python -m compileall -q app run.py scripts/setup_douyin_cookie.py
curl http://127.0.0.1:8000/
```

每个任务完成后：更新 `guifan/task.json` 的对应 `passes`、追加 `guifan/progress.txt`，进行 8000 端口测试，并创建独立 Git 提交。
