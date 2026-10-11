/**
 * Клиентская логика дашборда памяти агента.
 *
 * Опрашивает /memory/snapshot, /memory/prompt-preview и /memory/events,
 * рисует три колонки слоёв, собранный промт и лог маршрутизации.
 */

const state = {
  sessionId: "",
  userId: "local-user",
  timer: null,
  longFilter: "",
  snapshot: null,
};

const $ = (id) => document.getElementById(id);

/* ---------- Утилиты ---------- */

function escapeHtml(text) {
  return (text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("ru-RU");
}

function formatTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString("ru-RU");
}

function showToast(message, type = "") {
  const toast = $("toast");
  toast.textContent = message;
  toast.className = `toast ${type}`;
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => toast.classList.add("hidden"), 3500);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (err) {
    data = null;
  }
  if (!response.ok) {
    const detail = (data && (data.detail || data.message)) || `Ошибка ${response.status}`;
    throw new Error(detail);
  }
  return data;
}

/* ---------- Рендер слоёв ---------- */

function renderShortTerm(payload) {
  $("short-count").textContent = formatNumber(payload.count);
  $("short-tokens").textContent = formatNumber(payload.tokens);
  const list = $("short-list");
  list.innerHTML = "";
  if (!payload.items.length) {
    list.innerHTML = '<div class="empty">Пока пусто — напишите сообщение в чате.</div>';
    return;
  }
  const total = payload.items.length;
  payload.items.forEach((item, index) => {
    const card = document.createElement("div");
    card.className = "card";
    // Свежие — последние 2 сообщения; старые (первые) подсвечиваем как «на обрезку».
    if (index >= total - 2) card.classList.add("fresh");
    if (index === 0 && total > 20) card.classList.add("stale");
    card.innerHTML = `
      <div class="card-head">
        <span class="card-role ${item.role}">${escapeHtml(item.role)}</span>
        <span class="card-ts">${formatTime(item.timestamp)}</span>
      </div>
      <div class="card-content">${escapeHtml(item.content)}</div>
      ${index === 0 && total > 20 ? '<div class="card-warn">⚠ будет обрезано при следующем сообщении</div>' : ""}
    `;
    list.appendChild(card);
  });
}

function renderWorking(payload) {
  $("working-count").textContent = formatNumber(payload.count);
  const tree = $("working-tree");
  tree.innerHTML = "";
  const data = payload.data || {};
  const entries = Object.entries(data).filter(([key, value]) => {
    if (key === "updated_at") return false;
    if (Array.isArray(value)) return value.length > 0;
    return Boolean(value);
  });
  if (!entries.length) {
    tree.innerHTML = '<div class="empty">Задача не активна — рабочая память пуста.</div>';
    return;
  }
  entries.forEach(([key, value]) => {
    const row = document.createElement("div");
    row.className = "kv";
    const rendered = Array.isArray(value) ? value.join("\n") : String(value);
    row.innerHTML = `
      <span class="kv-key">${escapeHtml(key)}</span>
      <span class="kv-val">${escapeHtml(rendered)}</span>
    `;
    tree.appendChild(row);
  });
}

function renderLongTerm(payload) {
  const items = payload.items.filter((fact) =>
    (fact.fact || "").toLowerCase().includes(state.longFilter)
  );
  $("long-count").textContent = formatNumber(payload.count);
  const list = $("long-list");
  list.innerHTML = "";
  if (!items.length) {
    list.innerHTML = '<div class="empty">Фактов нет — расскажите о предпочтениях.</div>';
    return;
  }
  items.forEach((fact) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="card-head">
        <span class="card-role user">${escapeHtml(fact.category || "general")}</span>
        <button class="fact-del" data-id="${escapeHtml(fact.id)}">Удалить</button>
      </div>
      <div class="card-content">${escapeHtml(fact.fact)}</div>
      <div class="fact-meta">
        <span>источник: ${escapeHtml(fact.source || "—")}</span>
        <span>${formatTime(fact.created_at)}</span>
        <span class="conf">уверенность: ${formatNumber(fact.confirmations)}</span>
      </div>
    `;
    card.querySelector(".fact-del").addEventListener("click", () => deleteFact(fact.id));
    list.appendChild(card);
  });
}

function renderPrompt(payload) {
  const pre = $("prompt-preview");
  pre.innerHTML = "";
  if (!payload.blocks || !payload.blocks.length) {
    pre.textContent = "Промт пуст.";
    return;
  }
  payload.blocks.forEach((block) => {
    const span = document.createElement("span");
    span.className = `src-${block.source}`;
    span.textContent = `### [${block.source}] ${block.role}\n${block.content}\n\n`;
    pre.appendChild(span);
  });
}

