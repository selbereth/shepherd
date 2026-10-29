const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);

if (params.get("kind") === "ads") {
  // Ad/tracker/malware list: a warning with a way through, unlike parent-banned sites.
  $("title").textContent = "This site may be unsafe";
  $("msg").textContent = "It is on a list of ad, tracking or malware sites. Proceeding is logged for your parent.";
  $("actions").hidden = false;
  chrome.runtime.sendMessage({ type: "blocked-info" }).then((r) => {
    $("d").textContent = r?.domain || "";
    if (!r?.url) $("proceed").disabled = true;
  });
  $("back").onclick = () => (history.length > 1 ? history.back() : window.close());
  $("proceed").onclick = async () => {
    const r = await chrome.runtime.sendMessage({ type: "proceed" });
    if (r?.url) location.replace(r.url);
    else $("err").textContent = r?.error || "Couldn't continue.";
  };
} else {
  $("d").textContent = params.get("domain") || "";
}
