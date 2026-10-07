# 全平台文案提取改造计划（task-019 ~ task-026）

> 目标：让 `wenzi` 对**几乎所有主流平台**都能提取视频/音频并快速产出文案，
> 结果可持久保存、可导出、可批量。
> 核心手段：**四档平台策略 + 多平台 Cookie Vault + 字幕优先快路径**。

---

## 一、现状与差距

### 已有能力（task-001 ~ 018）
- yt-dlp 下载 + ffmpeg 转 16k 单声道 WAV + FunASR(paraformer-zh) 识别
- 单一 cookie 文件 `YTDLP_COOKIE_FILE`
- 单一代理 `YTDLP_PROXY`
- B站 playurl API 兜底 `_bilibili_stream()`
- 内存任务管理，重启即丢

### 硬伤（task-021 逐条复现并修复）
| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| 1 | cookie 文件只支持**一个** | `config.py: YTDLP_COOKIE_FILE` | 多平台不能共存 |
| 2 | cookie domain **写死 `.douyin.com`** | `routes.py: _write_netscape_cookie_file` | 小红书/B站 cookie 注入静默失效 |
| 3 | Referer **全局写死 B站** | `downloader.py: _base_ydl_options` | 对抖音/小红书请求带 B站 Referer，反而触发风控 |
| 4 | 无字幕快路径 | `routes.py: _process_task` | 有字幕也要下音频跑 ASR，慢 10~50 倍 |
| 5 | 无短链解析 | `routes.py: _normalize_input_url` | `v.douyin.com`、`b23.tv`、`xhslink.com` 只能走 generic 兜底，慢且易失败 |
| 6 | 无平台识别 | 全局 | 无法按平台选策略 / cookie / UA |
| 7 | 结果不落盘 | `task_manager.py` | 关服务文案就没了 |
| 8 | 无导出接口 | 仅前端拼 .md | 无法程序化获取文案 |
| 9 | 无批量 | `POST /api/extract` 单条 | 一次只能贴一个链接 |
| 10 | 无缓存 | 全局 | 同一视频重复识别，浪费算力 |

---

## 二、档位判定：按视频运行时决定，不按平台贴标签

### 2.1 核心原则（务必先看）

> **同一个平台的不同视频，档位可能不同。**
> 例如 Bilibili：有 CC 字幕的视频走 A 档（秒出），没有 CC 字幕的视频走 B 档（下载 + ASR）；
> 抖音：绝大多数视频走 B2（需 cookie），但用户如果手上有 CDN 直链则走 C 档。

因此：
- **平台表不是路由依据**，只是「能力提示（hints）」，用于 UI 预告与 cookie 预检
- **真正的路由依据是每个视频的运行时探测结果**
- 任务结果中记录 `resolved_tier`（实际走的档），前端展示实际路径而非平台标签

### 2.2 运行时判定链（每个视频独立执行）

```
输入：规范化后的 URL + 识别出的平台
  │
  ├─ 1. 该平台有 yt-dlp extractor 吗？
  │      否 → resolved = C（直链引导，见 2.6）
  │      是 ↓
  │
  ├─ 2. 探测 extract_info(url, download=False)
  │      │
  │      ├─ 探测失败，且错误特征为 cookie_invalid（403 / 需登录）
  │      │     → resolved = B2（提示配置 cookie 后重试）
  │      │
  │      ├─ 探测失败，其它错误
  │      │     → 按错误分类返回可读提示（见 task-023 错误分类）
  │      │
  │      └─ 探测成功 ↓
  │
  ├─ 3. info 里有可用字幕轨道（subtitles / automatic_captions，已排除 live_chat）？
  │      有 → resolved = A（走字幕，秒出）
  │      无 ↓
  │
  ├─ 4. 有字幕轨道但被登录墙挡住？（B站 need_login_subtitle 等）
  │      → resolved = A_LOCKED
  │        优先提示「配置 cookie 可秒出字幕」，同时允许用户选择降级 ASR
  │
  └─ 5. 确实无字幕轨道
         → resolved = B（下载 + ASR）
            · 该视频是否需要 cookie？由探测结果 + 平台 cookie_names 判断
            · 不需要 → B1
            · 需要   → B2
```

