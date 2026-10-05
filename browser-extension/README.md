# Wenzi Local Cookie Sync

This extension avoids Chromium v20/App-Bound Cookie decryption by using the browser's own `chrome.cookies` API while the browser is running.

## Install in Chrome or Edge

1. Open `chrome://extensions` in Chrome or `edge://extensions` in Edge.
2. Enable **Developer mode**.
3. Choose **Load unpacked**.
4. Select this `browser-extension` directory.
5. Keep the browser logged in to Douyin/Bilibili or another supported platform.

The extension synchronizes supported cookies to `http://127.0.0.1:8000`. It sends only to the local Wenzi service and the API never returns cookie values. The browser can remain open.

If the extension is installed before the service starts, it retries on cookie changes and every five minutes. After installing, refresh the target platform once or wait for the next sync alarm.
