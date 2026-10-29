// Sends visible page text to the background worker for scoring.
(() => {
  const text = (document.body?.innerText || "").slice(0, 20000);
  // Adult sites label themselves (RTA); a precise signal that works even for pages with little text.
  const rating = document.querySelector('meta[name="rating" i]')?.content || "";
  chrome.runtime.sendMessage({
    type: "page",
    report: { url: location.href, title: document.title, text, rating },
  });
})();