档位枚举：`A` / `A_LOCKED` / `B1` / `B2` / `C`

### 2.3 平台能力提示表（仅用于 UI 预告与 cookie 预检，不作为路由依据）

> 实证方法：`vendor/yt-dlp/yt_dlp/extractor/` 下逐文件检查
> `_get_cookies` / `_login_hint` / `LoginRequired` / `_perform_login` 命中情况，
> 以及 `grep -ril` 确认 extractor 是否存在。

平台表字段：`has_extractor` / `may_have_subtitle` / `may_need_cookie` / `cookie_names` / `short_link_domains`

#### 有字幕能力的平台（`may_have_subtitle = true`）
| 平台 | 域名 | 字幕情况 | 注意 |
|---|---|---|---|
| **YouTube** | youtube.com / youtu.be | 手动字幕 + 自动字幕 | 年龄限制/会员内容需 cookie |
| **Bilibili** | bilibili.com / b23.tv | 部分视频有 CC 字幕 | **需 SESSDATA**；**大量视频没有字幕，会落到 B 档** |

> ⚠️ `may_have_subtitle = true` 只表示「有可能有」，**不代表该视频一定有**。
> 每个视频都必须实际探测后才知道走 A 还是 B。

#### 预期 B1 档｜yt-dlp 直接可抓，不需要 Cookie
extractor 登录相关命中为 **0**，免 cookie 可直接抓取。

| 平台 | 域名 | 备注 |
|---|---|---|
| 西瓜视频 | ixigua.com | `IxiguaIE`，0 命中 |
| 腾讯视频 | v.qq.com | `tencent.py`，0 命中，免费内容 |
| 优酷 | youku.com | `YoukuIE`，0 命中，免费内容 |
| 爱奇艺 | iqiyi.com | 仅 `iq.com` 国际版有 1 处命中，主站免 cookie |
| 微博 | weibo.com | 0 命中 |
| Facebook | facebook.com | `FacebookIE`，0 命中，公开视频 |
| Apple Podcasts | podcasts.apple.com | 0 命中 |
| SoundCloud | soundcloud.com | `oauth_token` 仅用于 Go+/私有，公开曲目免 cookie |
| 喜马拉雅 | ximalaya.com | 仅 VIP 音轨需账号，免费内容免 cookie |
| 网易云音乐播客 | music.163.com | — |

#### 预期 B2 档｜yt-dlp **抓不了 / 被风控** → **必须 Cookie**（走 Cookie Vault + ASR）
extractor 硬性依赖 cookie，缺失时直接失败或返回空。

| 平台 | 域名 | 必需 Cookie | 源码依据 |
|---|---|---|---|
| **抖音** | douyin.com | `s_v_web_id` `ttwid` | `DouyinIE` 无 cookie 直接 `raise ExtractorError('Fresh cookies ... are needed')` |
| **小红书** | xiaohongshu.com | `web_session` `a1` | 依赖 `window.__INITIAL_STATE__`，未登录返回登录墙 |
| Instagram | instagram.com | `sessionid` | `_is_logged_in()` 检查 `_AUTH_COOKIE_NAME` |
| X / Twitter | x.com | `auth_token` `ct0` | `_API_BASE` cookie 检查 |
| TikTok | tiktok.com | 部分区域 | 5 处登录相关命中 |

> 另外：**B1 档平台的 VIP / 会员 / 私密内容**，也在运行时判定为 B2，需对应账号 cookie。
> 这正是「按视频判定」的又一处体现——同一个优酷链接，免费视频是 B1，会员视频是 B2。

#### 预期 C 档｜yt-dlp **无 extractor** → 直链兜底（用户抓包）
实证：`grep -ril "kuaishou\|channels.weixin\|xiaoyuzhou"` → **0 命中**。

