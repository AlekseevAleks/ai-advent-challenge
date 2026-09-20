/**
 * Local AI Chat — frontend application.
 *
 * The browser only ever talks to the local FastAPI backend; the backend talks
 * to the OpenAI-compatible API. The API key never reaches this file.
 */
(() => {
  "use strict";

  // ------------------------------------------------------------------ state
  const state = {
    chats: [],
    activeChatId: null,
    activeChat: null,
    messages: [],
    settings: null,
    models: [],
    view: "empty", // empty | chat | settings | memory
    streaming: false,
    abortController: null,
    pendingDeleteId: null,
    memory: null,
    editingMemoryId: null,
    memoryPanelOpen: false,
    selectedModel: "",
    modelFilter: "",
    modelActiveIndex: -1,
    scrollPositions: new Map(),
  };

  const els = {
    app: document.getElementById("app"),
    sidebar: document.getElementById("sidebar"),
    sidebarOpen: document.getElementById("sidebarOpen"),
    sidebarClose: document.getElementById("sidebarClose"),
    sidebarBackdrop: document.getElementById("sidebarBackdrop"),
    settingsBtn: document.getElementById("settingsBtn"),
    memoryBtn: document.getElementById("memoryBtn"),
    newChatBtn: document.getElementById("newChatBtn"),
    chatList: document.getElementById("chatList"),
    chatTitle: document.getElementById("chatTitle"),
    chatMeta: document.getElementById("chatMeta"),
    regenerateBtn: document.getElementById("regenerateBtn"),
    memoryToggle: document.getElementById("memoryToggle"),
    view: document.getElementById("view"),
    apiStatusDot: document.getElementById("apiStatusDot"),
    apiStatusText: document.getElementById("apiStatusText"),
    newChatModal: document.getElementById("newChatModal"),
    modelCombo: document.getElementById("modelCombo"),
    modelSearch: document.getElementById("modelSearch"),
    modelOptions: document.getElementById("modelOptions"),
    modelClear: document.getElementById("modelClear"),
    modelSelected: document.getElementById("modelSelected"),
    modelHint: document.getElementById("modelHint"),
    createChatBtn: document.getElementById("createChatBtn"),
    confirmModal: document.getElementById("confirmModal"),
    confirmText: document.getElementById("confirmText"),
    confirmOkBtn: document.getElementById("confirmOkBtn"),
    memoryModal: document.getElementById("memoryModal"),
    memoryCategory: document.getElementById("memoryCategory"),
    memoryKey: document.getElementById("memoryKey"),
    memoryValue: document.getElementById("memoryValue"),
    memoryModalHint: document.getElementById("memoryModalHint"),
    memorySaveBtn: document.getElementById("memorySaveBtn"),
    toasts: document.getElementById("toasts"),
  };

  // ------------------------------------------------------------------- utils
  const escapeHtml = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  const formatTime = (iso) => {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString("ru-RU", {
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const formatDate = (iso) => {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleDateString("ru-RU", {
      day: "2-digit",
      month: "short",
    });
  };

  function toast(message, type = "info", timeout = 6000) {
    const node = document.createElement("div");
    node.className = `toast toast--${type}`;
    node.textContent = message;
    els.toasts.appendChild(node);
    setTimeout(() => {
      node.style.opacity = "0";
      node.style.transition = "opacity .25s ease";
      setTimeout(() => node.remove(), 260);
    }, timeout);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });

    if (response.status === 204) return null;

    let payload = null;
    const text = await response.text();
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = null;
      }
    }

    if (!response.ok) {
      const message =
        (payload && payload.error && payload.error.message) ||
        `Ошибка запроса (${response.status}).`;
      const error = new Error(message);
      error.code = payload && payload.error ? payload.error.code : "http_error";
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  // --------------------------------------------------------------- markdown
  const KEYWORDS = new Set([
    "def", "class", "return", "if", "else", "elif", "for", "while", "import",
    "from", "as", "try", "except", "finally", "with", "lambda", "yield",
    "async", "await", "pass", "break", "continue", "raise", "in", "is", "not",
    "and", "or", "None", "True", "False", "self", "const", "let", "var",
    "function", "new", "this", "typeof", "instanceof", "export", "default",
    "extends", "super", "static", "public", "private", "protected", "interface",
    "type", "enum", "implements", "package", "void", "int", "float", "double",
    "string", "bool", "struct", "func", "go", "defer", "chan", "select",
    "match", "case", "switch", "do", "throw", "catch", "null", "undefined",
    "true", "false", "end", "then", "fi", "esac", "echo", "local", "export",
  ]);

  function highlightCode(code, language) {
    const lang = (language || "").toLowerCase();
    if (["text", "plain", "txt", "output", ""].includes(lang)) {
      return escapeHtml(code);
    }

    // Tokenize the raw text and escape every token itself. Escaping first
    // would let the `#` of an HTML entity such as `&#39;` be treated as the
    // start of a comment, which swallows the rest of the line.
    const pattern =
      /(\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\/)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(\b\d+(?:\.\d+)?\b)|(\b[A-Za-z_$][\w$]*\b)/g;

    let result = "";
    let lastIndex = 0;
    let match;

    while ((match = pattern.exec(code)) !== null) {
      result += escapeHtml(code.slice(lastIndex, match.index));
      const [full, comment, str, num, word] = match;
      if (comment) {
        result += `<span class="tok-comment">${escapeHtml(comment)}</span>`;
      } else if (str) {
        result += `<span class="tok-string">${escapeHtml(str)}</span>`;
      } else if (num) {
        result += `<span class="tok-number">${escapeHtml(num)}</span>`;
      } else if (word) {
        result += KEYWORDS.has(word)
          ? `<span class="tok-keyword">${escapeHtml(word)}</span>`
          : escapeHtml(word);
      } else {
        result += escapeHtml(full);
      }
      lastIndex = match.index + full.length;
    }

    result += escapeHtml(code.slice(lastIndex));
    return result;
  }

  function renderInline(text) {
    let out = escapeHtml(text);
    out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    out = out.replace(/~~([^~]+)~~/g, "<del>$1</del>");
    out = out.replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    );
    return out;
  }

  function renderMarkdown(source) {
    const text = String(source ?? "").replace(/\r\n/g, "\n");
    const lines = text.split("\n");
    const html = [];
    let index = 0;

    const flushParagraph = (buffer) => {
      if (buffer.length) {
        html.push(`<p>${renderInline(buffer.join(" "))}</p>`);
        buffer.length = 0;
      }
    };

    const paragraph = [];

    while (index < lines.length) {
      const line = lines[index];

      // Fenced code block
      const fence = line.match(/^\s*```(\w+)?\s*$/);
      if (fence) {
        flushParagraph(paragraph);
        const language = fence[1] || "";
        const codeLines = [];
        index += 1;
        while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
          codeLines.push(lines[index]);
          index += 1;
        }
        index += 1; // skip closing fence
        const code = codeLines.join("\n");
        html.push(
          `<div class="code-block"><div class="code-block__head">` +
            `<span>${escapeHtml(language || "code")}</span>` +
            `<button class="code-block__copy" data-copy-code>Копировать</button>` +
            `</div><pre><code>${highlightCode(code, language)}</code></pre></div>`
        );
        continue;
      }

      // Headings
      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        flushParagraph(paragraph);
        const level = Math.min(heading[1].length, 4);
        html.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
        index += 1;
        continue;
      }

      // Horizontal rule
      if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
        flushParagraph(paragraph);
        html.push("<hr />");
        index += 1;
        continue;
      }

      // Blockquote
      if (/^\s*>\s?/.test(line)) {
        flushParagraph(paragraph);
        const quote = [];
        while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
          quote.push(lines[index].replace(/^\s*>\s?/, ""));
          index += 1;
        }
        html.push(`<blockquote>${renderInline(quote.join(" "))}</blockquote>`);
        continue;
      }

      // Lists
      const bullet = line.match(/^\s*[-*+]\s+(.*)$/);
      const ordered = line.match(/^\s*\d+[.)]\s+(.*)$/);
      if (bullet || ordered) {
        flushParagraph(paragraph);
        const isOrdered = Boolean(ordered);
        const items = [];
        while (index < lines.length) {
          const current = lines[index];
          const match = isOrdered
            ? current.match(/^\s*\d+[.)]\s+(.*)$/)
            : current.match(/^\s*[-*+]\s+(.*)$/);
          if (!match) break;
          items.push(`<li>${renderInline(match[1])}</li>`);
          index += 1;
        }
        const tag = isOrdered ? "ol" : "ul";
        html.push(`<${tag}>${items.join("")}</${tag}>`);
        continue;
      }

      // Table
      if (
        line.includes("|") &&
        index + 1 < lines.length &&
        /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[index + 1])
      ) {
        flushParagraph(paragraph);
        const parseRow = (row) =>
          row
            .trim()
            .replace(/^\|/, "")
            .replace(/\|$/, "")
            .split("|")
            .map((cell) => cell.trim());
        const header = parseRow(line);
        index += 2;
        const rows = [];
        while (index < lines.length && lines[index].includes("|")) {
          rows.push(parseRow(lines[index]));
          index += 1;
        }
        const head = header.map((cell) => `<th>${renderInline(cell)}</th>`).join("");
        const body = rows
          .map(
            (row) =>
              `<tr>${row.map((cell) => `<td>${renderInline(cell)}</td>`).join("")}</tr>`
          )
          .join("");
        html.push(
          `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`
        );
        continue;
      }

      // Blank line ends the paragraph
      if (!line.trim()) {
        flushParagraph(paragraph);
        index += 1;
        continue;
      }

      paragraph.push(line.trim());
      index += 1;
    }

    flushParagraph(paragraph);
    return html.join("");
  }

  // ------------------------------------------------------------------ render
  function renderSidebar() {
    if (!state.chats.length) {
      els.chatList.innerHTML =
        '<div class="chat-item" style="cursor:default;color:var(--text-dim)">' +
        "Чатов пока нет</div>";
      return;
    }

    els.chatList.innerHTML = state.chats
      .map(
        (chat) => `
        <div class="chat-item ${chat.id === state.activeChatId ? "is-active" : ""}"
             data-chat-id="${escapeHtml(chat.id)}" role="button" tabindex="0">
          <div class="chat-item__body">
            <div class="chat-item__title">${escapeHtml(chat.title)}</div>
            <div class="chat-item__sub">${escapeHtml(chat.model)} · ${formatDate(
          chat.updated_at
        )}</div>
          </div>
          <button class="chat-item__delete" data-delete-chat="${escapeHtml(
            chat.id
          )}" title="Удалить чат" aria-label="Удалить чат">🗑</button>
        </div>`
      )
      .join("");
  }

  function renderTopbar() {
    if (state.view === "chat" && state.activeChat) {
      els.chatTitle.textContent = state.activeChat.title;
      els.chatMeta.textContent = `Модель: ${state.activeChat.model}`;
      els.regenerateBtn.hidden = state.messages.length === 0;
      els.memoryToggle.hidden = false;
    } else if (state.view === "settings") {
      els.chatTitle.textContent = "Настройки";
      els.chatMeta.textContent = "API Base URL и API Key";
      els.regenerateBtn.hidden = true;
      els.memoryToggle.hidden = true;
    } else if (state.view === "memory") {
      els.chatTitle.textContent = "Память агента";
      els.chatMeta.textContent = state.activeChat
        ? `Чат: ${state.activeChat.title}`
        : "Три слоя памяти";
      els.regenerateBtn.hidden = true;
      els.memoryToggle.hidden = true;
    } else {
      els.chatTitle.textContent = "AI Chat";
      els.chatMeta.textContent = "";
      els.regenerateBtn.hidden = true;
      els.memoryToggle.hidden = true;
    }
  }

  function renderApiStatus() {
    const settings = state.settings;
    if (!settings || !settings.is_configured) {
      els.apiStatusDot.className = "status-dot is-bad";
      els.apiStatusText.textContent = "API не настроен";
    } else {
      els.apiStatusDot.className = "status-dot is-ok";
      els.apiStatusText.textContent = "API настроен";
    }
  }

  function messageNode(message, { streaming = false } = {}) {
    const author =
      message.role === "user"
        ? "Вы"
        : message.role === "assistant"
        ? "AI"
        : "Система";
    const initials =
      message.role === "user" ? "Я" : message.role === "assistant" ? "AI" : "S";

    const wrapper = document.createElement("div");
    wrapper.className = `message message--${message.role}`;
    wrapper.dataset.messageId = message.id || "";

    const actions =
      message.role === "assistant" && !streaming
        ? `<div class="message__actions">
             <button class="message__action" data-copy-message title="Копировать ответ">Копировать</button>
           </div>`
        : "";

    wrapper.innerHTML = `
      <div class="message__avatar">${initials}</div>
      <div class="message__body">
        <div class="message__head">
          <span class="message__author">${author}</span>
          <span class="message__time">${formatTime(message.created_at)}</span>
          ${actions}
        </div>
        <div class="message__content"></div>
      </div>`;

    const content = wrapper.querySelector(".message__content");
    if (streaming) {
      content.classList.add("cursor-blink");
      content.textContent = message.content || "";
    } else {
      content.innerHTML = renderMarkdown(message.content);
    }
    return wrapper;
  }

  function renderChat() {
    const layout = document.createElement("div");
    layout.className = "chat-layout";
    layout.id = "chatLayout";

    const container = document.createElement("div");
    container.className = "chat";

    const messages = document.createElement("div");
    messages.className = "messages";
    messages.id = "messagesScroll";

    const inner = document.createElement("div");
    inner.className = "messages__inner";
    inner.id = "messagesInner";

    if (!state.messages.length) {
      inner.innerHTML = `
        <div class="state">
          <div class="state__icon">💬</div>
          <div class="state__title">Начните диалог</div>
          <div class="state__text">Напишите первое сообщение — чат автоматически получит название.</div>
        </div>`;
    } else {
      state.messages.forEach((message) => inner.appendChild(messageNode(message)));
    }

    messages.appendChild(inner);

    const composer = document.createElement("div");
    composer.className = "composer";
    composer.innerHTML = `
      <div class="composer__inner">
        <textarea class="composer__input" id="composerInput" rows="1"
          placeholder="Напишите сообщение..."></textarea>
        <button class="composer__send" id="sendBtn" title="Отправить">➤</button>
      </div>
      <div class="composer__hint">Enter — отправить, Shift+Enter — новая строка</div>`;

    container.appendChild(messages);
    container.appendChild(composer);

    const panel = document.createElement("aside");
    panel.className = "memory-panel";
    panel.id = "memoryPanel";
    panel.setAttribute("aria-label", "Память агента");

    layout.appendChild(container);
    layout.appendChild(panel);

    els.view.innerHTML = "";
    els.view.appendChild(layout);

    const input = document.getElementById("composerInput");
    const sendBtn = document.getElementById("sendBtn");

    input.addEventListener("input", () => autoResize(input));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        handleSend();
      }
    });
    sendBtn.addEventListener("click", () => {
      if (state.streaming) {
        stopStreaming();
      } else {
        handleSend();
      }
    });

    updateSendButton();
    restoreScroll();
    input.focus();

    // The panel keeps its open/closed state across chat switches.
    if (state.memoryPanelOpen) {
      layout.classList.add("chat-layout--memory-open");
      loadMemory().then(renderMemoryPanel);
    } else {
      renderMemoryPanel();
    }
  }

  function autoResize(input) {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
  }

  function updateSendButton() {
    const sendBtn = document.getElementById("sendBtn");
    if (!sendBtn) return;
    if (state.streaming) {
      sendBtn.classList.add("is-stop");
      sendBtn.textContent = "■";
      sendBtn.title = "Остановить генерацию";
      sendBtn.disabled = false;
    } else {
      sendBtn.classList.remove("is-stop");
      sendBtn.textContent = "➤";
      sendBtn.title = "Отправить";
      sendBtn.disabled = false;
    }
  }

  function scrollToBottom(force = false) {
    const container = document.getElementById("messagesScroll");
    if (!container) return;
    const nearBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight < 160;
    if (force || nearBottom) {
      container.scrollTop = container.scrollHeight;
    }
  }

  function saveScroll() {
    const container = document.getElementById("messagesScroll");
    if (container && state.activeChatId) {
      state.scrollPositions.set(state.activeChatId, container.scrollTop);
    }
  }

  function restoreScroll() {
    const container = document.getElementById("messagesScroll");
    if (!container) return;
    const saved = state.scrollPositions.get(state.activeChatId);
    if (typeof saved === "number") {
      container.scrollTop = saved;
    } else {
      container.scrollTop = container.scrollHeight;
    }
  }

  function renderEmptyState() {
    const hasSettings = state.settings && state.settings.is_configured;
    els.view.innerHTML = `
      <div class="state">
        <div class="state__icon">${hasSettings ? "💬" : "⚙"}</div>
        <div class="state__title">${
          hasSettings ? "У вас пока нет чатов" : "Для начала работы настройте API"
        }</div>
        <div class="state__text">${
          hasSettings
            ? "Создайте новый чат и выберите модель."
            : "Укажите API Base URL и API Key, чтобы загрузить список моделей."
        }</div>
        <div class="state__actions">
          ${
            hasSettings
              ? '<button class="btn btn--primary" data-action="new-chat">＋ Новый чат</button>'
              : '<button class="btn btn--primary" data-action="open-settings">Настройки</button>'
          }
        </div>
      </div>`;
  }

  function renderSettings() {
    const settings = state.settings || {
      api_base_url: "",
      api_key_masked: "",
      has_api_key: false,
    };

    els.view.innerHTML = `
      <div class="settings">
        <div class="settings__inner">
          <h2 class="settings__title">Настройки</h2>
          <p class="settings__subtitle">
            Укажите адрес OpenAI-compatible API. Ключ хранится только локально
            на этом компьютере и не передаётся никуда, кроме указанного сервера.
          </p>

          <div class="card">
            <h3 class="card__title">Подключение</h3>
            <p class="card__text">Например: https://api.openai.com/v1 или http://localhost:8000/v1</p>

            <label class="field">
              <span class="field__label">API Base URL</span>
              <input class="input" id="baseUrlInput" type="text" spellcheck="false"
                placeholder="https://api.example.com/v1"
                value="${escapeHtml(settings.api_base_url || "")}" />
            </label>

            <label class="field">
              <span class="field__label">API Key</span>
              <input class="input" id="apiKeyInput" type="password" spellcheck="false"
                autocomplete="off" placeholder="${
                  settings.has_api_key
                    ? escapeHtml(settings.api_key_masked)
                    : "sk-..."
                }" />
              <div class="field__hint">${
                settings.has_api_key
                  ? "Ключ сохранён. Оставьте поле пустым, чтобы не менять его."
                  : "Ключ ещё не сохранён."
              }</div>
            </label>

            <div class="settings__actions">
              <button class="btn btn--primary" id="saveSettingsBtn">Сохранить</button>
              <button class="btn btn--ghost" id="testSettingsBtn">Проверить подключение</button>
            </div>

            <div id="testResult"></div>
          </div>

          <div class="card">
            <h3 class="card__title">Локальные данные</h3>
            <p class="card__text">
              Настройки: data/config.json · Чаты: data/chat.db<br />
              Файлы не попадают в git и остаются на вашем компьютере.
            </p>
          </div>
        </div>
      </div>`;

    document
      .getElementById("saveSettingsBtn")
      .addEventListener("click", saveSettings);
    document
      .getElementById("testSettingsBtn")
      .addEventListener("click", testConnection);
  }

  // ------------------------------------------------------------------ memory
  function memoryList(items) {
    if (!items || !items.length) return "";
    return `<ul class="memory-list">${items
      .map((item) => `<li>${escapeHtml(item)}</li>`)
      .join("")}</ul>`;
  }

  function memoryField(label, value) {
    if (!value) return "";
    return `<div class="memory-field">
      <span class="memory-field__label">${escapeHtml(label)}</span>
      <span class="memory-field__value">${escapeHtml(value)}</span>
    </div>`;
  }

  // Reusable memory blocks: rendered both on the full memory screen and in the
  // chat side panel, so the two views can never drift apart.
  function shortTermBlockHtml(shortTerm) {
    if (!shortTerm) {
      return `<div class="memory-empty">Выберите чат, чтобы увидеть его диалог.</div>`;
    }
    if (!shortTerm.entries.length) {
      return `<div class="memory-empty">В этом чате пока нет сообщений.</div>`;
    }
    return `<div class="memory-transcript">${shortTerm.entries
      .map(
        (entry) => `<div class="memory-line memory-line--${entry.role}">
          <span class="memory-line__role">${escapeHtml(entry.role)}</span>
          <span class="memory-line__text">${escapeHtml(
            entry.content.length > 300
              ? `${entry.content.slice(0, 300)}…`
              : entry.content
          )}</span>
        </div>`
      )
      .join("")}</div>
      <div class="memory-note">
        Показано ${shortTerm.entries.length} из ${shortTerm.total_messages} сообщений${
          shortTerm.truncated ? " (контекст обрезан)" : ""
        }.
      </div>`;
  }

  function workingBlockHtml(working) {
    if (!working || !working.exists) {
      return `<div class="memory-empty">Рабочая память пуста — задача ещё не определена.</div>`;
    }
    const data = working.data || {};
    const listField = (label, items) =>
      items && items.length
        ? `<div class="memory-field"><span class="memory-field__label">${label}</span>${memoryList(
            items
          )}</div>`
        : "";

    return `<div class="memory-grid">
        ${memoryField("Текущая задача", data.task)}
        ${memoryField("Цель", data.goal)}
        ${memoryField("Текущий этап", data.current_step)}
      </div>
      ${listField("Стек", data.stack)}
      ${listField("Выполнено", data.completed)}
      ${listField("Ограничения", data.constraints)}
      ${listField("Решения", data.decisions)}`;
  }

  function longTermBlockHtml(longTerm, { compact = false } = {}) {
    const entries = (longTerm && longTerm.entries) || [];
    if (!entries.length) {
      return `<div class="memory-empty">Долговременная память пуста. Напишите, например: «Я предпочитаю Python».</div>`;
    }
    return `<div class="memory-entries${compact ? " memory-entries--compact" : ""}">${entries
      .map(
        (entry) => `<div class="memory-entry">
          <div class="memory-entry__body">
            <span class="memory-entry__category">${escapeHtml(
              entry.category
            )}</span>
            <span class="memory-entry__key">${escapeHtml(entry.key)}</span>
            <span class="memory-entry__value">${escapeHtml(entry.value)}</span>
            <span class="memory-entry__source">${escapeHtml(entry.source)}</span>
          </div>
          <div class="memory-entry__actions">
            <button class="message__action" data-edit-memory="${escapeHtml(
              entry.id
            )}">Изменить</button>
            <button class="message__action" data-delete-memory="${escapeHtml(
              entry.id
            )}">Удалить</button>
          </div>
        </div>`
      )
      .join("")}</div>`;
  }

  function memoryActionsHtml() {
    const disabled = state.activeChatId ? "" : "disabled";
    return `<div class="settings__actions">
      <button class="btn btn--ghost" data-action="edit-working" ${disabled}>Изменить</button>
      <button class="btn btn--ghost" data-action="clear-working" ${disabled}>Очистить</button>
      <button class="btn btn--ghost" data-action="analyze-memory" ${disabled}>Проанализировать чат</button>
    </div>`;
  }

  function renderMemory() {
    const memory = state.memory;
    if (!memory) {
      els.view.innerHTML = `
        <div class="state">
          <div class="state__icon">🧠</div>
          <div class="state__title">Загрузка памяти…</div>
        </div>`;
      return;
    }

    els.view.innerHTML = `
      <div class="settings">
        <div class="settings__inner">
          <h2 class="settings__title">Память агента</h2>
          <p class="settings__subtitle">
            Три независимых слоя: текущий диалог, состояние задачи и устойчивые
            факты о пользователе. Ниже видно, что и куда попало.
          </p>

          <div class="card">
            <h3 class="card__title">1. Short-term memory — текущий диалог</h3>
            <p class="card__text">
              Сообщения этого чата. Используется как история разговора и
              ограничивается окном контекста.
            </p>
            ${shortTermBlockHtml(memory.short_term)}
          </div>

          <div class="card">
            <h3 class="card__title">2. Working memory — текущая задача</h3>
            <p class="card__text">
              Структурированное состояние задачи этого чата. Не является
              историей сообщений.
            </p>
            ${workingBlockHtml(memory.working)}
            ${memoryActionsHtml()}
          </div>

          <div class="card">
            <h3 class="card__title">3. Long-term memory — профиль пользователя</h3>
            <p class="card__text">
              Устойчивые факты, общие для всех чатов. Не удаляются вместе с чатом.
            </p>
            ${longTermBlockHtml(memory.long_term)}
            <div class="settings__actions">
              <button class="btn btn--primary" data-action="add-memory">Добавить запись</button>
            </div>
          </div>

          <div class="card">
            <h3 class="card__title">Что уходит в prompt</h3>
            <p class="card__text">
              Компактный текст, который получает модель: long-term → working →
              short-term. Сырой JSON не отправляется.
            </p>
            <pre class="memory-prompt">${escapeHtml(
              memory.prompt_preview || "Память пока пуста."
            )}</pre>
          </div>
        </div>
      </div>`;
  }

  // ------------------------------------------------------- chat side panel
  function renderMemoryPanel() {
    const panel = document.getElementById("memoryPanel");
    if (!panel) return;

    const memory = state.memory;
    if (!memory) {
      panel.innerHTML = `<div class="memory-panel__loading">Загрузка памяти…</div>`;
      return;
    }

    panel.innerHTML = `
      <div class="memory-panel__section">
        <div class="memory-panel__title">
          <span class="memory-panel__badge">1</span> Short-term
          <span class="memory-panel__hint">текущий диалог</span>
        </div>
        ${shortTermBlockHtml(memory.short_term)}
      </div>

      <div class="memory-panel__section">
        <div class="memory-panel__title">
          <span class="memory-panel__badge">2</span> Working
          <span class="memory-panel__hint">текущая задача</span>
        </div>
        ${workingBlockHtml(memory.working)}
        ${memoryActionsHtml()}
      </div>

      <div class="memory-panel__section">
        <div class="memory-panel__title">
          <span class="memory-panel__badge">3</span> Long-term
          <span class="memory-panel__hint">профиль пользователя</span>
        </div>
        ${longTermBlockHtml(memory.long_term, { compact: true })}
        <div class="settings__actions">
          <button class="btn btn--ghost" data-action="add-memory">Добавить запись</button>
        </div>
      </div>

      <div class="memory-panel__section">
        <div class="memory-panel__title">Что уходит в prompt</div>
        <pre class="memory-prompt">${escapeHtml(
          memory.prompt_preview || "Память пока пуста."
        )}</pre>
      </div>`;
  }

  function toggleMemoryPanel(force) {
    const layout = document.getElementById("chatLayout");
    if (!layout) return;
    const next =
      typeof force === "boolean"
        ? force
        : !layout.classList.contains("chat-layout--memory-open");
    state.memoryPanelOpen = next;
    layout.classList.toggle("chat-layout--memory-open", next);
    const toggle = document.getElementById("memoryToggle");
    if (toggle) {
      toggle.classList.toggle("is-active", next);
      toggle.title = next ? "Скрыть память" : "Показать память";
    }
    if (next) {
      loadMemory().then(renderMemoryPanel);
    }
  }

  async function loadMemory() {
    const query = state.activeChatId
      ? `?chat_id=${encodeURIComponent(state.activeChatId)}`
      : "";
    try {
      state.memory = await api(`/api/memory${query}`);
    } catch (error) {
      state.memory = null;
      toast(error.message, "error");
    }
  }

  async function openMemory() {
    state.view = "memory";
    state.memory = null;
    closeSidebar();
    render();
    await loadMemory();
    render();
  }

  async function refreshMemory() {
    await loadMemory();
    render();
  }

  async function analyzeMemory() {
    if (!state.activeChatId) return;
    try {
      const report = await api(
        `/api/chats/${state.activeChatId}/memory/analyze`,
        { method: "POST" }
      );
      const parts = [];
      if (report.working_memory_changes.length) {
        parts.push(`working: ${report.working_memory_changes.join("; ")}`);
      }
      if (report.long_term_accepted.length) {
        parts.push(
          `long-term: ${report.long_term_accepted
            .map((entry) => `${entry.key}=${entry.value}`)
            .join(", ")}`
        );
      }
      if (report.long_term_rejected.length) {
        parts.push(`отклонено: ${report.long_term_rejected.length}`);
      }
      toast(
        parts.length ? `Память обновлена — ${parts.join(" | ")}` : "Новых данных для памяти не найдено.",
        "success",
        6000
      );
      await refreshMemory();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function clearWorkingMemory() {
    if (!state.activeChatId) return;
    try {
      await api(`/api/chats/${state.activeChatId}/memory/working`, {
        method: "DELETE",
      });
      toast("Рабочая память очищена.", "success", 3000);
      await refreshMemory();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function openWorkingEditor() {
    const working = state.memory && state.memory.working;
    const data = (working && working.data) || {};
    const asLines = (items) => (items || []).join(", ");

    els.view.innerHTML = `
      <div class="settings">
        <div class="settings__inner">
          <h2 class="settings__title">Рабочая память</h2>
          <p class="settings__subtitle">
            Состояние текущей задачи. Списки вводятся через запятую.
          </p>
          <div class="card">
            <label class="field">
              <span class="field__label">Текущая задача</span>
              <input class="input" id="wmTask" type="text" value="${escapeHtml(
                data.task || ""
              )}" />
            </label>
            <label class="field">
              <span class="field__label">Цель</span>
              <input class="input" id="wmGoal" type="text" value="${escapeHtml(
                data.goal || ""
              )}" />
            </label>
            <label class="field">
              <span class="field__label">Текущий этап</span>
              <input class="input" id="wmStep" type="text" value="${escapeHtml(
                data.current_step || ""
              )}" />
            </label>
            <label class="field">
              <span class="field__label">Стек (через запятую)</span>
              <input class="input" id="wmStack" type="text" value="${escapeHtml(
                asLines(data.stack)
              )}" />
            </label>
            <label class="field">
              <span class="field__label">Выполнено (через запятую)</span>
              <input class="input" id="wmCompleted" type="text" value="${escapeHtml(
                asLines(data.completed)
              )}" />
            </label>
            <label class="field">
              <span class="field__label">Ограничения (через запятую)</span>
              <input class="input" id="wmConstraints" type="text" value="${escapeHtml(
                asLines(data.constraints)
              )}" />
            </label>
            <label class="field">
              <span class="field__label">Решения (через запятую)</span>
              <input class="input" id="wmDecisions" type="text" value="${escapeHtml(
                asLines(data.decisions)
              )}" />
            </label>
            <div class="settings__actions">
              <button class="btn btn--primary" data-action="save-working">Сохранить</button>
              <button class="btn btn--ghost" data-action="open-memory">Отмена</button>
            </div>
          </div>
        </div>
      </div>`;
  }

  async function saveWorkingMemory() {
    if (!state.activeChatId) return;
    const splitList = (id) =>
      document
        .getElementById(id)
        .value.split(",")
        .map((item) => item.trim())
        .filter(Boolean);

    const payload = {
      data: {
        task: document.getElementById("wmTask").value.trim(),
        goal: document.getElementById("wmGoal").value.trim(),
        current_step: document.getElementById("wmStep").value.trim(),
        stack: splitList("wmStack"),
        completed: splitList("wmCompleted"),
        constraints: splitList("wmConstraints"),
        decisions: splitList("wmDecisions"),
      },
    };

    try {
      await api(`/api/chats/${state.activeChatId}/memory/working`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      toast("Рабочая память сохранена.", "success", 3000);
      await openMemory();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function openMemoryModal(entry) {
    state.editingMemoryId = entry ? entry.id : null;
    document.getElementById("memoryModalTitle").textContent = entry
      ? "Изменить запись"
      : "Новая запись";
    els.memoryCategory.value = entry ? entry.category : "preference";
    els.memoryKey.value = entry ? entry.key : "";
    els.memoryValue.value = entry ? entry.value : "";
    els.memoryModalHint.textContent = "";
    openModal("memoryModal");
  }

  async function saveMemoryEntry() {
    const category = els.memoryCategory.value;
    const key = els.memoryKey.value.trim();
    const value = els.memoryValue.value.trim();

    if (!key || !value) {
      els.memoryModalHint.textContent = "Заполните ключ и значение.";
      return;
    }

    try {
      if (state.editingMemoryId) {
        await api(`/api/memory/long-term/${state.editingMemoryId}`, {
          method: "PUT",
          body: JSON.stringify({ category, key, value }),
        });
      } else {
        await api("/api/memory/long-term", {
          method: "POST",
          body: JSON.stringify({ category, key, value, source: "manual" }),
        });
      }
      closeModal("memoryModal");
      toast("Запись сохранена.", "success", 3000);
      await refreshMemory();
    } catch (error) {
      els.memoryModalHint.textContent = error.message;
    }
  }

  async function deleteMemoryEntry(memoryId) {
    try {
      await api(`/api/memory/long-term/${memoryId}`, { method: "DELETE" });
      toast("Запись удалена.", "success", 3000);
      await refreshMemory();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function render() {
    renderSidebar();
    renderTopbar();
    renderApiStatus();

    if (state.view === "settings") {
      renderSettings();
    } else if (state.view === "memory") {
      renderMemory();
    } else if (state.view === "chat" && state.activeChat) {
      renderChat();
    } else {
      renderEmptyState();
    }
  }

  // ------------------------------------------------------------------ modals
  function openModal(id) {
    document.getElementById(id).hidden = false;
  }

  function closeModal(id) {
    document.getElementById(id).hidden = true;
  }

  document.querySelectorAll("[data-close]").forEach((node) => {
    node.addEventListener("click", () => {
      closeModal(node.dataset.close);
      if (node.dataset.close === "newChatModal") closeModelOptions();
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeModal("newChatModal");
      closeModal("confirmModal");
      closeModal("memoryModal");
      closeSidebar();
    }
  });

  // ---------------------------------------------------------------- sidebar
  function openSidebar() {
    els.app.classList.add("sidebar-open");
    els.sidebarBackdrop.hidden = false;
  }

  function closeSidebar() {
    els.app.classList.remove("sidebar-open");
    els.sidebarBackdrop.hidden = true;
  }

  els.sidebarOpen.addEventListener("click", openSidebar);
  els.sidebarClose.addEventListener("click", closeSidebar);
  els.sidebarBackdrop.addEventListener("click", closeSidebar);

  // ------------------------------------------------------------------- data
  async function loadSettings() {
    try {
      state.settings = await api("/api/settings");
    } catch (error) {
      state.settings = null;
      toast(error.message, "error");
    }
    renderApiStatus();
  }

  async function loadChats() {
    try {
      const data = await api("/api/chats");
      state.chats = data.chats || [];
    } catch (error) {
      state.chats = [];
      toast(error.message, "error");
    }
    renderSidebar();
  }

  async function openChat(chatId) {
    saveScroll();
    try {
      const [chat, data] = await Promise.all([
        api(`/api/chats/${chatId}`),
        api(`/api/chats/${chatId}/messages`),
      ]);
      state.activeChatId = chatId;
      state.activeChat = chat;
      state.messages = data.messages || [];
      state.view = "chat";
      closeSidebar();
      render();
      if (state.memory) {
        // The memory screen was open before; refresh it for the new chat.
        await loadMemory();
      }
    } catch (error) {
      toast(error.message, "error");
      if (error.status === 404) {
        await loadChats();
        state.view = "empty";
        state.activeChat = null;
        state.activeChatId = null;
        render();
      }
    }
  }

  // ------------------------------------------------------- model combobox
  function filteredModels() {
    const query = state.modelFilter.trim().toLowerCase();
    if (!query) return state.models;
    return state.models.filter((model) =>
      model.id.toLowerCase().includes(query)
    );
  }

  function renderModelOptions() {
    const matches = filteredModels();
    const list = els.modelOptions;

    if (!state.models.length) {
      list.hidden = true;
      return;
    }

    if (!matches.length) {
      list.innerHTML = `<div class="combo__empty">Ничего не найдено</div>`;
      list.hidden = false;
      return;
    }

    // Cap the rendered list: some providers expose hundreds of models.
    const visible = matches.slice(0, 200);
    list.innerHTML = visible
      .map((model, index) => {
        const active = index === state.modelActiveIndex ? " is-active" : "";
        const selected = model.id === state.selectedModel ? " is-selected" : "";
        return `<div class="combo__option${active}${selected}" role="option"
          data-model-index="${index}" aria-selected="${
          model.id === state.selectedModel
        }">${escapeHtml(model.id)}</div>`;
      })
      .join("");
    if (matches.length > visible.length) {
      list.innerHTML += `<div class="combo__more">…и ещё ${
        matches.length - visible.length
      }</div>`;
    }
    list.hidden = false;
  }

  function selectModel(modelId) {
    state.selectedModel = modelId;
    els.modelSearch.value = modelId;
    state.modelFilter = modelId;
    state.modelActiveIndex = -1;
    els.modelOptions.hidden = true;
    els.modelSearch.setAttribute("aria-expanded", "false");
    els.modelClear.hidden = !modelId;
    els.modelSelected.textContent = modelId ? `Выбрано: ${modelId}` : "";
    els.createChatBtn.disabled = !modelId;
  }

  function closeModelOptions() {
    els.modelOptions.hidden = true;
    els.modelSearch.setAttribute("aria-expanded", "false");
    state.modelActiveIndex = -1;
  }

  function moveModelSelection(delta) {
    const matches = filteredModels();
    if (!matches.length) return;
    if (els.modelOptions.hidden) renderModelOptions();
    const total = Math.min(matches.length, 200);
    state.modelActiveIndex =
      (state.modelActiveIndex + delta + total) % total;
    renderModelOptions();
    const active = els.modelOptions.querySelector(".combo__option.is-active");
    if (active) active.scrollIntoView({ block: "nearest" });
  }

  async function loadModels() {
    state.models = [];
    state.selectedModel = "";
    state.modelFilter = "";
    state.modelActiveIndex = -1;
    els.modelSearch.value = "";
    els.modelSearch.disabled = true;
    els.modelClear.hidden = true;
    els.modelSelected.textContent = "";
    els.modelOptions.hidden = true;
    els.modelHint.textContent = "Загрузка моделей…";
    els.createChatBtn.disabled = true;

    try {
      const data = await api("/api/models");
      state.models = data.models || [];
      if (!state.models.length) {
        throw new Error("API не вернул ни одной модели.");
      }
      els.modelSearch.disabled = false;
      els.modelHint.textContent = `Доступно моделей: ${state.models.length}. Начните вводить название.`;
      els.modelSearch.focus();
    } catch (error) {
      state.models = [];
      els.modelSearch.disabled = true;
      els.modelHint.textContent = `${error.message}\n\nПроверьте настройки API.`;
      els.createChatBtn.disabled = true;
    }
  }

  // ---------------------------------------------------------------- actions
  async function handleNewChat() {
    if (!state.settings || !state.settings.is_configured) {
      toast("Сначала настройте API: укажите Base URL и API Key.", "error");
      openSettings();
      return;
    }
    openModal("newChatModal");
    await loadModels();
  }

  async function handleCreateChat() {
    const model = state.selectedModel;
    if (!model) {
      toast("Выберите модель из списка.", "error");
      return;
    }
    els.createChatBtn.disabled = true;
    try {
      const chat = await api("/api/chats", {
        method: "POST",
        body: JSON.stringify({ model }),
      });
      closeModal("newChatModal");
      await loadChats();
      await openChat(chat.id);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      els.createChatBtn.disabled = false;
    }
  }

  function askDeleteChat(chatId) {
    const chat = state.chats.find((item) => item.id === chatId);
    state.pendingDeleteId = chatId;
    els.confirmText.textContent = chat
      ? `Чат «${chat.title}» и все его сообщения будут удалены безвозвратно.`
      : "Чат и все его сообщения будут удалены безвозвратно.";
    openModal("confirmModal");
  }

  async function confirmDeleteChat() {
    const chatId = state.pendingDeleteId;
    state.pendingDeleteId = null;
    closeModal("confirmModal");
    if (!chatId) return;

    try {
      await api(`/api/chats/${chatId}`, { method: "DELETE" });
      state.scrollPositions.delete(chatId);
      if (state.activeChatId === chatId) {
        state.activeChatId = null;
        state.activeChat = null;
        state.messages = [];
        state.view = "empty";
      }
      await loadChats();
      render();
      toast("Чат удалён.", "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function openSettings() {
    state.view = "settings";
    closeSidebar();
    render();
  }

  async function saveSettings() {
    const baseUrl = document.getElementById("baseUrlInput").value.trim();
    const apiKey = document.getElementById("apiKeyInput").value;

    if (baseUrl && !/^https?:\/\//i.test(baseUrl)) {
      toast("API Base URL должен начинаться с http:// или https://", "error");
      return;
    }

    const payload = { api_base_url: baseUrl };
    if (apiKey.trim()) payload.api_key = apiKey.trim();

    try {
      state.settings = await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      render();
      toast("Настройки сохранены.", "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function testConnection() {
    const resultBox = document.getElementById("testResult");
    const button = document.getElementById("testSettingsBtn");
    button.disabled = true;
    resultBox.className = "test-result";
    resultBox.textContent = "Проверяем подключение…";

    try {
      const result = await api("/api/settings/test", { method: "POST" });
      resultBox.className = `test-result ${result.ok ? "is-ok" : "is-bad"}`;
      resultBox.textContent = result.message;
    } catch (error) {
      resultBox.className = "test-result is-bad";
      resultBox.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  // --------------------------------------------------------------- messaging
  function appendMessage(message, options) {
    const inner = document.getElementById("messagesInner");
    if (!inner) return null;
    const emptyState = inner.querySelector(".state");
    if (emptyState) emptyState.remove();
    const node = messageNode(message, options);
    inner.appendChild(node);
    return node;
  }

  function setTypingIndicator(visible) {
    const inner = document.getElementById("messagesInner");
    if (!inner) return;
    let indicator = document.getElementById("typingIndicator");
    if (visible) {
      if (!indicator) {
        indicator = document.createElement("div");
        indicator.id = "typingIndicator";
        indicator.className = "message message--assistant";
        indicator.innerHTML = `
          <div class="message__avatar">AI</div>
          <div class="message__body">
            <div class="message__head"><span class="message__author">AI</span></div>
            <div class="typing">AI печатает
              <span class="typing__dots"><span></span><span></span><span></span></span>
            </div>
          </div>`;
        inner.appendChild(indicator);
      }
      scrollToBottom(true);
    } else if (indicator) {
      indicator.remove();
    }
  }

  function stopStreaming() {
    if (state.abortController) {
      state.abortController.abort();
      state.abortController = null;
    }
    state.streaming = false;
    setTypingIndicator(false);
    updateSendButton();
  }

  async function handleSend() {
    if (state.streaming) return;
    const input = document.getElementById("composerInput");
    if (!input) return;
    const content = input.value.trim();
    if (!content) return;
    if (!state.activeChatId) return;

    input.value = "";
    autoResize(input);

    const userMessage = {
      id: `local-${Date.now()}`,
      chat_id: state.activeChatId,
      role: "user",
      content,
      created_at: new Date().toISOString(),
    };
    state.messages.push(userMessage);
    appendMessage(userMessage);
    scrollToBottom(true);

    await streamReply({ content });
  }

  async function streamReply(body, { regenerate = false } = {}) {
    state.streaming = true;
    updateSendButton();
    setTypingIndicator(true);

    const assistantMessage = {
      id: `stream-${Date.now()}`,
      chat_id: state.activeChatId,
      role: "assistant",
      content: "",
      created_at: new Date().toISOString(),
    };
    const node = appendMessage(assistantMessage, { streaming: true });
    const contentNode = node ? node.querySelector(".message__content") : null;

    const controller = new AbortController();
    state.abortController = controller;

    const url = regenerate
      ? `/api/chats/${state.activeChatId}/regenerate/stream`
      : `/api/chats/${state.activeChatId}/messages/stream`;

    let buffer = "";
    let received = false;
    let failed = false;

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!response.ok) {
        let message = `Ошибка запроса (${response.status}).`;
        try {
          const payload = await response.json();
          if (payload && payload.error && payload.error.message) {
            message = payload.error.message;
          }
        } catch {
          /* ignore */
        }
        throw new Error(message);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let raw = "";

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        raw += decoder.decode(value, { stream: true });

        const blocks = raw.split("\n\n");
        raw = blocks.pop() || "";

        for (const block of blocks) {
          const lines = block.split("\n");
          let eventName = "message";
          let dataLine = "";
          for (const line of lines) {
            if (line.startsWith("event:")) eventName = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
          }
          if (!dataLine) continue;

          let payload;
          try {
            payload = JSON.parse(dataLine);
          } catch {
            continue;
          }

          if (eventName === "user_message") {
            // Replace the optimistic local message with the persisted one.
            const localIndex = state.messages.findIndex(
              (message) => message.id === userMessageId()
            );
            if (localIndex >= 0) state.messages[localIndex] = payload;
          } else if (eventName === "delta") {
            received = true;
            setTypingIndicator(false);
            buffer += payload.content || "";
            if (contentNode) contentNode.textContent = buffer;
            scrollToBottom();
          } else if (eventName === "done") {
            assistantMessage.id = payload.id;
            assistantMessage.content = payload.content;
            assistantMessage.created_at = payload.created_at;
            if (node) {
              const fresh = messageNode(assistantMessage);
              node.replaceWith(fresh);
            }
          } else if (eventName === "error") {
            failed = true;
            toast(payload.message || "Не удалось получить ответ от API.", "error");
          }
        }
      }
    } catch (error) {
      if (error.name === "AbortError") {
        if (buffer) {
          assistantMessage.content = buffer;
          if (node) node.replaceWith(messageNode(assistantMessage));
        } else if (node) {
          node.remove();
        }
        toast("Генерация остановлена.", "info", 3000);
      } else {
        failed = true;
        toast(error.message, "error");
        if (node) node.remove();
      }
    } finally {
      state.streaming = false;
      state.abortController = null;
      setTypingIndicator(false);
      updateSendButton();

      if (!failed && received) {
        state.messages.push(assistantMessage);
      }

      // Refresh chat list (title may have changed) and the active chat meta.
      try {
        const chats = await api("/api/chats");
        state.chats = chats.chats || [];
        const current = state.chats.find((chat) => chat.id === state.activeChatId);
        if (current) state.activeChat = current;
        renderSidebar();
        renderTopbar();
      } catch {
        /* non-critical */
      }

      // Memory was updated by the analysis step, so refresh the side panel.
      if (state.memoryPanelOpen) {
        await loadMemory();
        renderMemoryPanel();
      }
    }
  }

  function userMessageId() {
    const lastUser = [...state.messages]
      .reverse()
      .find((message) => message.role === "user");
    return lastUser ? lastUser.id : null;
  }

  async function handleRegenerate() {
    if (state.streaming || !state.activeChatId) return;
    if (!state.messages.length) return;

    // Remove the trailing assistant message locally.
    const lastIndex = state.messages.length - 1;
    if (state.messages[lastIndex].role === "assistant") {
      state.messages.pop();
      const inner = document.getElementById("messagesInner");
      const nodes = inner ? inner.querySelectorAll(".message") : [];
      if (nodes.length) nodes[nodes.length - 1].remove();
    }

    await streamReply({}, { regenerate: true });
  }

  // ------------------------------------------------------------- delegation
  els.chatList.addEventListener("click", (event) => {
    const deleteBtn = event.target.closest("[data-delete-chat]");
    if (deleteBtn) {
      event.stopPropagation();
      askDeleteChat(deleteBtn.dataset.deleteChat);
      return;
    }
    const item = event.target.closest("[data-chat-id]");
    if (item) openChat(item.dataset.chatId);
  });

  els.chatList.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const item = event.target.closest("[data-chat-id]");
    if (item) {
      event.preventDefault();
      openChat(item.dataset.chatId);
    }
  });

  els.view.addEventListener("click", async (event) => {
    const action = event.target.closest("[data-action]");
    if (action) {
      const name = action.dataset.action;
      if (name === "new-chat") handleNewChat();
      if (name === "open-settings") openSettings();
      if (name === "open-memory") openMemory();
      if (name === "analyze-memory") analyzeMemory();
      if (name === "clear-working") clearWorkingMemory();
      if (name === "edit-working") openWorkingEditor();
      if (name === "save-working") saveWorkingMemory();
      if (name === "add-memory") openMemoryModal(null);
      return;
    }

    const editMemory = event.target.closest("[data-edit-memory]");
    if (editMemory) {
      const entry = ((state.memory || {}).long_term || { entries: [] }).entries.find(
        (item) => item.id === editMemory.dataset.editMemory
      );
      if (entry) openMemoryModal(entry);
      return;
    }

    const deleteMemory = event.target.closest("[data-delete-memory]");
    if (deleteMemory) {
      await deleteMemoryEntry(deleteMemory.dataset.deleteMemory);
      return;
    }

    const copyCode = event.target.closest("[data-copy-code]");
    if (copyCode) {
      const block = copyCode.closest(".code-block");
      const code = block ? block.querySelector("code") : null;
      if (code) {
        await copyText(code.textContent);
        copyCode.textContent = "Скопировано";
        setTimeout(() => (copyCode.textContent = "Копировать"), 1500);
      }
      return;
    }

    const copyMessage = event.target.closest("[data-copy-message]");
    if (copyMessage) {
      const message = copyMessage.closest(".message");
      const content = message ? message.querySelector(".message__content") : null;
      if (content) {
        await copyText(content.innerText);
        copyMessage.textContent = "Скопировано";
        setTimeout(() => (copyMessage.textContent = "Копировать"), 1500);
      }
    }
  });

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
  }

  els.settingsBtn.addEventListener("click", openSettings);
  els.memoryBtn.addEventListener("click", openMemory);
  els.memoryToggle.addEventListener("click", () => toggleMemoryPanel());

  // ------------------------------------------------- model combobox events
  els.modelSearch.addEventListener("input", () => {
    state.modelFilter = els.modelSearch.value;
    state.modelActiveIndex = -1;
    // Typing invalidates a previous pick until the user chooses again.
    if (state.selectedModel && els.modelSearch.value !== state.selectedModel) {
      state.selectedModel = "";
      els.createChatBtn.disabled = true;
      els.modelSelected.textContent = "";
    }
    els.modelClear.hidden = !els.modelSearch.value;
    renderModelOptions();
  });

  els.modelSearch.addEventListener("focus", () => {
    if (state.models.length) renderModelOptions();
  });

  els.modelSearch.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveModelSelection(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveModelSelection(-1);
    } else if (event.key === "Enter") {
      const matches = filteredModels();
      if (!els.modelOptions.hidden && matches.length) {
        event.preventDefault();
        const index =
          state.modelActiveIndex >= 0 ? state.modelActiveIndex : 0;
        selectModel(matches[index].id);
      }
    } else if (event.key === "Escape") {
      closeModelOptions();
    }
  });

  els.modelOptions.addEventListener("click", (event) => {
    const option = event.target.closest("[data-model-index]");
    if (!option) return;
    const matches = filteredModels();
    const model = matches[Number(option.dataset.modelIndex)];
    if (model) selectModel(model.id);
  });

  els.modelClear.addEventListener("click", () => {
    els.modelSearch.value = "";
    state.modelFilter = "";
    state.selectedModel = "";
    state.modelActiveIndex = -1;
    els.modelClear.hidden = true;
    els.modelSelected.textContent = "";
    els.createChatBtn.disabled = true;
    els.modelSearch.focus();
    renderModelOptions();
  });

  // Clicking outside the combobox closes the dropdown.
  document.addEventListener("click", (event) => {
    if (!els.modelCombo.contains(event.target)) closeModelOptions();
  });
  els.memorySaveBtn.addEventListener("click", saveMemoryEntry);
  els.newChatBtn.addEventListener("click", handleNewChat);
  els.createChatBtn.addEventListener("click", handleCreateChat);
  els.confirmOkBtn.addEventListener("click", confirmDeleteChat);
  els.regenerateBtn.addEventListener("click", handleRegenerate);

  window.addEventListener("beforeunload", saveScroll);

  // ------------------------------------------------------------------- init
  async function init() {
    await loadSettings();
    await loadChats();

    if (state.chats.length) {
      await openChat(state.chats[0].id);
    } else {
      state.view = "empty";
      render();
    }
  }

  init();
})();