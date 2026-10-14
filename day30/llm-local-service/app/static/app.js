"use strict";

(() => {
  const state = {
    page: "overview",
    apiKey: "",
    settings: null,
    logOffset: 0,
    logLimit: 50,
    logTotal: 0,
    logSearchTimer: null,
    lastProbe: null,
  };

  const $ = (id) => document.getElementById(id);
  const STATUS_TEXT = { ok: "Успешно", error: "Ошибка", rejected: "Отклонён" };
  const PAGE_TITLES = { overview: "Обзор", settings: "Модель и настройки", logs: "Журнал запросов" };

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    if (state.apiKey) headers.set("X-API-Key", state.apiKey);
    let response;
    try {
      response = await fetch(path, { ...options, headers, cache: "no-store" });
    } catch (error) {
      throw new Error("Не удалось подключиться к API. Проверьте, что сервис запущен.");
    }
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      const detail = payload?.error;
      if (response.status === 401) {
        throw new Error("Требуется API key: введите ключ в верхней панели и нажмите «Применить».");
      }
      throw new Error(detail?.message || `Ошибка HTTP ${response.status}`);
    }
    return payload;
  }

  function toast(message, kind = "", duration = 3600) {
    const node = document.createElement("div");
    node.className = `toast ${kind}`.trim();
    node.textContent = message;
    $("toast-region").append(node);
    window.setTimeout(() => node.remove(), duration);
  }

  function showInline(id, message, isError = false) {
    const node = $(id);
    node.textContent = message || "";
    node.classList.toggle("error", Boolean(isError));
  }

  function setServicePill(isOnline, text) {
    const pill = $("service-pill");
    pill.className = `status-pill ${isOnline ? "status-online" : "status-offline"}`;
    pill.querySelector("span").textContent = text;
  }

  function setHealthRow(prefix, ok, detail, label) {
    $(`${prefix}-indicator`).className = `health-indicator ${ok ? "ok" : "bad"}`;
    $(`${prefix}-detail`).textContent = detail;
    const status = $(`${prefix}-health-label`);
    status.textContent = label;
    status.className = `health-label ${ok ? "good" : "bad"}`;
  }

  function navigate(page) {
    if (!PAGE_TITLES[page]) return;
    state.page = page;
    document.querySelectorAll(".page").forEach((node) => {
      const active = node.id === `page-${page}`;
      node.classList.toggle("active", active);
      node.hidden = !active;
    });
    document.querySelectorAll(".nav-item").forEach((node) => {
      node.classList.toggle("active", node.dataset.page === page);
    });
    $("page-breadcrumb").textContent = PAGE_TITLES[page];
    history.replaceState(null, "", `#${page}`);
    if (page === "settings") loadSettings();
    if (page === "logs") loadLogs(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function setText(id, value, fallback = "—") {
    $(id).textContent = value === null || value === undefined || value === "" ? fallback : String(value);
  }

  async function refreshOverview() {
    try {
      const [live, health, stats, logs, settings] = await Promise.all([
        api("/health/live"),
        api("/health"),
        api("/api/admin/logs/stats"),
        api("/api/admin/logs?limit=5&offset=0"),
        api("/api/admin/settings"),
      ]);
      const ollamaOk = health.ollama === "ok" && health.model_available;
      setServicePill(ollamaOk, ollamaOk ? "Сервис онлайн" : "Проблема модели");
      setText("stat-api", live.status === "ok" ? "Работает" : "Недоступен");
      setText("stat-api-sub", `FastAPI · v${live.version}`);
      setText("stat-ollama", health.ollama === "ok" ? "Подключена" : "Недоступна");
      setText("stat-ollama-sub", health.detail);
      setText("stat-model", health.model);
      setText("stat-model-sub", health.model_available ? "Установлена в Ollama" : "Модель не найдена");
      setText("stat-logs", stats.enabled ? stats.files : "Выкл.");
      setText("stat-logs-sub", stats.enabled ? `${stats.buffered} в памяти · максимум ${stats.max_entries}` : "Запись отключена");
      setText("nav-log-count", stats.files);
      $("sidebar-port").textContent = settings.read_only.port;
      setHealthRow("api", true, `Процесс активен · ${settings.read_only.host}:${settings.read_only.port}`, "OK");
      setHealthRow("ollama", health.ollama === "ok", health.detail, health.ollama === "ok" ? "OK" : "Ошибка");
      setHealthRow("model", health.model_available, health.model, health.model_available ? "Готова" : "Нет");
      setText("ollama-url", health.ollama_url);
      renderRecent(logs.items);
      if (state.page === "settings") fillSettings(settings);
      if (state.page === "logs") {
        setText("logs-storage", `${stats.files} JSON-файлов · ${stats.directory}`);
      }
    } catch (error) {
      if (/API key/i.test(error.message)) {
        setServicePill(false, "Нужен API key");
        toast(error.message, "error", 6000);
      } else {
        setServicePill(false, "API недоступен");
        setText("stat-api", "Недоступен");
        toast(error.message, "error");
      }
    }
  }

  function renderRecent(items) {
    const list = $("overview-recent");
    list.replaceChildren();
    if (!items || items.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state compact";
      empty.textContent = "Запросов пока нет. Отправьте запрос через POST /chat.";
      list.append(empty);
      return;
    }
    items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "recent-item";
      const main = document.createElement("div");
      main.className = "recent-main";
      const id = document.createElement("strong");
      id.textContent = item.id.slice(0, 12);
      const stamp = document.createElement("small");
      stamp.textContent = formatDate(item.started_at);
      main.append(id, stamp);
      const model = document.createElement("span");
      model.className = "recent-model";
      model.textContent = item.model;
      const status = makeStatusChip(item.status, item.http_status);
      const duration = document.createElement("span");
      duration.className = "recent-duration";
      duration.textContent = formatDuration(item.duration_ms);
      row.append(main, model, status, duration);
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      row.addEventListener("click", () => openLogDetail(item.id));
      list.append(row);
    });
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  }

  function formatDuration(value) {
    if (value === null || value === undefined) return "—";
    return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(2)} s`;
  }

  function makeStatusChip(status, httpStatus) {
    const chip = document.createElement("span");
    chip.className = `status-chip ${status || "rejected"}`;
    chip.textContent = `${STATUS_TEXT[status] || status || "—"}${httpStatus ? ` · ${httpStatus}` : ""}`;
    return chip;
  }

  async function loadSettings() {
    try {
      const result = await api("/api/admin/settings");
      fillSettings(result);
      await loadModels(result.settings.ollama_base_url, result.settings.ollama_model);
    } catch (error) {
      toast(error.message, "error", 6000);
    }
  }

  function fillSettings(payload) {
    if (!payload?.settings) return;
    state.settings = payload;
    const s = payload.settings;
    const values = {
      "field-base-url": s.ollama_base_url,
      "field-model": s.ollama_model,
      "field-timeout": s.ollama_timeout,
      "field-connect-timeout": s.ollama_connect_timeout,
      "field-num-ctx": s.ollama_num_ctx,
      "field-concurrency": s.ollama_max_concurrency,
      "field-message-chars": s.max_message_chars,
      "field-history": s.max_history_messages,
      "field-context": s.max_context_tokens,
      "field-output": s.max_output_tokens,
      "field-tolerance": s.context_token_tolerance,
      "field-rate-limit": s.rate_limit,
      "field-log-enabled": s.request_log_enabled,
    };
    Object.entries(values).forEach(([id, value]) => {
      if (id === "field-log-enabled") $(id).checked = Boolean(value);
      else $(id).value = value;
    });
    setText("read-host", payload.read_only.host);
    setText("read-port", payload.read_only.port);
    setText("read-api-key", payload.read_only.api_key_configured ? "Настроен · скрыт" : "Не задан");
    setText("log-directory", payload.read_only.request_log_dir);
    setText("log-directory-notice", payload.read_only.request_log_dir);
    setText("log-retention", `${payload.read_only.request_log_max_entries} файлов`);
    $("modified-badge").hidden = !payload.modified;
    updateBudgetPreview();
  }

  async function loadModels(baseUrl, modelName) {
    const select = $("field-model-select");
    select.replaceChildren(new Option("Проверка списка моделей…", ""));
    try {
      const response = await api("/api/admin/models");
      select.replaceChildren();
      if (!response.installed_models.length) select.add(new Option("Нет установленных моделей", ""));
      response.installed_models.forEach((name) => select.add(new Option(name, name)));
      if (modelName && !response.installed_models.includes(modelName)) {
        select.add(new Option(`${modelName} · текущая`, modelName));
      }
      select.value = modelName || "";
      setProbeBadge(response.model_available, response.detail);
    } catch (error) {
      select.replaceChildren(new Option("Список недоступен — введите имя вручную", ""));
      setProbeBadge(false, error.message);
    }
  }

  function setProbeBadge(ok, message) {
    const badge = $("model-check-badge");
    badge.textContent = ok ? "Подключена" : "Не проверена";
    badge.className = `status-label ${ok ? "good" : "bad"}`;
    if (message) showInline("probe-message", message, !ok);
  }

  function collectSettings() {
    return {
      ollama_base_url: $("field-base-url").value.trim(),
      ollama_model: $("field-model").value.trim(),
      ollama_timeout: Number($("field-timeout").value),
      ollama_connect_timeout: Number($("field-connect-timeout").value),
      ollama_num_ctx: Number($("field-num-ctx").value),
      ollama_max_concurrency: Number($("field-concurrency").value),
      max_message_chars: Number($("field-message-chars").value),
      max_history_messages: Number($("field-history").value),
      max_context_tokens: Number($("field-context").value),
      max_output_tokens: Number($("field-output").value),
      context_token_tolerance: Number($("field-tolerance").value),
      rate_limit: $("field-rate-limit").value.trim(),
      request_log_enabled: $("field-log-enabled").checked,
    };
  }

  function updateBudgetPreview() {
    const context = Number($("field-context").value);
    const output = Number($("field-output").value);
    const numCtx = Number($("field-num-ctx").value);
    const tolerance = Number($("field-tolerance").value);
    const evaluationBudget = Math.floor(context * (1 - tolerance));
    const valid = context + output <= numCtx;
    const preview = $("context-budget-preview");
    preview.classList.toggle("invalid", !valid);
    preview.textContent = valid
      ? `Вход: максимум ${context} токенов · оценочный бюджет ${evaluationBudget} · ответ: ${output} · окно Ollama: ${numCtx}`
      : `Ошибка: MAX_CONTEXT_TOKENS (${context}) + MAX_OUTPUT_TOKENS (${output}) превышает OLLAMA_NUM_CTX (${numCtx}).`;
    $("save-settings").disabled = !valid;
  }

  async function probeCurrentForm() {
    const button = $("probe-button");
    button.disabled = true;
    showInline("probe-message", "Проверяю Ollama…");
    try {
      const data = await api("/api/admin/models/probe", {
        method: "POST",
        body: JSON.stringify({
          ollama_base_url: $("field-base-url").value.trim(),
          ollama_model: $("field-model").value.trim(),
        }),
      });
      if (data.reachable) {
        const select = $("field-model-select");
        const existing = [...select.options].some((option) => option.value === data.current_model);
        if (!existing) select.add(new Option(data.current_model, data.current_model));
        showInline("probe-message", `${data.detail} Установлено моделей: ${data.installed_models.length}.`, !data.model_available);
      } else {
        showInline("probe-message", data.detail, true);
      }
      setProbeBadge(data.model_available, data.detail);
    } catch (error) {
      showInline("probe-message", error.message, true);
      setProbeBadge(false, error.message);
    } finally {
      button.disabled = false;
    }
  }

  async function saveSettings(event) {
    event.preventDefault();
    const data = collectSettings();
    if (data.ollama_num_ctx < data.max_context_tokens + data.max_output_tokens) {
      toast("Контекстное окно должно включать входной контекст и резерв ответа.", "error");
      return;
    }
    const button = $("save-settings");
    button.disabled = true;
    showInline("settings-message", "Применяю…");
    try {
      const result = await api("/api/admin/settings", { method: "PATCH", body: JSON.stringify(data) });
      fillSettings(result);
      showInline("settings-message", "Настройки применены к новым запросам.");
      toast("Настройки модели обновлены без перезапуска.", "success");
      await refreshOverview();
      await loadModels(result.settings.ollama_base_url, result.settings.ollama_model);
    } catch (error) {
      showInline("settings-message", error.message, true);
      toast(error.message, "error", 6000);
    } finally {
      button.disabled = false;
      updateBudgetPreview();
    }
  }

  async function resetSettings() {
    if (!window.confirm("Сбросить runtime-настройки к значениям из .env?")) return;
    try {
      const result = await api("/api/admin/settings/reset", { method: "POST" });
      fillSettings(result);
      showInline("settings-message", "Настройки сброшены к .env.");
      toast("Runtime-настройки сброшены.", "success");
      await refreshOverview();
      await loadModels(result.settings.ollama_base_url, result.settings.ollama_model);
    } catch (error) {
      showInline("settings-message", error.message, true);
      toast(error.message, "error");
    }
  }

  function logQuery() {
    const params = new URLSearchParams({ limit: String(state.logLimit), offset: String(state.logOffset) });
    const status = $("log-status-filter").value;
    const model = $("log-model-filter").value;
    const search = $("log-search").value.trim();
    if (status) params.set("status", status);
    if (model) params.set("model", model);
    if (search) params.set("search", search);
    return params.toString();
  }

  async function loadLogs(resetOffset = false) {
    if (resetOffset) state.logOffset = 0;
    try {
      const [page, stats] = await Promise.all([
        api(`/api/admin/logs?${logQuery()}`),
        api("/api/admin/logs/stats"),
      ]);
      state.logTotal = page.total;
      setText("logs-count", `${page.total} записей по текущему фильтру`);
      setText("logs-storage", stats.enabled ? `${stats.files} JSON-файлов · ${stats.directory} · ${stats.write_errors} ошибок записи` : "Запись логов выключена");
      setText("nav-log-count", stats.files);
      $("logs-prev").disabled = state.logOffset <= 0;
      $("logs-next").disabled = state.logOffset + state.logLimit >= page.total;
      const first = page.total ? state.logOffset + 1 : 0;
      const last = Math.min(state.logOffset + state.logLimit, page.total);
      setText("logs-page-label", `${first}–${last} / ${page.total}`);
      renderLogRows(page.items);
      populateModelFilter(page.items);
    } catch (error) {
      $("logs-table-body").replaceChildren();
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 7;
      cell.className = "table-empty";
      cell.textContent = error.message;
      row.append(cell);
      $("logs-table-body").append(row);
      toast(error.message, "error");
    }
  }

  function populateModelFilter(items) {
    const select = $("log-model-filter");
    const current = select.value;
    const models = [...new Set(items.map((item) => item.model).filter(Boolean))];
    select.replaceChildren(new Option("Все модели", ""));
    models.forEach((model) => select.add(new Option(model, model)));
    if (models.includes(current)) select.value = current;
  }

  function renderLogRows(items) {
    const body = $("logs-table-body");
    body.replaceChildren();
    if (!items.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 7;
      cell.className = "table-empty";
      cell.textContent = "Записей не найдено. Возможно, журнал пуст или запись отключена.";
      row.append(cell);
      body.append(row);
      return;
    }
    items.forEach((item) => {
      const row = document.createElement("tr");
      const timeCell = document.createElement("td");
      timeCell.textContent = formatDate(item.started_at);
      const statusCell = document.createElement("td");
      statusCell.append(makeStatusChip(item.status, item.http_status));
      const modelCell = document.createElement("td");
      modelCell.className = "model-chip";
      modelCell.textContent = item.model;
      const countCell = document.createElement("td");
      countCell.className = "table-mono";
      countCell.textContent = String(item.message_count);
      const tokensCell = document.createElement("td");
      tokensCell.className = "table-mono";
      tokensCell.textContent = item.estimated_input_tokens == null ? "—" : `≈ ${item.estimated_input_tokens}`;
      const durationCell = document.createElement("td");
      durationCell.className = "table-mono";
      durationCell.textContent = formatDuration(item.duration_ms);
      const actionCell = document.createElement("td");
      const open = document.createElement("button");
      open.className = "row-open";
      open.type = "button";
      open.textContent = "Подробности →";
      open.addEventListener("click", () => openLogDetail(item.id));
      actionCell.append(open);
      row.append(timeCell, statusCell, modelCell, countCell, tokensCell, durationCell, actionCell);
      body.append(row);
    });
  }

  async function openLogDetail(id) {
    try {
      const entry = await api(`/api/admin/logs/${encodeURIComponent(id)}`);
      const panel = $("log-detail");
      $("detail-title").textContent = `${entry.model} · ${entry.id.slice(0, 12)}`;
      const meta = $("detail-meta");
      meta.replaceChildren();
      [
        `Статус: ${STATUS_TEXT[entry.status] || entry.status} ${entry.http_status || ""}`,
        `Время: ${formatDate(entry.started_at)}`,
        `Длительность: ${formatDuration(entry.duration_ms)}`,
        `Клиент: ${entry.client}`,
        `Сообщений: ${entry.message_count}`,
        `Токены ≈ ${entry.estimated_input_tokens ?? "—"}`,
        `num_ctx: ${entry.num_ctx ?? "—"}`,
      ].forEach((text) => {
        const pill = document.createElement("span");
        pill.textContent = text;
        meta.append(pill);
      });
      const conversation = $("detail-messages");
      conversation.replaceChildren();
      (entry.messages || []).forEach((message) => {
        const block = document.createElement("div");
        block.className = "message-block";
        const heading = document.createElement("div");
        heading.className = "message-head";
        heading.textContent = message.role;
        const content = document.createElement("pre");
        content.textContent = message.content;
        block.append(heading, content);
        conversation.append(block);
      });
      $("detail-response").textContent = entry.response || "(ответ отсутствует)";
      const hasError = Boolean(entry.error_message);
      $("detail-error-wrap").hidden = !hasError;
      $("detail-error").textContent = entry.error_message || "";
      $("detail-file").textContent = entry.file ? `Файл: ${entry.file}` : "Запись из памяти";
      panel.hidden = false;
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function clearLogs() {
    if (!window.confirm("Удалить все JSON-файлы журналов и очистить список? Это действие нельзя отменить.")) return;
    try {
      const result = await api("/api/admin/logs", { method: "DELETE" });
      $("log-detail").hidden = true;
      toast(`Удалено файлов: ${result.deleted}.`, "success");
      await loadLogs(true);
      await refreshOverview();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function applyApiKey() {
    state.apiKey = $("api-key-input").value.trim();
    toast(state.apiKey ? "Ключ будет использован только в этой вкладке." : "Ключ очищен.", "success");
    refreshOverview();
    if (state.page === "settings") loadSettings();
    if (state.page === "logs") loadLogs(true);
  }

  function bindEvents() {
    document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.page)));
    document.querySelectorAll("[data-go]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.go)));
    $("refresh-button").addEventListener("click", () => {
      refreshOverview();
      if (state.page === "logs") loadLogs(true);
    });
    $("api-key-apply").addEventListener("click", applyApiKey);
    $("api-key-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter") applyApiKey();
    });
    $("settings-form").addEventListener("submit", saveSettings);
    $("probe-button").addEventListener("click", probeCurrentForm);
    $("reset-settings").addEventListener("click", resetSettings);
    $("field-model-select").addEventListener("change", (event) => {
      if (event.target.value) $("field-model").value = event.target.value;
    });
    ["field-context", "field-output", "field-num-ctx", "field-tolerance"].forEach((id) => $(id).addEventListener("input", updateBudgetPreview));
    $("logs-refresh").addEventListener("click", () => loadLogs(true));
    $("log-status-filter").addEventListener("change", () => loadLogs(true));
    $("log-model-filter").addEventListener("change", () => loadLogs(true));
    $("log-search").addEventListener("input", () => {
      window.clearTimeout(state.logSearchTimer);
      state.logSearchTimer = window.setTimeout(() => loadLogs(true), 350);
    });
    $("logs-prev").addEventListener("click", () => {
      state.logOffset = Math.max(0, state.logOffset - state.logLimit);
      loadLogs();
    });
    $("logs-next").addEventListener("click", () => {
      if (state.logOffset + state.logLimit < state.logTotal) state.logOffset += state.logLimit;
      loadLogs();
    });
    $("clear-logs").addEventListener("click", clearLogs);
    $("detail-close").addEventListener("click", () => { $("log-detail").hidden = true; });
    window.addEventListener("hashchange", () => {
      const page = location.hash.slice(1);
      if (PAGE_TITLES[page]) navigate(page);
    });
  }

  async function boot() {
    bindEvents();
    const requested = location.hash.slice(1);
    navigate(PAGE_TITLES[requested] ? requested : "overview");
    await refreshOverview();
    window.setInterval(() => {
      if (state.page === "overview") refreshOverview();
      if (state.page === "logs") loadLogs();
    }, 15000);
  }

  document.addEventListener("DOMContentLoaded", boot, { once: true });
})();