| 平台 | 域名 | 方案 |
|---|---|---|
| 快手 | kuaishou.com | ⚠️ 无 extractor → 抓包 CDN 直链 |
| 微信视频号 | channels.weixin.qq.com | ⚠️ 无 extractor → 抓包 CDN 直链 |
| 小宇宙 | xiaoyuzhoufm.com | ⚠️ 无 extractor → 抓包 CDN 直链 |
| 其它任意站点 | * | GenericIE + 直链兜底 |

> 策略：提交时返回明确引导文案，并提供直链输入入口；直链过期时提示「请重新抓包」。
> C 档由 `has_extractor = false` 在判定链第 1 步直接确定，不依赖探测。

### 2.4 举例：Bilibili 一个平台覆盖三种档位

| B站视频情况 | 运行时判定 | 实际路径 |
|---|---|---|
| 有 CC 字幕 + 已配 SESSDATA | **A** | 下字幕，秒出 |
| 有 CC 字幕 + 未配 SESSDATA | **A_LOCKED** | 提示配 cookie 可秒出，或降级 ASR |
| 无 CC 字幕（大多数情况） | **B1** | 下载音频 + FunASR 识别 |
| 大会员专享内容 + 未配 cookie | **B2** | 提示配置账号 cookie |

---

## 三、目标架构

```
                    ┌──────────────────────────────┐
   URL / 分享文案 → │ urlnorm.py  短链解析 + 清洗   │
                    └──────────────┬───────────────┘
                                   ↓
                    ┌──────────────────────────────┐
                    │ platforms.py  识别平台        │
                    │ （只给能力提示，不做路由）      │
                    └──────────────┬───────────────┘
                                   ↓
        ┌──────────────────────────────────────────────────┐
        │ router.py  运行时判定链（按视频，不按平台）           │
        │  ① 无 extractor？      → C                       │
        │  ② 探测 extract_info(download=False)             │
        │  ③ 有可用字幕轨道？     → A                       │
        │  ④ 有字幕但被登录墙挡？ → A_LOCKED                │
        │  ⑤ 确实无字幕 → B：需 cookie？→ B1 / B2          │
        └──────┬────────────┬────────────┬─────────────────┘
               ↓            ↓            ↓
        ┌────────────┐ ┌──────────┐ ┌──────────┐
        │ A / A_LOCK │ │  B1      │ │  B2      │  ←── cookies.py
        │ subtitles  │ │ down+asr │ │ down+asr │      按平台注入
        └──────┬─────┘ └────┬─────┘ └────┬─────┘
               │            └─────┬──────┘
               │                  ↓
               │            ┌───────────┐
               │            │  asr.py   │
               │            └─────┬─────┘
               └──────────┬───────┘
                          ↓
            ┌──────────────────────────────┐
            │ storage.py  SQLite + 落盘     │
            │ exporter.py md/txt/srt/json   │
            │ 记录 resolved_tier 实际路径    │
            └──────────────────────────────┘

   ┌───────────────────────────────────────────────────────┐
   │ cookies.py  Cookie Vault（被 B2 与 A_LOCKED 共用）      │
   │  data/cookies/<domain>.txt   ← 粘贴 Cookie 头         │
   │  data/cookies/<domain>.txt   ← cookiesfrombrowser 同步│
   │  data/cookies/_merged.txt    → 注入 yt-dlp cookiefile │
   │  data/cookies/_meta.json     → 校验时间 / 健康状态     │
   └───────────────────────────────────────────────────────┘
```

### 新增文件清单
```
app/services/cookies.py      Cookie Vault（多平台存取 / 合并 / 校验 / 浏览器导入）
app/services/platforms.py    平台能力提示表（has_extractor / may_have_subtitle / may_need_cookie）
app/services/router.py       运行时判定链（按视频探测决定 A / A_LOCKED / B1 / B2 / C）
app/services/urlnorm.py      短链解析、URL 规范化、分享文案清洗
app/services/subtitles.py    字幕抓取 + VTT/SRT 解析（移植自 AI-Video-Transcriber）
app/services/storage.py      SQLite 持久化 + 文案落盘
data/cookies/                cookie 源文件目录
data/app.db                  SQLite 数据库
data/output/                 文案输出目录
```

