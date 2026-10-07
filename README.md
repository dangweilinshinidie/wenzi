# Wenzi｜视频转文字工作台

> **面向普通用户的本地优先视频转文字工具。** 有字幕先取字幕，没有字幕再转语音；支持批量任务、时间戳、结果历史与导出。
>
> 我们希望把它做到“地表最强视频转文字工具”——这是一项目标和产品愿景，不是独立评测或对所有平台、语言、设备的客观排名保证。欢迎用真实工作流检验，也欢迎贡献改进。

Wenzi 是一个可在个人电脑运行的本地 Web 服务。视频地址和登录 Cookie 由本机服务处理；浏览器扩展只把所选平台 Cookie 发往本机 `127.0.0.1:8000`。服务处理能力依赖视频可访问性、账号权限、网络、设备性能与平台规则，不承诺所有链接都可解析。

## 功能一览

- **字幕优先**：检测到字幕时优先抓取字幕，跳过音频下载和 ASR；字幕不可用时按实际路由下载音频并进行语音识别。
- **语音识别**：FunASR 中文识别，可选时间戳分段。
- **多平台与直链**：使用 yt-dlp 支持的平台解析；也可提供常见媒体直链。具体可用性以平台、视频和当前网络为准。
- **账号 Cookie**：支持本机 Cookie Vault 和 Chromium 扩展同步；不需要把 Cookie 粘贴到在线第三方。
- **批量和历史**：异步任务、批量提交、结果缓存、SQLite 历史和 Markdown/TXT/SRT/JSON 导出。
- **本地 Web 工作台**：浏览器打开即可使用，无需前端 Node 构建。

## 系统要求

### 推荐配置

| 项目 | 要求/建议 |
|---|---|
| 操作系统 | Windows 10/11 x64 首选；Linux/macOS 可尝试，但请自行安装匹配平台的 FFmpeg 并验证 FunASR 依赖 |
| Python | 3.10–3.11 64 位建议；项目依赖和 FunASR/模型兼容性可能随版本变化 |
| 内存 | 8 GB 起步，16 GB 或更多较适合本地 ASR；首次模型加载会占用额外内存 |
| 磁盘 | 为 Python 依赖、ASR 模型缓存和临时音频预留数 GB；长视频会额外消耗临时空间 |
| 网络 | 安装 Python 包、首次下载模型、访问视频平台需要可用网络；受地区或平台限制时可能需要合规网络配置 |
| 浏览器 | Chrome 或 Edge。仅在需要同步登录 Cookie 时安装本项目的未打包扩展 |
| 端口 | 本机 TCP `8000` 可用；默认仅绑定 `127.0.0.1` |

**ASR 推理使用 CPU 也可以运行，但会比有合适 GPU 的环境慢。** 具体速度取决于音频时长、硬件和模型加载情况。首次启动会从模型仓库下载模型，可能需要较长时间和数 GB 磁盘空间。

## 安装与运行（Windows）

### 1. 安装先决软件

1. 安装 **Python 3.10 或 3.11（64 位）**，安装时勾选 `Add Python to PATH`。
2. 安装 **Git for Windows**。
3. 安装 **FFmpeg** 并加入 PATH，或在项目 `vendor/ffmpeg/` 下提供 `ffmpeg.exe`、`ffprobe.exe`。可在终端确认：

   ```powershell
   python --version
   git --version
   ffmpeg -version
   ```

4. （推荐）安装 **Node.js LTS**。yt-dlp 解析部分 YouTube 内容时需要 JavaScript runtime；Node 能改善相关站点兼容性。
5. 确认本机 `8000` 端口未被其他程序占用。

### 2. 获取项目

```powershell
git clone <项目仓库地址>
cd wenzi
```

如果你拿到的是 ZIP 包，解压后进入含 `run.py` 的项目目录即可。

### 3. 创建虚拟环境并安装依赖

```powershell
.\install_windows.bat
```

