# AI-Video-Transcriber 参考调研

> 调研对象：`https://github.com/wendy7756/AI-Video-Transcriber.git`
>
> 本地 checkout：`634e6a2207f54efa9874fd7cb58aea06e2a49e92`（commit message: `Update Readme`）。
>
> 说明：`vendor/` 已被本项目 `.gitignore` 排除，因此参考仓库源码只作为本地调研输入，不直接纳入 Wenzi 的主仓库提交。

## 1. 许可证与合规结论

仓库根目录 `LICENSE` 是 Apache License 2.0，原始许可证文本从第 1 行开始，授权条款在第 66 行附近，保留版权/许可证/NOTICE 与修改说明的要求在第 93 至 112 行附近，商标与名称限制在第 139 行附近。

在满足 Apache-2.0 条款的前提下，许可证允许商业使用、修改、再发布以及闭源衍生作品。这里的“可商用、可闭源”是许可证层面的结论，不等于对平台内容版权或第三方依赖许可证的法律意见。

如果 Wenzi 复制或派生参考项目代码，需要：

- 保留参考项目的 `LICENSE` 文本和适用的版权/NOTICE 信息。
- 在被修改的文件或随附文档中明确标注修改内容，不能把派生代码伪装成原始代码。
- 不使用作者、项目名称、商标或产品名称暗示作者背书、赞助或官方关系；Apache-2.0 第 6 条不授予商标权。
- 继续分别核对 yt-dlp、FunASR、faster-whisper 和模型的许可证及平台服务条款。

本项目的实现策略是只移植明确需要的字幕解析和“字幕优先”设计思路；若复制实际代码，`app/services/subtitles.py` 文件头必须保留来源 URL、Apache-2.0 许可和本项目修改说明。

## 2. 字幕获取与解析

### `backend/video_processor.py`

| 行号 | 函数 | 观察结果 | 对 Wenzi 的可复用价值 |
|---:|---|---|---|
| 120-220 | `fetch_subtitles` | 先用 yt-dlp `extract_info(download=False)` 探测标题、`subtitles` 与 `automatic_captions`；过滤 `live_chat`；手动字幕优先于自动字幕；语言优先级 `en > en-orig > zh-Hans > zh-Hant > zh > ja > ko > fr > de > es > 其余第一项`；只配置 `writesubtitles`/`writeautomaticsub`、`skip_download=True` 下载字幕；解析异常、找不到文件或空结果都返回 `None` 并回退音频流程；`finally` 删除独立字幕目录。 | 直接对应 Wenzi task-023 的 A 档快路径，但应复用既有探测信息，避免重复 `extract_info`。 |
| 224-310 | `_parse_vtt` | 识别 cue 时间行，支持 `HH:MM:SS` 与 `MM:SS`；移除 HTML/VTT 内联标签；解码常见 HTML 实体；空文本和重复文本去重；过滤长度小于 2 的文本。 | 移植到 `app/services/subtitles.py`，并将返回的字符串时间转为 Wenzi 的 `Segment` 秒数。 |
| 289-310 | VTT 二次去重 | 对已经解析的条目检查后续最多 3 条：如果后续文本以当前文本为起始前缀且更长，则当前条目是 YouTube 滚动追加的中间态，丢弃；这样只保留最终追加版本。 | 这是最值得移植的算法，避免自动字幕逐字追加造成重复文案。应保留来源注释和单元测试。 |
| 312-354 | `_parse_srt` | 按空行分块，查找时间行，清理标签，去重文本，返回 start/end/text。 | 可作为 SRT 备用解析器；当前实现对实体解码不如 VTT 完整，移植时统一文本清洗。 |
| 356-365 | `_normalize_time` | 去掉毫秒，将 `HH:MM:SS` 折算成 `MM:SS`，也接受 `MM:SS`。 | Wenzi 内部应保留浮点秒，最终格式化时再生成显示文本，避免丢失毫秒和时间轴精度。 |
| 368-389 | `_format_subtitle_entries` | 把字幕条目格式化成 Markdown，包含语言元信息、`[start - end]` 和文本。 | 仅借鉴输出结构；Wenzi 应统一返回 `TaskResult.text + Segment[]`，不把 Markdown 当内部接口。 |
| 395-451 | `download_and_convert` | 支持把已探测到的标题作为 `prefetched_title`，跳过重复元信息探测；下载后转 m4a。 | 复用“探测信息向后传递”的思想；Wenzi 继续使用既有 WAV/ffmpeg/FunASR 规格。 |

`fetch_subtitles` 的字幕下载阶段没有把 Cookie、代理或平台特定请求头传入 yt-dlp；这对公开内容有用，但不能替代 Wenzi 的 Cookie Vault 和反爬处理。

## 3. 无字幕转写参数

### `backend/transcriber.py`

`Transcriber.transcribe` 位于第 33 行附近，实际调用在第 54 至 75 行：

- `WhisperModel(model_size, device="cpu", compute_type="int8")`：延迟加载 CPU int8 模型。
- `beam_size=5`、`best_of=5`：基础解码质量配置。
- `temperature=[0.0, 0.2, 0.4]`：失败或低质量时递增温度重试。
- `vad_filter=True`，并设置 `min_silence_duration_ms=900`、`speech_pad_ms=300`：减少静音片段带来的无效识别。
- `no_speech_threshold=0.7`：更积极地过滤无语音段。
- `compression_ratio_threshold=2.3`、`log_prob_threshold=-1.0`：抑制重复或低可信度输出。
- `condition_on_previous_text=False`：降低错误累积造成连续重复的风险。
- 通过 `asyncio.to_thread` 执行阻塞的 Whisper 调用，避免阻塞事件循环。