---

## 四、任务拆解（8 个任务，共 177 步）

| 任务 | 描述 | 步骤 | 阶段 |
|---|---|---|---|
| **task-019** | 梳理现有 wenzi 项目全貌（模块 / 数据流 / 配置 / 已知问题） | 13 | 现状确认 |
| **task-020** | 调研新开源项目 AI-Video-Transcriber（架构 / 可复用点 / 许可合规） | 11 | 现状确认 |
| **task-021** | 排查现有 Cookie 相关 Bug 并重写多平台 Cookie 逻辑 | 20 | 现状确认 + 基建 |
| **task-022** | 建立平台能力提示表 + URL 规范化 + 平台识别 | 24 | 二开主体 |
| **task-023** | 实现运行时判定链与内容获取管线（逐视频判定 + 字幕优先 + 下载强化） | 39 | 二开主体 |
| **task-024** | 实现结果保存与导出（SQLite / 文案落盘 / 导出 API / 历史记录） | 25 | 二开主体 |
| **task-025** | 实现批量提交、结果缓存与并发队列 | 22 | 二开主体 |
| **task-026** | 端到端验证与文档更新 | 23 | 验证收尾 |

### 前 3 个任务的作用（现状确认）
- **task-019** 产出 `docs/codebase-map.md` —— 让后续所有任务都建立在**真实模块契约**上，而不是猜测
- **task-020** 产出 `docs/reference-notes.md` —— 明确「抄什么、不抄什么、怎么合规」
- **task-021** 先把 cookie 的 5 个 Bug **复现出来**再重写，避免在不理解旧逻辑的情况下改出新 Bug

### 后续任务的前置约束
task-022 ~ task-026 的**第一步都要求先读现有模块**（`codebase-map.md` / `downloader.py` / `routes.py` / `task_manager.py`），
确认接口契约后再动手，严禁凭空新增模块或破坏 task-017 已验证的流程。

---

## 五、最小可用里程碑

```
task-019 → 020 → 021 → 022 → 023
```
完成即可实现：**贴链接 → 识别平台 → 逐视频运行时判定 → A 档秒出字幕 / B1·B2 档走 ASR 出文案**。

注意：「A 档秒出」是**视频级**结论，不是平台级。同一个 B站链接，有 CC 字幕就秒出，没有就老老实实跑 ASR。

加上 task-024 即满足「保存」需求；task-025 满足「批量提速」；task-026 收尾验证。

---

## 六、风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 平台风控升级导致 extractor 失效 | 抖音/小红书随时可能挂 | 保留 C 档直链兜底；yt-dlp 用 git 管理便于升级 |
| 平台表被误当成路由依据 | 无字幕视频误走字幕路径而失败 | task-022/task-023 明确：平台表只给提示，**路由一律以运行时探测为准** |
| Cookie 频繁过期 | 用户需反复粘贴 | 优先推 `cookiesfrombrowser`；健康检查 + 失效告警 |
| Chrome cookie 加密（DPAPI）读取失败 | 一键导入不可用 | 降级为手动粘贴，返回明确指引而非 500 |
| 快手/视频号/小宇宙无 extractor | 无法覆盖 | 如实告知 + 直链通道；后续可自研 extractor |
| 大文件撑爆磁盘 | 服务不可用 | 磁盘检查 + 任务结束清理中间 WAV（已有 1.6GB 残留） |
| 批量任务触发限流 | IP 被封 | 限速 + 队列串行化 + 代理白名单预留 |
| 版权与合规 | 法律风险 | 仅个人学习使用；文档声明；不提供绕过付费墙能力 |