脚本使用 Python 3.11（找不到时尝试 3.10），创建项目虚拟环境并安装依赖。如果你希望手动安装，可运行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如 PowerShell 阻止激活脚本，可在当前终端运行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

`requirements.txt` 会安装 yt-dlp、FunASR 和 Web 运行依赖。开发环境中的 `vendor/` 目录是可选的源码/二进制缓存，不是用户安装的前置条件。首次部署建议使用干净虚拟环境；不要安装到系统 Python。

### 4. 配置

```powershell
Copy-Item .env.example .env
```

一般可先使用默认配置。默认端口是 `8000`，ASR 使用 CPU。编辑 `.env` 可更改监听地址、代理、并发和模型选项。`.env`、Cookie 数据和任务数据库属于本机私密数据，不要上传或提交。

### 5. 启动服务

```powershell
python run.py
```

首次启动时 FunASR 会初始化并下载识别模型。看到服务启动日志后访问：

- 工作台：<http://127.0.0.1:8000/ui>
- 健康检查：<http://127.0.0.1:8000/>
- API 文档：<http://127.0.0.1:8000/docs>

关闭服务：在运行窗口按 `Ctrl+C`。如修改了 Python 代码或 `.env`，重启进程使配置生效。

### Linux/macOS 简要说明

安装 Python 3.10/3.11、Git、FFmpeg（系统包管理器安装），然后创建虚拟环境、安装 `requirements.txt` 并运行 `python run.py`。Linux/macOS 上需自行确认 FunASR 对当前 Python、PyTorch 和系统架构的兼容性；本项目的预置 FFmpeg 若为 Windows 二进制，不能用于其他操作系统。

## 安装 Chrome/Edge Cookie 扩展（可选）

**只有访问需要登录的视频时才需要扩展。** 它通过浏览器官方 Cookie API 读取已授权平台的 Cookie，避免部分新版本 Chrome Cookie 无法被 Python 直接解密的问题。扩展不是 Chrome Web Store 发布版本，需要从本机项目目录加载。

1. 确认 Wenzi 服务运行在 `http://127.0.0.1:8000`。
2. Chrome 打开 `chrome://extensions`；Edge 打开 `edge://extensions`。
3. 打开页面上的 **开发者模式（Developer mode）**。
4. 点击 **加载已解压的扩展程序（Load unpacked）**。
5. 选择项目中的 `browser-extension` 文件夹（不是其中的某个文件）。
6. 确认扩展已启用，并按浏览器提示批准所需站点 Cookie 权限。
7. 在同一个浏览器配置文件里登录目标平台，然后打开或刷新一次该平台页面。扩展会向本机同步，之后也会定期同步。
8. 返回 Wenzi 工作台重试任务。

扩展仅面向其权限清单里列出的支持域名，并配置为把数据发送到本机服务；请仅从可信项目副本加载扩展，不要将扩展目录改指向公网服务。卸载方式是在扩展管理页点击“移除”。细节见 [`browser-extension/README.md`](browser-extension/README.md)。

如果扩展未安装，Wenzi 仍保留 yt-dlp 浏览器 Cookie 读取和手动 Cookie 配置作为备选。Chromium 数据库锁、Windows DPAPI 或浏览器 profile 权限会影响原生读取；常见排查见 [`docs/cookie-guide.md`](docs/cookie-guide.md)。

## 日常使用

1. 打开 <http://127.0.0.1:8000/ui>。
2. 粘贴视频/音频页面链接，按需要开启时间戳。
3. 点击获取视频信息或开始转写，等待任务完成。
4. 在结果区查看文本、来源和时间戳；按需下载 Markdown、TXT、SRT 或 JSON。
5. 批量任务和历史记录可在工作台相应区域查看。

### 路由行为