function renderEvents(payload) {
  const box = $("events");
  box.innerHTML = "";
  if (!payload.events.length) {
    box.innerHTML = '<div class="empty">Событий пока нет.</div>';
    return;
  }
  payload.events.forEach((event) => {
    const row = document.createElement("div");
    row.className = "event";
    const value = typeof event.value === "string" ? event.value : JSON.stringify(event.value);
    row.innerHTML = `
      <span class="event-ts">${formatTime(event.ts)}</span>
      <span class="event-layer ${event.layer}">${escapeHtml(event.layer)}</span>
      <span class="event-text">${escapeHtml(event.action)} ${escapeHtml(event.key || "")} → ${escapeHtml((value || "").slice(0, 80))}</span>
    `;
    box.appendChild(row);
  });
}

/* ---------- Загрузка данных ---------- */

async function refresh() {
  if (!state.sessionId) {
    showToast("Укажите session_id (id чата)", "err");
    return;
  }
  try {
    const query = `session_id=${encodeURIComponent(state.sessionId)}&user_id=${encodeURIComponent(state.userId)}`;
    const [snapshot, prompt, events] = await Promise.all([
      api(`/memory/snapshot?${query}`),
      api(`/memory/prompt-preview?${query}`),
      api("/memory/events?limit=40"),
    ]);
    state.snapshot = snapshot;
    renderShortTerm(snapshot.short_term);
    renderWorking(snapshot.working);
    renderLongTerm(snapshot.long_term);
    renderPrompt(prompt);
    renderEvents(events);
    $("last-update").textContent = `обновлено ${formatTime(snapshot.last_update)}`;
    syncToggles(snapshot.enabled_layers);
  } catch (err) {
    showToast(err.message, "err");
  }
}

function syncToggles(enabled) {
  $("toggle-short").checked = enabled.includes("short");
  $("toggle-working").checked = enabled.includes("working");
  $("toggle-long").checked = enabled.includes("long");
  const off = ["short", "working", "long"].filter((layer) => !enabled.includes(layer));
  $("toggles-hint").textContent = off.length
    ? `Отключены: ${off.join(", ")} — ablation активен`
    : "Все слои включены";
}

/* ---------- Действия ---------- */

async function applyToggles() {
  const layers = [];
  if ($("toggle-short").checked) layers.push("short");
  if ($("toggle-working").checked) layers.push("working");
  if ($("toggle-long").checked) layers.push("long");
  try {
    await api("/memory/toggles", {
      method: "PATCH",
      body: JSON.stringify({ layers }),
    });
    await refresh();
  } catch (err) {
    showToast(err.message, "err");
  }
}

async function collapseWorking() {
  try {
    const result = await api("/memory/working/collapse", {
      method: "POST",
      body: JSON.stringify({ session_id: state.sessionId, user_id: state.userId }),
    });
    showToast(result.saved ? "Задача схлопнута в long-term" : "Нечего схлопывать", "ok");
    await refresh();
  } catch (err) {
    showToast(err.message, "err");
  }
}

async function clearWorking() {
  try {
    await api(`/api/memory/${encodeURIComponent(state.sessionId)}`, { method: "DELETE" });
    showToast("Рабочая память очищена", "ok");
    await refresh();
  } catch (err) {
    showToast(err.message, "err");
  }
}

async function deleteFact(factId) {
  try {
    await api(`/memory/long-term/${encodeURIComponent(factId)}`, { method: "DELETE" });
    showToast("Факт удалён — он больше не попадёт в промт", "ok");
    await refresh();
  } catch (err) {
    showToast(err.message, "err");
  }
}

async function clearEvents() {
  try {
    await api("/memory/events", { method: "DELETE" });
    await refresh();
  } catch (err) {
    showToast(err.message, "err");
  }
}

/* ---------- Инициализация ---------- */

function startAutoRefresh() {
  stopAutoRefresh();
  if ($("auto-refresh").checked) {
    state.timer = setInterval(refresh, 1000);
  }
}

function stopAutoRefresh() {
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
}

function bindEvents() {
  $("refresh").addEventListener("click", refresh);
  $("auto-refresh").addEventListener("change", startAutoRefresh);
  $("session-id").addEventListener("change", () => {
    state.sessionId = $("session-id").value.trim();
    refresh();
  });
  $("user-id").addEventListener("change", () => {
    state.userId = $("user-id").value.trim() || "local-user";
    refresh();
  });
  $("long-search").addEventListener("input", () => {
    state.longFilter = ($("long-search").value || "").toLowerCase().trim();
    if (state.snapshot) renderLongTerm(state.snapshot.long_term);
  });
  ["toggle-short", "toggle-working", "toggle-long"].forEach((id) => {
    $(id).addEventListener("change", applyToggles);
  });
  $("collapse-working").addEventListener("click", collapseWorking);
  $("clear-working").addEventListener("click", clearWorking);
  $("clear-events").addEventListener("click", clearEvents);
}

async function init() {
  bindEvents();
  // По умолчанию берём последний чат, чтобы дашборд сразу что-то показал.
  try {
    const data = await api("/api/chats");
    const chats = data.chats || [];
    if (chats.length) {
      state.sessionId = chats[0].id;
      $("session-id").value = chats[0].id;
    }
  } catch (err) {
    /* ignore */
  }
  await refresh();
  startAutoRefresh();
}

document.addEventListener("DOMContentLoaded", init);
