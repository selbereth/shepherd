// Sends visible page text to the background worker for scoring.
(() => {
  const text = (document.body?.innerText || "").slice(0, 20000);
  chrome.runtime.sendMessage({
    type: "page",
    report: { url: location.href, title: document.title, text },
  });
})();
