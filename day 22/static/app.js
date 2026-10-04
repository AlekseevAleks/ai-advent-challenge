/**
 * Клиентская логика SPA-интерфейса ИИ-чата.
 *
 * Отвечает за переключение экранов без перезагрузки, работу с настройками,
 * списком моделей и чатов, а также за приём SSE-стрима ответа ассистента.
 */

const state = {
  config: { api_url: "", api_key_masked: "", has_key: false, default_model: "" },
  models: [],
  chats: [],
  currentChat: null,
  streaming: false,
  controller: null,
  mcpServers: [],
  mcpCurrentId: null,
};

const $ = (id) => document.getElementById(id);

/* ---------- Утилиты ---------- */

/**
 * Форматирует стоимость в рублях с разумной точностью.
 *
 * Значение приходит от API в поле ``cost_rub``.
 */
function formatCost(value) {
  if (value === null || value === undefined) return "—";
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  if (num === 0) return "0,00 ₽";
  if (num < 0.01) return `${num.toFixed(5).replace(".", ",")} ₽`;
  return `${num.toFixed(4).replace(".", ",")} ₽`;
}

/** Возвращает стоимость в рублях из usage (поле ``cost_rub``) или null. */
function costOf(usage) {
  if (!usage) return null;
  const value = usage.cost_rub;
  if (value === null || value === undefined) return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

/** Форматирует число с разделителями разрядов. */
function formatNumber(value) {
  return Number(value || 0).toLocaleString("ru-RU");
}

/** Строит текст мета-строки с токенами и стоимостью для сообщения. */
function usageMetaText(usage) {
  if (!usage) return "";
  const prompt = Number(usage.prompt_tokens || 0);
  const completion = Number(usage.completion_tokens || 0);
  const total = Number(usage.total_tokens || prompt + completion);
  const cost = costOf(usage);
  const costText = cost === null ? "стоимость неизвестна" : `стоимость ${formatCost(cost)}`;
  return `Запрос: ${formatNumber(prompt)} · Ответ: ${formatNumber(completion)} · Всего: ${formatNumber(total)} · ${costText}`;
}

/** Строит текст мета-строки для сообщения пользователя (только токены запроса). */
function promptMetaText(usage) {
  if (!usage) return "";
  const prompt = Number(usage.prompt_tokens || 0);
  return `Токенов запроса: ${formatNumber(prompt)}`;
}

/**
 * Создаёт мета-строку под сообщением.
 *
 * При ``skeleton = true`` показывает анимированный скелетон вместо текста —
 * используется, пока запрос ещё выполняется.
 */
function buildMeta(text, skeleton = false) {
  const meta = document.createElement("div");
  meta.className = "msg-meta";
  if (skeleton) {
    meta.classList.add("skeleton");
    meta.innerHTML = '<span class="skeleton-bar"></span>';
  } else {
    meta.textContent = text;
  }
  return meta;
}

/** Подсвечивает JSON-строку простыми span-классами. */
function highlightJson(value) {
  const json = JSON.stringify(value, null, 2);
  return escapeHtml(json).replace(
    /("(?:\\.|[^"\\])*"(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
    (match) => {
      let cls = "json-num";
      if (match.startsWith('"')) {
        cls = match.trimEnd().endsWith(":") ? "json-key" : "json-str";
      } else if (match === "true" || match === "false" || match === "null") {
        cls = "json-bool";
      }
      return `<span class="${cls}">${match}</span>`;
    }
  );
}

/** Открывает модальное окно с логом запроса по его request_id. */
async function openRequestLog(requestId) {
  const modal = $("log-modal");
  const content = $("log-content");
  $("log-title").textContent = `Лог запроса: ${requestId}`;
  content.textContent = "Загрузка...";
  modal.classList.remove("hidden");
  try {
    const data = await api(`/api/requests/${encodeURIComponent(requestId)}`);
    content.innerHTML = highlightJson(data);
  } catch (err) {
    content.textContent = err.message || "Лог запроса не найден";
  }
}

/** Закрывает модальное окно с логом. */
function closeRequestLog() {
  $("log-modal").classList.add("hidden");
}

/** Открывает модальное окно с логом запроса и ответа RAG. */
async function openRagLog(requestId) {
  const modal = $("log-modal");
  const content = $("log-content");
  $("log-title").textContent = `Запрос RAG: ${requestId}`;
  content.textContent = "Загрузка...";
  modal.classList.remove("hidden");
  try {
    const data = await api(`/api/rag/requests/${encodeURIComponent(requestId)}`);
    content.innerHTML = highlightJson(data);
  } catch (err) {
    content.textContent = err.message || "RAG-запрос не найден";
  }
}

