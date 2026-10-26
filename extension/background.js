// Syncs the banned-domain list into declarativeNetRequest rules and relays
// page reports from the content script to the shepherd server.
const SYNC_MINUTES = 5;

async function cfg() {
  const { server, key } = await chrome.storage.managed?.get(["server", "key"]).catch(() => ({})) ?? {};
  if (server && key) return { server, key };
  return chrome.storage.local.get(["server", "key"]);
}

async function api(path, init = {}) {
  const { server, key } = await cfg();
  if (!server || !key) throw new Error("not configured");
  const res = await fetch(server.replace(/\/$/, "") + path, {
    ...init,
    headers: { "Content-Type": "application/json", "X-Device-Key": key },
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

async function syncBanned() {
  try {
    const { domains } = await api("/api/banned");
    const rules = domains.map((d, i) => ({
      id: i + 1,
      priority: 1,
      action: { type: "redirect", redirect: { extensionPath: `/blocked.html?domain=${encodeURIComponent(d)}` } },
      condition: { requestDomains: [d], resourceTypes: ["main_frame"] },
    }));
    const old = await chrome.declarativeNetRequest.getDynamicRules();
    await chrome.declarativeNetRequest.updateDynamicRules({
      removeRuleIds: old.map((r) => r.id),
      addRules: rules,
    });
  } catch (e) {
    console.warn("shepherd sync failed", e);
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("sync", { periodInMinutes: SYNC_MINUTES });
  syncBanned();
});
chrome.runtime.onStartup.addListener(syncBanned);
chrome.alarms.onAlarm.addListener((a) => a.name === "sync" && syncBanned());

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type !== "page") return;
  api("/api/check", { method: "POST", body: JSON.stringify(msg.report) })
    .then(async (r) => {
      if (r.verdict === "block" && sender.tab?.id != null) {
        chrome.tabs.update(sender.tab.id, {
          url: chrome.runtime.getURL(`blocked.html?domain=${encodeURIComponent(new URL(msg.report.url).hostname)}`),
        });
        syncBanned(); // pick up auto-bans immediately
      }
      reply(r);
    })
    .catch((e) => reply({ error: String(e) }));
  return true;
});