- **A / subtitle**：找到可用字幕，直接下载解析字幕。
- **A_LOCKED**：检测到字幕但平台提示登录/权限不足；默认不静默消耗 ASR，允许时可选择降级识别。
- **B1 / ASR**：没有可用字幕时下载音频、FFmpeg 转换并用 FunASR 识别。
- **B2 / ASR**：需要登录 Cookie 的音频下载/识别路径。
- **C / direct**：平台 extractor 不适用时使用支持的媒体直链或按提示处理。

实际路由按单个视频的运行时探测决定，不是“平台列表里支持就保证所有视频能用”。私密视频、会员内容、地区限制、登录门槛、过期直链和平台风控都可能阻止处理；本项目不绕过付费墙或访问控制。

## Cookie 与隐私安全

- Cookie 等同于登录凭据。不要把它发到聊天、截图、Issue 或 Git 仓库。服务默认仅监听本机回环地址；不要改为对公网开放，项目目前没有用户认证或多租户隔离。
- 扩展同步内容只应发给本机 Wenzi；不要修改为公网地址。
- Cookie API 的列表和状态接口不回传 Cookie 明文。数据库/配置目录仍应由操作系统账号保护。
- `data/`、`.env`、浏览器 profile、任务结果可能含有隐私，不要公开分享。
- 仅处理你有权访问和转录的内容，并遵守平台条款、版权和当地法律。

## 依赖项目与致谢

Wenzi 使用或参考以下开源项目。依赖的版本、模型和二进制可能有各自独立许可，分发时应保留相应版权与许可文件；FunASR 模型权重也应单独核对其模型许可。

| 项目 | 用途 | 来源/许可说明 |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) / [Uvicorn](https://github.com/encode/uvicorn) | Web API 和 ASGI 服务 | MIT；以各自上游许可证为准 |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 视频信息、字幕和媒体提取 | 上游为 Unlicense；仓库可能包含本地源码副本，具体版本请查看其 LICENSE |
| [FunASR](https://github.com/modelscope/FunASR) | 本地语音识别及 VAD/标点 | 上游源码为 MIT；模型权重许可可能不同，须单独确认 |
| [FFmpeg](https://ffmpeg.org/) | 音频转换与媒体处理 | LGPL/GPL 取决于构建选项；本机二进制发行需检查对应构建许可 |
| [AI-Video-Transcriber](https://github.com/wendy7756/AI-Video-Transcriber) | 字幕解析实现的参考来源 | 项目采用 Apache-2.0；Wenzi 字幕解析模块注明了改动和来源，保留上游许可要求 |

除上表外，Python 传递依赖、模型仓库和平台提取器也可能各有许可与使用条款。请查阅对应上游文件和本项目发行包里的许可证，不要把“开源”理解成所有第三方模型、媒体或平台内容都可无限制使用。

## 项目结构

```text
README.md                 用户安装和使用说明
app/                      FastAPI 后端、转码/字幕/ASR 服务
app/static/               Web 工作台
browser-extension/        Chrome/Edge 本地 Cookie 扩展
requirements.txt           Python 运行依赖
run.py                    启动入口
.env.example              配置模板
data/                     运行期数据库、Cookie、导出结果（自动生成/本地私有）
tmp/                      临时下载和中间文件（自动生成）
docs/                     架构、Cookie、依赖来源和平台设计文档
tools/                    兼容性的本地 Cookie 命令行工具
```

## 开发者验证

```powershell
python -m compileall -q app run.py tools/setup_douyin_cookie.py
```

普通用户无需安装 Node 前端工具链，也无需运行开发检查。项目架构、Cookie、参考项目与平台补充材料位于 `docs/`；本项目交付目录不包含开发测试和 Agent 历史脚手架。

## 免责声明

项目名称和“地表最强”表述是愿景性宣传，不是客观、第三方认证的性能排名或准确率保证。字幕和 ASR 的可用性、准确率、延迟会因语言、音质、平台接口、模型、网络和硬件而变。请先自行评估再用于生产或重要决策。
