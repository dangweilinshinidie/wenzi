# Wenzi Chrome/Edge 本地 Cookie 同步扩展

这个未打包扩展使用 Chromium 官方 `chrome.cookies` API，在浏览器保持运行时读取已登录平台的 Cookie，并只同步到本机 Wenzi 服务：

```text
http://127.0.0.1:8000/api/cookie/browser-sync
```

Cookie 值不会显示在扩展页面、接口响应或日志中。扩展不是 Chrome Web Store 发布版本，只应从可信的 Wenzi 项目目录加载。

## 安装

1. 启动 Wenzi：`python run.py`。
2. Chrome 打开 `chrome://extensions`，Edge 打开 `edge://extensions`。
3. 开启右上角的 **Developer mode / 开发者模式**。
4. 点击 **Load unpacked / 加载已解压的扩展程序**。
5. 选择本目录 `browser-extension`，不要选择其中的单个文件。
6. 回到已登录抖音、B 站等平台的同一个浏览器配置文件，刷新目标平台页面。
7. 返回 `http://127.0.0.1:8000/ui` 重新提交任务。

扩展会在 Cookie 变化时同步，并通过定时任务周期性重试。浏览器可以保持打开，不需要手动复制 Cookie。

## 权限与安全

- 只请求 manifest 中列出的支持平台域名 Cookie 权限。
- 只向本机 `127.0.0.1:8000` 发送同步请求，不向外部服务器发送 Cookie。
- 不要把 `service_worker.js` 或扩展目录改造成向公网地址发送数据。
- Cookie 等同于账号登录凭据；不要截图、分享、提交 Git 或粘贴到聊天中。
- 卸载扩展：在扩展管理页面点击 **Remove / 移除**。

如果扩展未同步成功，Wenzi 仍支持 yt-dlp 原生浏览器读取和手动 Cookie Vault。Windows Chrome 的数据库锁、DPAPI 和运行用户不一致可能影响原生读取，详见 [`../docs/cookie-guide.md`](../docs/cookie-guide.md)。
