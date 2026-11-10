"use strict";

const element = id => document.getElementById(id);
const buttons = [...document.querySelectorAll("[data-action]")];
const labels = {
  active: "Служба работает, проверяем готовность приложения",
  inactive: "Aion остановлен",
  activating: "Aion запускается",
  deactivating: "Aion останавливается",
  failed: "Служба завершилась с ошибкой",
  unknown: "Состояние службы недоступно",
};
let pending = false;
let checking = false;
let service = "unknown";

async function api(path, options) {
  const response = await fetch(path, {cache: "no-store", ...options});
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : "Запрос не выполнен");
  }
  return response.json();
}

function updateButtons() {
  const unavailable = pending || ["activating", "deactivating", "unknown"].includes(service);
  for (const button of buttons) {
    const action = button.dataset.action;
    button.disabled = unavailable || (action === "start" ? service === "active" : service !== "active");
  }
}

async function refresh() {
  if (checking) return;
  checking = true;
  try {
    const status = await api("/api/status");
    service = status.service;
    const ready = service === "active" && status.ready;
    element("state").textContent = ready ? "Aion доступен" : labels[service] || labels.unknown;
    element("state").dataset.ready = String(ready);
    element("details").textContent = [
      status.version && "Версия " + status.version,
      status.result && status.result !== "success" && "Результат службы " + status.result,
      status.restarts && "Автоперезапусков " + status.restarts,
    ].filter(Boolean).join(" · ");
    element("load").textContent = status.load_1m.toFixed(2);
    element("memory").textContent = status.memory_percent.toFixed(0) + "%";
    element("disk").textContent = (status.disk_free_bytes / 1024 ** 3).toFixed(1) + " ГиБ";
    element("checked").textContent = "Обновлено в " + new Date().toLocaleTimeString("ru-RU");
    const link = element("aion");
    link.href = status.aion_url;
    link.hidden = !ready;
  } catch (error) {
    service = "unknown";
    element("state").textContent = error.message;
    element("state").dataset.ready = "false";
    element("aion").hidden = true;
  } finally {
    checking = false;
    updateButtons();
  }
}

for (const button of buttons) {
  button.addEventListener("click", async () => {
    const action = button.dataset.action;
    if (action === "stop" && !window.confirm("Остановить Aion для всех пользователей?")) return;
    pending = true;
    updateButtons();
    try {
      await api("/api/action/" + action, {method: "POST", headers: {"X-Ouroboros-Action": "1"}});
      element("message").textContent = "Команда принята. Состояние обновится автоматически.";
    } catch (error) {
      element("message").textContent = error.message;
    } finally {
      await refresh();
      pending = false;
      updateButtons();
    }
  });
}

refresh();
setInterval(refresh, 3000);