/** Добавляет кнопку «Запрос RAG» в мета-строку сообщения. */
function addRagButton(meta, ragRequestId) {
  if (!meta || !ragRequestId) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "log-btn";
  btn.textContent = "🔎 Запрос RAG";
  btn.title = "Открыть запрос и ответ RAG";
  btn.addEventListener("click", () => openRagLog(ragRequestId));
  meta.appendChild(btn);
}

/** Обновляет правую панель со сводной статистикой чата. */
function renderUsagePanel(usage) {
  const data = usage || { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
  $("usage-prompt").textContent = formatNumber(data.prompt_tokens);
  $("usage-completion").textContent = formatNumber(data.completion_tokens);
  $("usage-total").textContent = formatNumber(data.total_tokens);

  const cost = costOf(data);
  $("usage-cost").textContent = cost === null ? "—" : formatCost(cost);

  const note = $("usage-note");
  if (!data.total_tokens) {
    note.textContent = "Данные появятся после первого ответа.";
  } else if (cost === null) {
    note.textContent = "Стоимость не передана API.";
  } else {
    note.textContent = "Стоимость в рублях по данным API.";
  }
}

function showToast(message, type = "") {
  const toast = $("toast");
  toast.textContent = message;
  toast.className = `toast ${type}`;
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => toast.classList.add("hidden"), 4000);
}

