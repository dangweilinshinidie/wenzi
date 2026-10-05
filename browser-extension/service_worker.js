const API = "http://127.0.0.1:8000/api/cookie/browser-sync";
const COOKIE_FILTERS = [
  { domain: "douyin.com" },
  { domain: "iesdouyin.com" },
  { domain: "bilibili.com" },
  { domain: "youtube.com" },
  { domain: "googlevideo.com" },
  { domain: "xiaohongshu.com" },
  { domain: "instagram.com" },
  { domain: "facebook.com" },
  { domain: "tiktok.com" },
  { domain: "x.com" },
  { domain: "twitter.com" },
];

let syncTimer;

function scheduleSync() {
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => syncCookies(), 1500);
}

async function syncCookies() {
  const seen = new Set();
  const cookies = [];
  for (const filter of COOKIE_FILTERS) {
    const items = await chrome.cookies.getAll(filter);
    for (const cookie of items) {
      const key = `${cookie.domain}\n${cookie.path}\n${cookie.name}`;
      if (seen.has(key)) continue;
      seen.add(key);
      cookies.push({
        domain: cookie.domain,
        name: cookie.name,
        value: cookie.value,
        path: cookie.path,
        secure: cookie.secure,
        httpOnly: cookie.httpOnly,
        expirationDate: cookie.expirationDate,
      });
    }
  }
  if (!cookies.length) return;
  try {
    const response = await fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cookies),
    });
    if (!response.ok) throw new Error(`sync failed: HTTP ${response.status}`);
    await chrome.storage.local.set({ lastSyncAt: Date.now(), lastSyncCount: cookies.length });
  } catch (error) {
    console.warn("Wenzi local cookie sync unavailable:", error.message);
  }
}

chrome.runtime.onInstalled.addListener(scheduleSync);
chrome.runtime.onStartup.addListener(scheduleSync);
chrome.cookies.onChanged.addListener(scheduleSync);
chrome.alarms.create("wenzi-cookie-sync", { periodInMinutes: 5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "wenzi-cookie-sync") scheduleSync();
});
scheduleSync();