Wenzi 当前使用 FunASR，不直接替换为 faster-whisper。可采纳的是 VAD、温度回退和“不让前文错误无限累积”的调参思路；参数必须以 FunASR `AutoModel.generate` 的实际契约为准，不能原样照搬。

## 4. 任务编排与 SSE

### `backend/main.py`

任务状态在第 80-119 行附近维护：`tasks` 从 `temp/tasks.json` 恢复，`save_tasks` 使用线程锁写回；`sse_connections` 按 task id 保存 `asyncio.Queue`。`broadcast_task_update` 在第 87-110 行将 JSON 状态广播给订阅者。

`process_video_task` 位于第 595 行附近，实际顺序是：

```text
创建任务状态
  -> 并行启动可选原视频下载
  -> fetch_subtitles（字幕优先）
       -> 命中字幕：跳过音频下载和 Whisper
       -> 无字幕：下载/复用视频音轨 -> Whisper
  -> _run_post_extract_pipeline
       -> 保存原始文案
       -> 无语音时短路，不调用 LLM
       -> 可选优化 -> 语言不同时翻译 -> 摘要
       -> 写入任务状态并广播 completed
```

该流程在约第 631-705 行实现了字幕优先和无字幕慢路径；字幕与原视频下载可以并行，慢路径还会复用原视频抽音轨，避免重复下载。

`GET /api/task-stream/{task_id}` 位于第 862-922 行：

1. 校验 task id。
2. 创建 task 专用 `asyncio.Queue` 并注册到 `sse_connections`。
3. 立即发送当前状态。
4. 循环等待状态更新，30 秒无消息发送 heartbeat。
5. 收到 `completed` 或 `error` 后退出。
6. 在 `finally` 移除连接。

Wenzi 当前使用轮询，不应为了移植 SSE 推翻已交付接口。后续可选地增加 SSE，但必须继续支持 `GET /api/task/{task_id}`，并使用统一状态模型。

## 5. 摘要与翻译依赖评估

### `backend/summarizer.py`

`Summarizer.__init__` 在第 10-34 行：从参数或 `OPENAI_API_KEY` 读取 Key，从参数或 `OPENAI_BASE_URL` 读取 OpenAI 兼容端点；没有 Key 时客户端为 `None`，优化流程回退原始转录，摘要流程使用备用摘要。`optimize_transcript` 在第 56 行附近，`summarize` 在第 972 行附近，均会调用兼容 OpenAI Chat Completions 的客户端。

### `backend/translator.py`

`Translator.__init__` 在第 13-58 行：同样支持请求参数或环境变量中的 API Key、Base URL 和模型；缺少 Key 时翻译不可用并返回原文。`translate_text` 在第 187 行附近，长文本按块调用 OpenAI 兼容 Chat Completions。

结论：

- 摘要和翻译不是字幕获取或中文 ASR 的必要依赖。
- 它们适合作为后处理可选能力，不能进入 Wenzi 的基础转文字成功条件。
- 当前 Wenzi 需求聚焦视频转文字，task-023 不引入其 OpenAI 后处理模块，避免新增 API Key、费用、隐私和失败面。

## 6. Cookie、代理和反爬能力实证

对本地 checkout 执行：

```text
rg -ni 'cookie' vendor/AI-Video-Transcriber --glob '!*.lock' --glob '!LICENSE'
```

未命中源码内容。仓库没有 Cookie 配置、Cookie 文件注入、`cookiesfrombrowser` 或 Cookie 健康检查逻辑。对 `proxy` 的源码搜索也没有发现 yt-dlp 代理策略。它主要依赖 yt-dlp 默认网络行为和用户/环境的网络条件。

因此不能把参考项目描述成具备反爬能力。明确分工如下：

| 能力 | AI-Video-Transcriber | Wenzi 二开方向 |
|---|---|---|
| 字幕优先 | 有，先探测字幕再决定是否 Whisper | 移植思路，结合运行时 A/A_LOCKED/B1/B2 判定 |
| VTT/SRT 解析 | 有，含滚动追加去重 | 移植并转为统一 Segment 模型 |
| 中文 ASR | 默认 faster-whisper，多语言 | 保留 FunASR `paraformer-zh` |
| Cookie 通道 | 无命中 | Cookie Vault，按平台独立存储 |
| 代理/请求头反爬 | 未提供 | 按 URL/平台选择 Cookie、UA、Referer 与代理 |
| 任务实时进度 | SSE + 文件任务状态 | 当前轮询契约继续保留，后续可扩展 |
| LLM 摘要/翻译 | 依赖 OpenAI 兼容 API Key | 暂不引入基础管线 |

## 7. 最终采纳边界

只采纳以下两类设计，不整体 fork：

1. **字幕优先快路径**：先探测并复用视频信息，字幕命中时跳过下载和 ASR，异常时可靠回落 ASR。
2. **字幕文本解析**：VTT/SRT 时间解析、HTML 清洗、语言选择、重复去重，尤其是 YouTube 滚动追加中间态二次去重。

不采纳：

- 整体替换 Wenzi 的 FunASR 管线为 faster-whisper。
- 整体复制参考项目的 OpenAI 摘要/翻译、静态页面、任务文件结构或 API 契约。
- 把没有 Cookie/代理能力的公开内容获取逻辑当作抖音、小红书、B站等平台的通用方案。
- 用平台静态标签替代逐视频运行时探测。

这样可以保留 task-001 至 task-018 已交付的 `/api/extract`、`/api/task/{task_id}`、`/api/info` 和 FunASR 流程，并把参考项目的价值限制在可验证、低耦合的字幕快路径与解析算法上。