function escapeHtml(text) {
  return (text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Минимальный markdown-рендер: код, заголовки, списки, ссылки, выделение. */
function renderMarkdown(text) {
  const blocks = [];
  let src = (text || "").replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = blocks.length;
    blocks.push(`<pre><code class="lang-${escapeHtml(lang)}">${escapeHtml(code.trim())}</code></pre>`);
    return `\u0000BLOCK${idx}\u0000`;
  });

  src = escapeHtml(src);
  src = src.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  src = src.replace(/^###### (.*)$/gm, "<h6>$1</h6>");
  src = src.replace(/^##### (.*)$/gm, "<h5>$1</h5>");
  src = src.replace(/^#### (.*)$/gm, "<h4>$1</h4>");
  src = src.replace(/^### (.*)$/gm, "<h3>$1</h3>");
  src = src.replace(/^## (.*)$/gm, "<h2>$1</h2>");
  src = src.replace(/^# (.*)$/gm, "<h1>$1</h1>");
  src = src.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  src = src.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  src = src.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  src = src.replace(/^\s*[-*] (.*)$/gm, "<li>$1</li>");
  src = src.replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, "<ul>$1</ul>");

  src = src
    .split(/\n{2,}/)
    .map((part) => {
      const trimmed = part.trim();
      if (!trimmed) return "";
      if (/^<(h\d|ul|pre|blockquote)/.test(trimmed) || /^\u0000BLOCK\d+\u0000$/.test(trimmed)) return trimmed;
      return `<p>${trimmed.replace(/\n/g, "<br>")}</p>`;
    })
    .join("");

  return src.replace(/\u0000BLOCK(\d+)\u0000/g, (_, i) => blocks[Number(i)]);
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

/* ---------- Навигация ---------- */

function switchTab(tab) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  document.querySelectorAll(".screen").forEach((screen) => {
    screen.classList.toggle("active", screen.id === `screen-${tab}`);
  });
  if (tab === "chats") loadChats();
  if (tab === "new") loadModels();
  if (tab === "mcp") loadMCPServers();
  if (tab === "logs") loadLogs();
}

/* ---------- Настройки ---------- */

async function loadConfig() {
  try {
    state.config = await api("/api/config");
    $("api-url").value = state.config.api_url || "";
    $("api-key").value = state.config.api_key_masked || "";
    $("default-model").value = state.config.default_model || "";
    $("rag-url").value = state.config.rag_url || "";
    $("rag-collection").value = state.config.rag_collection || "";
    $("rag-strategy").value = state.config.rag_strategy || "";
  } catch (err) {
    showToast(err.message, "err");
  }
}

async function saveConfig(event) {
  event.preventDefault();
  const status = $("config-status");
  status.className = "status";
  status.textContent = "Сохранение...";
  try {
    state.config = await api("/api/config", {
      method: "POST",
      body: JSON.stringify({
        api_url: $("api-url").value,
        api_key: $("api-key").value,
        default_model: $("default-model").value,
      }),
    });
    $("api-key").value = state.config.api_key_masked || "";
    status.className = "status ok";
    status.textContent = "✅ Настройки сохранены";
    showToast("Настройки сохранены", "ok");
  } catch (err) {
    status.className = "status err";
    status.textContent = `❌ Ошибка: ${err.message}`;
  }
}

async function testConnection() {
  const status = $("config-status");
  status.className = "status";
  status.textContent = "Проверка подключения...";
  try {
    const result = await api("/api/config/test", {
      method: "POST",
      body: JSON.stringify({
        api_url: $("api-url").value,
        api_key: $("api-key").value,
        default_model: $("default-model").value,
      }),
    });
    status.className = "status ok";
    status.textContent = `✅ Подключение успешно. Доступно моделей: ${result.models_count}`;
  } catch (err) {
    status.className = "status err";
    status.textContent = `❌ Ошибка: ${err.message}`;
  }
}

/* ---------- MCP-серверы ---------- */

const MCP_DRAFT_ID = "__draft__";

/** Укорачивает адрес для таба (середина заменяется многоточием). */
function shortAddress(address) {
  if (!address) return "Новый сервер";
  if (address.length <= 34) return address;
  const head = address.slice(0, 22);
  const tail = address.slice(-9);
  return `${head}…${tail}`;
}

async function loadMCPServers() {
  try {
    const data = await api("/api/mcp/servers");
    state.mcpServers = data.servers || [];
    renderMCPTabs();
    // Держим текущий таб; если он удалён или его не было — первый сервер
    // или черновик «+ добавить».
    const exists = state.mcpServers.some((s) => s.id === state.mcpCurrentId);
    if (!exists) {
      state.mcpCurrentId = state.mcpServers.length
        ? state.mcpServers[0].id
        : MCP_DRAFT_ID;
    }
    selectMCPTab(state.mcpCurrentId);
  } catch (err) {
    showToast(err.message, "err");
  }
}

function currentMCPServer() {
  return state.mcpServers.find((s) => s.id === state.mcpCurrentId) || null;
}

function renderMCPTabs() {
  const tabs = $("mcp-tabs");
  tabs.innerHTML = "";
  state.mcpServers.forEach((server) => {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = `mcp-tab${server.id === state.mcpCurrentId ? " active" : ""}`;
    tab.title = server.address;
    tab.append(shortAddress(server.address));

    const remove = document.createElement("span");
    remove.className = "mcp-tab-remove";
    remove.textContent = "×";
    remove.title = "Удалить сервер";
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      removeMCPServer(server.id);
    });
    tab.appendChild(remove);
    tab.addEventListener("click", () => selectMCPTab(server.id));
    tabs.appendChild(tab);
  });

  const add = document.createElement("button");
  add.type = "button";
  add.className = `mcp-tab mcp-tab-add${state.mcpCurrentId === MCP_DRAFT_ID ? " active" : ""}`;
  add.textContent = "+ добавить";
  add.addEventListener("click", () => selectMCPTab(MCP_DRAFT_ID));
  tabs.appendChild(add);
}

function selectMCPTab(serverId) {
  state.mcpCurrentId = serverId;
  renderMCPTabs();
  const server = currentMCPServer();
  $("mcp-address").value = server ? server.address : "";
  const status = $("mcp-status");
  status.className = "status";
  status.textContent = "";
  renderMCPTools(server ? server.tools : null);
}

function removeMCPServer(serverId) {
  const server = state.mcpServers.find((s) => s.id === serverId);
  if (!server) return;
  if (!confirm(`Удалить MCP-сервер «${server.address}»?`)) return;
  api(`/api/mcp/servers/${encodeURIComponent(serverId)}`, { method: "DELETE" })
    .then(() => {
      state.mcpCurrentId = null;
      return loadMCPServers();
    })
    .then(() => showToast("Сервер удалён", "ok"))
    .catch((err) => showToast(err.message, "err"));
}

/** Возвращает адрес из поля или показывает ошибку и возвращает null. */
function mcpAddressOrWarn() {
  const status = $("mcp-status");
  const address = $("mcp-address").value.trim();
  if (!address) {
    status.className = "status err";
    status.textContent = "❌ Укажите адрес MCP-сервера.";
    return null;
  }
  return address;
}

/** Возвращает ID текущего сервера; для черновика — null (создать новый). */
function mcpServerIdOrNull() {
  return state.mcpCurrentId === MCP_DRAFT_ID ? null : state.mcpCurrentId;
}

async function saveMCPServer() {
  const status = $("mcp-status");
  status.className = "status";
  status.textContent = "Сохранение...";
  const address = mcpAddressOrWarn();
  if (!address) return;
  try {
    const result = await api("/api/mcp/servers", {
      method: "POST",
      body: JSON.stringify({ address, server_id: mcpServerIdOrNull() }),
    });
    state.mcpCurrentId = result.server.id;
    await loadMCPServers();
    status.className = "status ok";
    status.textContent = `✅ Сервер сохранён: ${shortAddress(address)}`;
    showToast("Сервер сохранён", "ok");
  } catch (err) {
    status.className = "status err";
    status.textContent = `❌ Ошибка: ${err.message}`;
  }
}

async function checkMCP() {
  const status = $("mcp-status");
  status.className = "status";
  status.textContent = "Проверка подключения...";
  const address = mcpAddressOrWarn();
  if (!address) return;
  try {
    const result = await api("/api/mcp/check", {
      method: "POST",
      body: JSON.stringify({ address, server_id: mcpServerIdOrNull() }),
    });
    state.mcpCurrentId = result.server.id;
    await loadMCPServers();
    status.className = "status ok";
    const info = result.server_info || {};
    const name = info.name || info.serverInfo?.name || "";
    const version = info.version || info.serverInfo?.version || "";
    const extra = [name, version].filter(Boolean).join(" · ");
    status.textContent = extra
      ? `✅ Подключение установлено: ${extra}`
      : "✅ Подключение установлено";
  } catch (err) {
    status.className = "status err";
    status.textContent = `❌ Ошибка: ${err.message}`;
  }
}

function formatToolSchema(schema) {
  try {
    return JSON.stringify(schema || {}, null, 2);
  } catch (err) {
    return String(schema || "");
  }
}

function renderMCPTools(tools) {
  const section = $("mcp-tools-section");
  const body = $("mcp-tools-body");
  body.innerHTML = "";

  const server = currentMCPServer();
  if (!tools || !tools.length) {
    section.classList.add("hidden");
    return;
  }

  $("mcp-tools-title").textContent = server
    ? `Инструменты MCP-сервера: ${server.address}`
    : "Инструменты MCP-сервера";

  tools.forEach((tool, index) => {
    const row = document.createElement("tr");
    const description = tool.description || "";
    const num = document.createElement("td");
    num.className = "col-num";
    num.textContent = String(index + 1);
    const name = document.createElement("td");
    name.className = "col-name";
    name.textContent = tool.name || "";
    const desc = document.createElement("td");
    desc.textContent = description;
    const schema = document.createElement("td");
    const pre = document.createElement("pre");
    pre.className = "schema-json";
    pre.innerHTML = highlightJson(tool.input_schema || {});
    schema.appendChild(pre);
    row.appendChild(num);
    row.appendChild(name);
    row.appendChild(desc);
    row.appendChild(schema);
    body.appendChild(row);
  });
  section.classList.remove("hidden");
}

async function fetchMCPTools() {
  const status = $("mcp-status");
  status.className = "status";
  status.textContent = "Запрос инструментов...";
  const address = mcpAddressOrWarn();
  if (!address) return;
  try {
    const result = await api("/api/mcp/tools", {
      method: "POST",
      body: JSON.stringify({ address, server_id: mcpServerIdOrNull() }),
    });
    state.mcpCurrentId = result.server.id;
    await loadMCPServers();
    renderMCPTools(result.tools || []);
    status.className = "status ok";
    status.textContent = `✅ Получено инструментов: ${result.tools.length}`;
  } catch (err) {
    $("mcp-tools-section").classList.add("hidden");
    status.className = "status err";
    status.textContent = `❌ Ошибка: ${err.message}`;
  }
}

/* ---------- Логи ---------- */

async function loadLogs() {
  try {
    const data = await api("/api/logs?limit=200");
    state.logs = data.logs || [];
    renderLogs();
  } catch (err) {
    showToast(err.message, "err");
  }
}

function formatDuration(ms) {
  if (ms === null || ms === undefined) return "—";
  const value = Number(ms);
  if (!Number.isFinite(value)) return "—";
  if (value < 1000) return `${value} мс`;
  return `${(value / 1000).toFixed(2)} с`;
}

function renderLogs() {
  const query = ($("log-search").value || "").toLowerCase().trim();
  const body = $("logs-body");
  body.innerHTML = "";

  const logs = state.logs.filter((log) => {
    if (!query) return true;
    const haystack = [
      log.request_id,
      log.chat_id,
      log.model,
      log.api_url,
      log.error,
    ].filter(Boolean).join(" ").toLowerCase();
    return haystack.includes(query);
  });

  if (!logs.length) {
    body.innerHTML = '<tr><td colspan="7" class="empty">Логов пока нет. Отправьте сообщение в чат — запрос к модели попадёт сюда.</td></tr>';
    return;
  }

  logs.forEach((log) => {
    const row = document.createElement("tr");

    const time = document.createElement("td");
    time.className = "col-time";
    const date = log.timestamp ? new Date(log.timestamp).toLocaleString("ru-RU") : "—";
    time.textContent = date;

    const chat = document.createElement("td");
    chat.className = "col-chat";
    chat.textContent = log.chat_id ? log.chat_id.slice(0, 8) : "—";

    const model = document.createElement("td");
    model.className = "col-model";
    model.textContent = log.model || "—";

    const status = document.createElement("td");
    status.className = "col-status";
    let statusText = "—";
    if (log.error) {
      statusText = "ошибка";
      status.classList.add("log-status-err");
    } else if (log.status_code) {
      statusText = String(log.status_code);
      status.classList.add(log.status_code < 400 ? "log-status-ok" : "log-status-err");
    }
    status.textContent = statusText;

    const duration = document.createElement("td");
    duration.className = "col-duration";
    duration.textContent = formatDuration(log.duration_ms);

    const id = document.createElement("td");
    id.className = "col-id";
    id.textContent = log.request_id || "";
    id.title = log.error || "";

    const open = document.createElement("td");
    open.className = "col-open";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "log-btn";
    btn.textContent = "🔍 Открыть";
    btn.addEventListener("click", () => openRequestLog(log.request_id));
    open.appendChild(btn);

    row.appendChild(time);
    row.appendChild(chat);
    row.appendChild(model);
    row.appendChild(status);
    row.appendChild(duration);
    row.appendChild(id);
    row.appendChild(open);
    body.appendChild(row);
  });
}

/* ---------- RAG-сервер ---------- */

function renderRagStrategies() {
  const collectionSelect = $("rag-collection");
  const strategySelect = $("rag-strategy");
  strategySelect.innerHTML = "";
  const option = collectionSelect.options[collectionSelect.selectedIndex];
  let strategies = [];
  if (option && option.dataset.strategies) {
    try {
      strategies = JSON.parse(option.dataset.strategies) || [];
    } catch (err) { /* ignore */ }
  }
  strategies.forEach((strategy) => {
    const item = document.createElement("option");
    item.value = strategy;
    item.textContent = strategy;
    strategySelect.appendChild(item);
  });
  // Возвращаем сохранённую стратегию, если она доступна для этой коллекции.
  const saved = state.config.rag_strategy || "";
  if (saved && strategies.includes(saved)) {
    strategySelect.value = saved;
  }
  strategySelect.disabled = !strategies.length;
}

async function checkRAG() {
  const status = $("rag-status");
  status.className = "status";
  status.textContent = "Проверка подключения...";
  const ragUrl = $("rag-url").value.trim();
  if (!ragUrl) {
    status.className = "status err";
    status.textContent = "❌ Укажите адрес RAG-сервера.";
    return;
  }
  try {
    const result = await api("/api/rag/check", {
      method: "POST",
      body: JSON.stringify({ rag_url: ragUrl }),
    });
    const select = $("rag-collection");
    select.innerHTML = "";
    const collections = result.collections || [];
    collections.forEach((collection) => {
      const option = document.createElement("option");
      option.value = collection.id;
      option.textContent = `${collection.name} (${collection.id})`;
      option.dataset.strategies = JSON.stringify(collection.strategies || []);
      select.appendChild(option);
    });
    if (!collections.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "Коллекции не найдены";
      select.appendChild(option);
    }
    // Возвращаем сохранённую коллекцию, если она ещё существует на сервере.
    const saved = state.config.rag_collection || "";
    if (saved && collections.some((c) => c.id === saved)) {
      select.value = saved;
    }
    select.disabled = false;
    renderRagStrategies();
    $("rag-save").disabled = false;
    status.className = "status ok";
    status.textContent = `✅ Подключение установлено. Коллекций: ${collections.length}`;
  } catch (err) {
    $("rag-collection").disabled = true;
    $("rag-save").disabled = true;
    status.className = "status err";
    status.textContent = `❌ Ошибка: ${err.message}`;
  }
}

async function saveRAG() {
  const status = $("rag-status");
  status.className = "status";
  status.textContent = "Сохранение...";
  try {
    state.config = await api("/api/rag/config", {
      method: "POST",
      body: JSON.stringify({
        rag_url: $("rag-url").value.trim(),
        rag_collection: $("rag-collection").value,
        rag_strategy: $("rag-strategy").value,
      }),
    });
    status.className = "status ok";
    status.textContent = "✅ RAG-настройки сохранены";
    showToast("RAG-настройки сохранены", "ok");
  } catch (err) {
    status.className = "status err";
    status.textContent = `❌ Ошибка: ${err.message}`;
  }
}

/* ---------- Модели ---------- */

async function loadModels() {
  const status = $("new-status");
  status.className = "status";
  status.textContent = "Загрузка моделей...";
  try {
    const data = await api("/api/models");
    state.models = data.models || [];
    renderModels();
    status.textContent = state.models.length
      ? `Доступно моделей: ${state.models.length}`
      : "Список моделей пуст.";
  } catch (err) {
    state.models = [];
    renderModels();
    status.className = "status err";
    status.textContent = `❌ ${err.message}`;
  }
}

function renderModels() {
  const query = ($("model-search").value || "").toLowerCase().trim();
  const select = $("model-select");
  const filtered = state.models.filter((m) => m.id.toLowerCase().includes(query));
  select.innerHTML = "";
  filtered.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.id;
    select.appendChild(option);
  });
  const preferred = state.config.default_model;
  if (preferred && filtered.some((m) => m.id === preferred)) {
    select.value = preferred;
  }
}

async function createChat() {
  const model = $("model-select").value;
  if (!model) {
    showToast("Выберите модель", "err");
    return;
  }
  try {
    const chat = await api("/api/chats", {
      method: "POST",
      body: JSON.stringify({ model }),
    });
    await openChat(chat.id);
  } catch (err) {
    showToast(err.message, "err");
  }
}

/* ---------- Список чатов ---------- */

async function loadChats() {
  try {
    const data = await api("/api/chats");
    state.chats = data.chats || [];
    renderChats();
  } catch (err) {
    showToast(err.message, "err");
  }
}

function renderChats() {
  const query = ($("chat-search").value || "").toLowerCase().trim();
  const list = $("chat-list");
  const chats = state.chats.filter((c) => (c.title || "").toLowerCase().includes(query));
  list.innerHTML = "";

  if (!chats.length) {
    list.innerHTML = '<div class="empty">Чатов пока нет. Создайте новый через ➕.</div>';
    return;
  }

  chats.forEach((chat) => {
    const item = document.createElement("div");
    item.className = "chat-item";
    const date = chat.created_at ? new Date(chat.created_at).toLocaleString("ru-RU") : "";
    item.innerHTML = `
      <div class="chat-item-main">
        <div class="chat-item-title">${escapeHtml(chat.title)}</div>
        <div class="chat-item-meta">${escapeHtml(chat.model)} · ${date} · сообщений: ${chat.message_count}</div>
      </div>
      <button class="icon-btn" title="Удалить">🗑</button>
    `;
    item.addEventListener("click", () => openChat(chat.id));
    item.querySelector(".icon-btn").addEventListener("click", async (event) => {
      event.stopPropagation();
      if (!confirm(`Удалить чат «${chat.title}»?`)) return;
      try {
        await api(`/api/chats/${chat.id}`, { method: "DELETE" });
        if (state.currentChat && state.currentChat.id === chat.id) {
          state.currentChat = null;
        }
        await loadChats();
        showToast("Чат удалён", "ok");
      } catch (err) {
        showToast(err.message, "err");
      }
    });
    list.appendChild(item);
  });
}

/* ---------- Диалог ---------- */

async function openChat(chatId, silent = false) {
  try {
    const chat = await api(`/api/chats/${chatId}`);
    state.currentChat = chat;
    $("chat-title").textContent = chat.title || "Чат";
    $("chat-model").textContent = chat.model || "";
    renderMessages(chat.messages || []);
    renderUsagePanel(chat.usage);
    switchTab("chat");
    // Запоминаем чат, чтобы вернуться в него после перехода на дашборд памяти.
    try {
      localStorage.setItem("lastChatId", chatId);
    } catch (err) { /* ignore */ }
    $("message-input").focus();
    return true;
  } catch (err) {
    if (!silent) showToast(err.message, "err");
    return false;
  }
}

function renderMessages(messages) {
  const container = $("messages");
  container.innerHTML = "";
  if (!messages.length) {
    container.innerHTML = '<div class="empty">Начните диалог — напишите первое сообщение.</div>';
    return;
  }
  messages.forEach((message) =>
    container.appendChild(
      buildMessage(
        message.role,
        message.content,
        message.usage,
        message.request_id,
        message.rag_request_id
      )
    )
  );
  container.scrollTop = container.scrollHeight;
}

function buildMessage(role, content, usage, requestId, ragRequestId) {
  const wrapper = document.createElement("div");
  wrapper.className = `msg ${role}`;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "🧑" : "🤖";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = renderMarkdown(content);
  wrapper.appendChild(avatar);
  wrapper.appendChild(bubble);
  if (usage || requestId || ragRequestId) {
    const meta = buildMeta("");
    if (usage) {
      const text = role === "user" ? promptMetaText(usage) : usageMetaText(usage);
      if (text) meta.appendChild(document.createTextNode(text));
    }
    if (requestId) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "log-btn";
      btn.textContent = "🔍 Посмотреть запрос";
      btn.addEventListener("click", () => openRequestLog(requestId));
      meta.appendChild(btn);
    }
    if (ragRequestId) addRagButton(meta, ragRequestId);
    bubble.appendChild(meta);
  }
  return wrapper;
}

