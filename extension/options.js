const $ = (id) => document.getElementById(id);
const area = (share) => (share ? chrome.storage.sync : chrome.storage.local);

(async () => {
  const { shareSettings, instanceId } = await chrome.storage.local.get(["shareSettings", "instanceId"]);
  $("share").checked = !!shareSettings;
  $("iid").textContent = instanceId ? instanceId.slice(0, 8) : "(created on first use)";
  const v = await area(shareSettings).get(["server", "key"]);
  $("server").value = v.server || "";
  $("key").value = v.key || "";
})();

$("save").onclick = async () => {
  const share = $("share").checked;
  const values = { server: $("server").value.trim(), key: $("key").value.trim() };
  await chrome.storage.local.set({ shareSettings: share });
  await area(share).set(values);
  if (!share) await chrome.storage.sync.remove(["server", "key"]);
  $("ok").textContent = "saved";
};
