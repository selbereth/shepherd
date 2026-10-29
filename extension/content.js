// Sends visible page text to the background worker for scoring.
// Single-page apps change content without a page load, so re-check when the URL changes or new text appears.
(() => {
  const MAX_CHARS = 20000;
  const URL_DELAY_MS = 1000; // let a route change finish rendering
  const RECHECK_MS = 5000; // at most one re-check per this long while the page keeps changing
  let lastUrl = "";
  let lastLen = 0;
  let lastSent = 0;
  let timer = null;

  function check() {
    timer = null;
    const body = document.body?.innerText || "";
    const sameUrl = location.href === lastUrl;
    // Re-checking the same URL only matters once there is meaningfully more text (infinite scroll, late loads).
    if (sameUrl && body.length < lastLen * 1.2 + 200) return;
    lastUrl = location.href;
    lastLen = body.length;
    lastSent = Date.now();
    // Feeds append new content at the end, so for a re-check send the newest text, not the first screen.
    const text = sameUrl ? body.slice(-MAX_CHARS) : body.slice(0, MAX_CHARS);
    // Adult sites label themselves (RTA); a precise signal that works even for pages with little text.
    const rating = document.querySelector('meta[name="rating" i]')?.content || "";
    try {
      chrome.runtime.sendMessage({ type: "page", report: { url: location.href, title: document.title, text, rating } });
    } catch { /* extension was reloaded; this content script is orphaned */ }
  }

  function schedule() {
    if (timer) return;
    const delay = location.href !== lastUrl ? URL_DELAY_MS : Math.max(URL_DELAY_MS, RECHECK_MS - (Date.now() - lastSent));
    timer = setTimeout(check, delay);
  }

  check();
  new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
})();