async function sendMessage() {
  if (state.streaming || !state.currentChat) return;
  const input = $("message-input");
  const content = input.value.trim();
  if (!content) return;
  const useRag = $("rag-enabled").checked;

  const container = $("messages");
  if (container.querySelector(".empty")) container.innerHTML = "";

  const userBubble = buildMessage("user", content);
  const userMeta = buildMeta("", true);
  userBubble.querySelector(".bubble").appendChild(userMeta);
  container.appendChild(userBubble);
  input.value = "";
  input.style.height = "auto";
  container.scrollTop = container.scrollHeight;

  const assistantBubble = buildMessage("assistant", "");
  assistantBubble.querySelector(".bubble").classList.add("cursor");
  container.appendChild(assistantBubble);
  container.scrollTop = container.scrollHeight;

  setStreaming(true);
  state.controller = new AbortController();
  let lastUsage = null;
  let requestId = null;

  try {
    const response = await fetch(`/api/chats/${state.currentChat.id}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, use_rag: useRag }),
      signal: state.controller.signal,
    });

    if (!response.ok) {
      const text = await response.text();
      let detail = `Ошибка ${response.status}`;
      try {
        detail = JSON.parse(text).detail || detail;
      } catch (err) { /* ignore */ }
      throw new Error(detail);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let accumulated = "";
    const bubble = assistantBubble.querySelector(".bubble");

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop();

      for (const part of parts) {
        const eventMatch = part.match(/^event: (.+)$/m);
        const dataMatch = part.match(/^data: (.+)$/m);
        if (!eventMatch || !dataMatch) continue;
        const event = eventMatch[1].trim();
        let payload = {};
        try {
          payload = JSON.parse(dataMatch[1]);
        } catch (err) {
          continue;
        }

        if (event === "delta") {
          accumulated += payload.content || "";
          bubble.innerHTML = renderMarkdown(accumulated);
          container.scrollTop = container.scrollHeight;
        } else if (event === "start") {
          requestId = payload.request_id || null;
        } else if (event === "usage") {
          lastUsage = payload.usage || null;
        } else if (event === "tools") {
          const names = payload.tools || [];
          if (names.length) {
            showToast(`🔧 Инструменты: ${names.join(", ")}`);
          }
        } else if (event === "rag") {
          if (payload.used && payload.chunks) {
            showToast(`🔎 RAG: найдено чанков: ${payload.chunks}`);
          } else if (payload.error) {
            showToast(`🔎 RAG: ${payload.error}`, "err");
          }
        } else if (event === "error") {
          bubble.classList.remove("cursor");
          bubble.innerHTML = `<p style="color:var(--danger)">❌ ${escapeHtml(payload.message)}</p>`;
          showToast(payload.message, "err");
        } else if (event === "done") {
          bubble.classList.remove("cursor");
          if (!accumulated) bubble.innerHTML = "<p>(пустой ответ)</p>";
          if (payload.usage) lastUsage = payload.usage;
          if (payload.request_id) requestId = payload.request_id;
          if (lastUsage) {
            bubble.appendChild(buildMeta(usageMetaText(lastUsage)));
          }
          if (lastUsage) {
            userMeta.classList.remove("skeleton");
            userMeta.textContent = promptMetaText(lastUsage);
          }
          if (requestId) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "log-btn";
            btn.textContent = "🔍 Посмотреть запрос";
            btn.addEventListener("click", () => openRequestLog(requestId));
            userMeta.appendChild(btn);
            const assistantMeta = bubble.querySelector(".msg-meta");
            if (assistantMeta) assistantMeta.appendChild(btn.cloneNode(true));
          }
          if (payload.rag_request_id) addRagButton(userMeta, payload.rag_request_id);
          if (payload.chat_usage) renderUsagePanel(payload.chat_usage);
        }
      }
    }
    bubble.classList.remove("cursor");
    await loadChats();
  } catch (err) {
    const bubble = assistantBubble.querySelector(".bubble");
    bubble.classList.remove("cursor");
    userMeta.classList.remove("skeleton");
    userMeta.textContent = "Токены запроса недоступны";
    if (err.name === "AbortError") {
      bubble.innerHTML += '<p style="color:var(--text-dim)">⏹ Генерация остановлена</p>';
    } else {
      bubble.innerHTML = `<p style="color:var(--danger)">❌ ${escapeHtml(err.message)}</p>`;
      showToast(err.message, "err");
    }
  } finally {
    setStreaming(false);
    state.controller = null;
  }
}

function setStreaming(value) {
  state.streaming = value;
  $("send-btn").classList.toggle("hidden", value);
  $("stop-btn").classList.toggle("hidden", !value);
}

function stopStreaming() {
  if (state.controller) state.controller.abort();
}

async function clearChat() {
  if (!state.currentChat) return;
  if (!confirm("Очистить историю сообщений?")) return;
  try {
    await api(`/api/chats/${state.currentChat.id}/clear`, { method: "POST" });
    state.currentChat.messages = [];
    renderMessages([]);
    renderUsagePanel(null);
    await loadChats();
  } catch (err) {
    showToast(err.message, "err");
  }
}

async function exportChat() {
  if (!state.currentChat) return;
  try {
    const data = await api(`/api/chats/${state.currentChat.id}/export`);
    const blob = new Blob([data.markdown], { type: "text/markdown;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${state.currentChat.title || "chat"}.md`;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (err) {
    showToast(err.message, "err");
  }
}

/* ---------- Инициализация ---------- */

function bindEvents() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  $("config-form").addEventListener("submit", saveConfig);
  $("test-connection").addEventListener("click", testConnection);
  $("toggle-key").addEventListener("click", () => {
    const input = $("api-key");
    const isPassword = input.type === "password";
    input.type = isPassword ? "text" : "password";
    $("toggle-key").textContent = isPassword ? "Скрыть" : "Показать";
  });

  $("mcp-save").addEventListener("click", saveMCPServer);
  $("rag-check").addEventListener("click", checkRAG);
  $("rag-save").addEventListener("click", saveRAG);
  $("rag-collection").addEventListener("change", renderRagStrategies);
  $("mcp-check").addEventListener("click", checkMCP);
  $("mcp-tools").addEventListener("click", fetchMCPTools);

  $("reload-logs").addEventListener("click", loadLogs);
  $("log-search").addEventListener("input", renderLogs);

  $("model-search").addEventListener("input", renderModels);
  $("reload-models").addEventListener("click", loadModels);
  $("create-chat").addEventListener("click", createChat);

  $("chat-search").addEventListener("input", renderChats);

  $("send-btn").addEventListener("click", sendMessage);
  $("stop-btn").addEventListener("click", stopStreaming);
  $("clear-chat").addEventListener("click", clearChat);
  $("export-chat").addEventListener("click", exportChat);

  $("log-close").addEventListener("click", closeRequestLog);
  $("log-backdrop").addEventListener("click", closeRequestLog);
  $("log-copy").addEventListener("click", async () => {
    const text = $("log-content").textContent || "";
    try {
      await navigator.clipboard.writeText(text);
      showToast("Лог скопирован", "ok");
    } catch (err) {
      showToast("Не удалось скопировать", "err");
    }
  });

  const input = $("message-input");
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
  });

  $("rag-enabled").addEventListener("change", () => {
    try {
      localStorage.setItem("ragEnabled", $("rag-enabled").checked ? "1" : "0");
    } catch (err) { /* ignore */ }
  });

  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      switchTab("chats");
      $("chat-search").focus();
    }
  });
}

async function init() {
  bindEvents();
  // Восстанавливаем галку «Использовать RAG» из localStorage.
  try {
    $("rag-enabled").checked = localStorage.getItem("ragEnabled") === "1";
  } catch (err) { /* ignore */ }
  await loadConfig();
  // Возвращаемся в последний открытый чат (например, после дашборда памяти).
  let lastChatId = null;
  try {
    lastChatId = localStorage.getItem("lastChatId");
  } catch (err) { /* ignore */ }
  if (lastChatId) {
    const restored = await openChat(lastChatId, true);
    if (restored) return;
    // Чат удалён — забываем его, чтобы не показывать ошибку при каждом входе.
    try {
      localStorage.removeItem("lastChatId");
    } catch (err) { /* ignore */ }
  }
  switchTab("settings");
}

document.addEventListener("DOMContentLoaded", init);
