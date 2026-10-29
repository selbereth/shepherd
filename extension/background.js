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

// Dynamic rule ids: 1..9999 hard-blocked sites (adult/manual bans), 10000+ the ad/tracker/malware list.
// Priorities: banned 3 > "proceed anyway" allow 2 > ad/tracker block 1.
const ADS_BASE_ID = 10000;
const ADS_CHUNK = 1000;
const SUB_RESOURCES = ["sub_frame", "stylesheet", "script", "image", "font", "object", "xmlhttprequest", "ping", "media", "websocket", "other"];

async function replaceRules(isMine, addRules) {
  const old = await chrome.declarativeNetRequest.getDynamicRules();
  await chrome.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: old.filter((r) => isMine(r.id)).map((r) => r.id),
    addRules,
  });
}

async function syncBanned() {
  try {
    const { domains } = await api("/api/banned");
    await replaceRules((id) => id < ADS_BASE_ID, domains.map((d, i) => ({
      id: i + 1,
      priority: 3,
      action: { type: "redirect", redirect: { extensionPath: `/blocked.html?domain=${encodeURIComponent(d)}` } },
      condition: { requestDomains: [d], resourceTypes: ["main_frame"] },
    })));
  } catch (e) {
    console.warn("shepherd sync failed", e);
  }
}

// uBlock-style: ad/tracker/malware requests are dropped silently; navigating straight to one of
// those domains shows a warning page with "proceed anyway".
async function syncAdblock() {
  try {
    const { adblockVersion } = await chrome.storage.local.get("adblockVersion");
    const { version, domains } = await api("/api/adblock?since=" + encodeURIComponent(adblockVersion ?? ""));
    if (domains === null) return; // unchanged
    const rules = [];
    for (let i = 0; i * ADS_CHUNK < domains.length; i++) {
      const requestDomains = domains.slice(i * ADS_CHUNK, (i + 1) * ADS_CHUNK);
      const id = ADS_BASE_ID + i * 2;
      rules.push(
        { id, priority: 1, action: { type: "block" }, condition: { requestDomains, resourceTypes: SUB_RESOURCES } },
        {
          id: id + 1, priority: 1,
          action: { type: "redirect", redirect: { extensionPath: "/blocked.html?kind=ads" } },
          condition: { requestDomains, resourceTypes: ["main_frame"] },
        },
      );
    }
    await replaceRules((id) => id >= ADS_BASE_ID, rules);
    await chrome.storage.local.set({ adblockVersion: version });
  } catch (e) {
    console.warn("shepherd adblock sync failed", e);
  }
}

const syncAll = () => Promise.all([syncBanned(), syncAdblock()]);

// Remember the last real page each tab tried to open, so the warning page can offer to continue to it.
chrome.webNavigation.onBeforeNavigate.addListener(async (d) => {
  if (d.frameId !== 0 || !/^https?:/.test(d.url)) return;
  const { lastUrl = {} } = await chrome.storage.session.get("lastUrl");
  lastUrl[d.tabId] = d.url;
  await chrome.storage.session.set({ lastUrl });
});

async function proceedPast(tabId) {
  const { lastUrl = {}, allowSeq = 0 } = await chrome.storage.session.get(["lastUrl", "allowSeq"]);
  const url = lastUrl[tabId];
  if (!url) throw new Error("no page to continue to");
  const domain = new URL(url).hostname;
  await chrome.storage.session.set({ allowSeq: allowSeq + 1 });
  // Session rules last until the browser restarts, like uBlock's temporary "allow".
  await chrome.declarativeNetRequest.updateSessionRules({
    addRules: [{
      id: allowSeq + 1, priority: 2, action: { type: "allow" },
      condition: { requestDomains: [domain], resourceTypes: ["main_frame", ...SUB_RESOURCES] },
    }],
  });
  api("/api/proceed", { method: "POST", body: JSON.stringify({ url }) }).catch(() => {});
  return url;
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("sync", { periodInMinutes: SYNC_MINUTES });
  syncAll();
});
chrome.runtime.onStartup.addListener(syncAll);
chrome.alarms.onAlarm.addListener((a) => a.name === "sync" && syncAll());

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === "blocked-info") {
    chrome.storage.session.get("lastUrl").then(({ lastUrl = {} }) => {
      const url = lastUrl[sender.tab?.id];
      reply({ url: url || "", domain: url ? new URL(url).hostname : "" });
    });
    return true;
  }
  if (msg.type === "proceed") {
    proceedPast(sender.tab?.id).then((url) => reply({ url })).catch((e) => reply({ error: String(e) }));
    return true;
  }
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
