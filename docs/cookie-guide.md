# 多平台 Cookie 使用指南

Cookie 是登录凭据，等同于账号访问令牌。不要把真实 Cookie 发到聊天、提交到 Git、写入截图或粘贴到公开日志。Wenzi 的 Cookie API 列表只返回域名、数量、来源和检测状态，不会返回 Cookie 值。

## 手动从浏览器复制 Cookie

1. 在目标平台浏览器中登录，并打开目标视频页面。
2. 按 `F12` 打开 Chrome/Edge DevTools，选择 **Network（网络）**。
3. 刷新视频页，选取该站点的视频信息或页面请求（域名应属于目标平台）。
4. 在 **Headers（标头）** 的 **Request Headers（请求标头）** 中找到 `Cookie`。
5. 只在本机 Wenzi 工作台/受控 API 请求中粘贴 `Cookie` 请求头的值。不要复制 `Set-Cookie` 响应头。
6. 在工作台 Cookie 配置表单中为平台选一个对应的检测 URL，保存后检查状态。

也可以使用平台浏览器开发者工具的 Application/Storage > Cookies 查看对应域名下的 Cookie；复制时保留名称和值，不要把 Cookie 分享给他人。

## 使用 API 保存

Cookie 请求头可用 `POST /api/cookie/config` 保存。应按平台 URL 推断域名，或明确提供 `domain`。以下内容仅是字段格式示例，不是真实凭据：

```json
{
  "raw_cookie": "session_name=REDACTED; another_name=REDACTED",
  "url": "https://www.youtube.com/watch?v=VIDEO_ID"
}
```

响应中的 `cookie_file`、`pair_count` 和健康状态可用于确认写入；不要记录请求体。支持 Cookie 请求头、带 `Cookie:` 前缀、Netscape 文件内容以及浏览器插件 JSON 数组。Netscape/JSON 可提供原始 domain，或另外给 `domain`/`url`。

使用以下接口管理 Cookie：

- `GET /api/cookie/list`：域名、数量、来源、检测结果，不含明文值。
- `POST /api/cookie/check`：传入目标视频 `url` 做检查。
- `DELETE /api/cookie/{domain}`：删除指定域名 Cookie。
- `POST /api/cookie/sync-browser`：尝试通过 yt-dlp 原生浏览器读取能力导入。

## 浏览器一键导入

在 Swagger `/docs` 的 `POST /api/cookie/sync-browser` 中选择 `chrome`、`edge` 或 `firefox`，或在本地配置 `YTDLP_COOKIES_FROM_BROWSER` 后调用接口。浏览器导入依赖 yt-dlp 与当前操作系统的浏览器配置，不能保证每台机器都成功。接口成功后返回域名元数据；不要在日志中输出浏览器 Cookie 内容。

## Windows DPAPI、文件占用与降级

Chrome/Edge 通常会对 Cookie 数据库加密；Windows 上解密可能依赖当前登录用户的 DPAPI 密钥。以下情况会导致导入失败：

- 浏览器仍在运行，Cookie SQLite 数据库被锁定或无法复制。
- Agent/服务进程运行身份与浏览器登录身份不同，无法访问 DPAPI 密钥。
- 浏览器配置目录权限受限，或浏览器正在更新/同步。

可依次尝试：

1. 完全退出所有 Chrome/Edge 窗口和后台进程后再次导入。
2. 确认服务由当前桌面登录用户启动，而非另一个 Windows 服务账号。
3. 确认浏览器 profile 可正常解锁，并给本地用户读取 profile 的权限。
4. 若仍失败，使用上面的 DevTools Network 手动复制请求头 Cookie，保存到正确的平台域名。

浏览器导入失败不表示 Cookie 已过期。真实账号 Cookie 是否有效应通过目标视频的受控检测判断。过期 Cookie 可从浏览器重新复制并更新。

## 平台提示与边界

Cookie 名称会随平台版本变化，表中的名称只是提示，并非校验 Cookie 有效性的硬性规则。B2 平台应使用对应平台 Cookie，不要跨平台共用。会员或付费内容仍需合法账号权限；工具不绕过付费墙。日志、报错或分享截图前先遮蔽 Cookie、令牌和带签名的 CDN URL。
