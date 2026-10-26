const $ = (id) => document.getElementById(id);
chrome.storage.local.get(["server", "key"]).then((v) => {
  $("server").value = v.server || "";
  $("key").value = v.key || "";
});
$("save").onclick = async () => {
  await chrome.storage.local.set({ server: $("server").value.trim(), key: $("key").value.trim() });
  $("ok").textContent = "saved";
};
