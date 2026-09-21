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
    view: "empty", // empty | chat | settings | memory | rules
    streaming: false,
    abortController: null,
    pendingDeleteId: null,
    memory: null,
    taskState: null,
    taskStepRefreshing: false,
    invariants: [],
    editingInvariantId: null,
    // Task State Rules page: the configurable lifecycle.
    taskStates: [],
    transitionRules: [],
    initialTaskState: "",
    finalTaskStates: [],
    editingTaskStateId: null,
    editingRuleId: null,
    ruleConditionDraft: [],
    availableTransitions: null,
    taskFacts: null,
    transitionHistory: [],
    transitionNotice: null,
    profile: null,
    profiles: [],
    activeProfileId: null,
    editingMemoryId: null,
    editingProfileId: null,
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
    rulesBtn: document.getElementById("rulesBtn"),
    newChatBtn: document.getElementById("newChatBtn"),
    chatList: document.getElementById("chatList"),
    chatTitle: document.getElementById("chatTitle"),
    chatMeta: document.getElementById("chatMeta"),
    regenerateBtn: document.getElementById("regenerateBtn"),
    memoryToggle: document.getElementById("memoryToggle"),
    profileSwitch: document.getElementById("profileSwitch"),
    profileSwitchBtn: document.getElementById("profileSwitchBtn"),
    profileSwitchName: document.getElementById("profileSwitchName"),
    profileSwitchMenu: document.getElementById("profileSwitchMenu"),
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
      els.profileSwitch.hidden = false;
    } else if (state.view === "settings") {
      els.chatTitle.textContent = "Настройки";
      els.chatMeta.textContent = "API Base URL и API Key";
      els.regenerateBtn.hidden = true;
      els.memoryToggle.hidden = true;
      els.profileSwitch.hidden = true;
      els.profileSwitch.hidden = true;
    } else if (state.view === "memory") {
      els.chatTitle.textContent = "Память агента";
      els.chatMeta.textContent = state.activeChat
        ? `Чат: ${state.activeChat.title}`
        : "Три слоя памяти";
      els.regenerateBtn.hidden = true;
      els.memoryToggle.hidden = true;
      els.profileSwitch.hidden = true;
    } else if (state.view === "rules") {
      els.chatTitle.textContent = "Task State Rules";
      els.chatMeta.textContent = "Состояния, переходы и условия";
      els.regenerateBtn.hidden = true;
      els.memoryToggle.hidden = true;
      els.profileSwitch.hidden = true;
    } else {
      els.chatTitle.textContent = "AI Chat";
      els.chatMeta.textContent = "";
      els.regenerateBtn.hidden = true;
      els.memoryToggle.hidden = true;
      els.profileSwitch.hidden = true;
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

  //: The backend prefixes a conflict answer with this sentence.
  const CONFLICT_MARKER = "запрос конфликтует с активным инвариантом";
  //: ...and a lifecycle refusal with this one.
  const TRANSITION_BLOCKED_MARKER =
    "он требует перехода, который запрещён правилами жизненного цикла";

  function isConflictMessage(message) {
    return (
      message.role === "assistant" &&
      typeof message.content === "string" &&
      message.content.toLowerCase().includes(CONFLICT_MARKER)
    );
  }

  function isTransitionBlockedMessage(message) {
    return (
      message.role === "assistant" &&
      typeof message.content === "string" &&
      message.content.toLowerCase().includes(TRANSITION_BLOCKED_MARKER)
    );
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

    const conflict = isConflictMessage(message);
    const blocked = !conflict && isTransitionBlockedMessage(message);
    const wrapper = document.createElement("div");
    wrapper.className = `message message--${message.role}${
      conflict ? " message--conflict" : blocked ? " message--blocked" : ""
    }`;
    wrapper.dataset.messageId = message.id || "";

    const actions =
      message.role === "assistant" && !streaming
        ? `<div class="message__actions">
             <button class="message__action" data-copy-message title="Копировать ответ">Копировать</button>
           </div>`
        : "";

    wrapper.innerHTML = `
      <div class="message__avatar">${
        conflict || blocked ? "⚠" : initials
      }</div>
      <div class="message__body">
        <div class="message__head">
          <span class="message__author">${author}</span>
          ${
            conflict
              ? '<span class="message__conflict-badge">⚠ Constraint conflict</span>'
              : blocked
              ? '<span class="message__conflict-badge">⚠ Transition blocked</span>'
              : ""
          }
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
            <h3 class="card__title">User Profile</h3>
            <p class="card__text">
              Как ассистент должен отвечать. Профиль подключается к каждому
              запросу автоматически и хранится отдельно от памяти агента.
            </p>
            <div id="profileForm"></div>
          </div>

          <div class="card">
            <h3 class="card__title">Invariants</h3>
            <p class="card__text">
              Обязательные ограничения проекта. Ассистент не предлагает решения,
              нарушающие активные инварианты, и не меняет их без явной просьбы.
            </p>
            <div id="invariantForm"></div>
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

    renderProfileForm();
    renderInvariantForm();
  }

  // -------------------------------------------------------------- invariants
  const INVARIANT_CATEGORIES = [
    ["architecture", "architecture — архитектура"],
    ["technology", "technology — технологии"],
    ["business", "business — бизнес-правила"],
    ["security", "security — безопасность"],
    ["design", "design — дизайн"],
    ["technical_decision", "technical_decision — технические решения"],
    ["constraint", "constraint — ограничения"],
    ["other", "other — прочее"],
  ];

  const INVARIANT_PRIORITIES = [
    ["critical", "critical — критично"],
    ["high", "high — высокий"],
    ["medium", "medium — средний"],
    ["low", "low — низкий"],
  ];

  function invariantSelect(id, label, options, value) {
    return `<label class="field">
      <span class="field__label">${escapeHtml(label)}</span>
      <select class="input" id="${id}">
        ${options
          .map(
            ([optionValue, optionLabel]) =>
              `<option value="${escapeHtml(optionValue)}"${
                optionValue === value ? " selected" : ""
              }>${escapeHtml(optionLabel)}</option>`
          )
          .join("")}
      </select>
    </label>`;
  }

  function renderInvariantForm() {
    const container = document.getElementById("invariantForm");
    if (!container) return;

    const editing = state.editingInvariantId
      ? state.invariants.find((item) => item.id === state.editingInvariantId)
      : null;
    const data = (editing && editing.data) || {};

    const rows = state.invariants.length
      ? state.invariants
          .map(
            (item) => `<div class="invariant-row${
              item.data.status === "active" ? " is-active" : " is-inactive"
            }">
              <div class="invariant-row__body">
                <div class="invariant-row__head">
                  <span class="invariant-row__mark">${
                    item.data.status === "active" ? "✓" : "○"
                  }</span>
                  <span class="invariant-row__category">${escapeHtml(
                    item.data.category
                  )}</span>
                  <span class="invariant-row__priority invariant-row__priority--${escapeHtml(
                    item.data.priority
                  )}">${escapeHtml(item.data.priority)}</span>
                  <span class="invariant-row__scope">${escapeHtml(
                    item.data.scope
                  )}</span>
                </div>
                <div class="invariant-row__rule">${escapeHtml(
                  item.data.rule
                )}</div>
                ${
                  item.data.description
                    ? `<div class="invariant-row__desc">${escapeHtml(
                        item.data.description
                      )}</div>`
                    : ""
                }
              </div>
              <div class="invariant-row__actions">
                <button class="message__action" data-toggle-invariant="${escapeHtml(
                  item.id
                )}">${
              item.data.status === "active" ? "Deactivate" : "Activate"
            }</button>
                <button class="message__action" data-edit-invariant="${escapeHtml(
                  item.id
                )}">Edit</button>
                <button class="message__action" data-delete-invariant="${escapeHtml(
                  item.id
                )}">Delete</button>
              </div>
            </div>`
          )
          .join("")
      : `<div class="memory-empty">Активных инвариантов нет. Добавьте первое ограничение.</div>`;

    container.innerHTML = `
      <div class="invariant-list">${rows}</div>

      <div class="settings__actions" style="margin-top:14px">
        <button class="btn btn--primary" data-action="create-invariant">Добавить инвариант</button>
      </div>

      ${
        editing
          ? `<div class="invariant-editor">
              <h4 class="card__title" style="margin-top:20px">
                Редактирование инварианта
              </h4>
              <label class="field">
                <span class="field__label">Правило</span>
                <input class="input" id="invariantRule" type="text"
                  value="${escapeHtml(data.rule || "")}"
                  placeholder="Не использовать Redis" />
              </label>
              <label class="field">
                <span class="field__label">Описание</span>
                <input class="input" id="invariantDescription" type="text"
                  value="${escapeHtml(data.description || "")}"
                  placeholder="Почему это ограничение принято" />
              </label>
              ${invariantSelect(
                "invariantCategory",
                "Категория",
                INVARIANT_CATEGORIES,
                data.category
              )}
              ${invariantSelect(
                "invariantPriority",
                "Приоритет",
                INVARIANT_PRIORITIES,
                data.priority
              )}
              <div class="settings__actions">
                <button class="btn btn--primary" data-action="save-invariant">Сохранить</button>
                <button class="btn btn--ghost" data-action="cancel-invariant">Отмена</button>
              </div>
            </div>`
          : ""
      }`;
  }

  async function loadInvariants() {
    try {
      const payload = await api("/api/invariants");
      state.invariants = payload.invariants || [];
    } catch (error) {
      state.invariants = [];
      toast(error.message, "error");
    }
  }

  function openInvariantEditor(invariantId) {
    state.editingInvariantId = invariantId;
    renderInvariantForm();
  }

  async function createInvariant() {
    const rule = window.prompt("Правило инварианта:", "Не использовать Redis");
    if (!rule || !rule.trim()) return;
    try {
      await api("/api/invariants", {
        method: "POST",
        body: JSON.stringify({
          scope: "global",
          category: "constraint",
          rule: rule.trim(),
          priority: "high",
        }),
      });
      await loadInvariants();
      renderInvariantForm();
      toast("Инвариант создан и активен.", "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function saveInvariant() {
    const invariantId = state.editingInvariantId;
    if (!invariantId) return;
    const rule = document.getElementById("invariantRule").value.trim();
    if (!rule) {
      toast("Правило не может быть пустым.", "error");
      return;
    }
    try {
      await api(`/api/invariants/${invariantId}`, {
        method: "PUT",
        body: JSON.stringify({
          rule,
          description: document.getElementById("invariantDescription").value.trim(),
          category: document.getElementById("invariantCategory").value,
          priority: document.getElementById("invariantPriority").value,
        }),
      });
      state.editingInvariantId = null;
      await loadInvariants();
      renderInvariantForm();
      toast("Инвариант сохранён.", "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function toggleInvariant(invariantId) {
    const invariant = state.invariants.find((item) => item.id === invariantId);
    if (!invariant) return;
    const action = invariant.data.status === "active" ? "deactivate" : "activate";
    try {
      await api(`/api/invariants/${invariantId}/${action}`, { method: "POST" });
      await loadInvariants();
      renderInvariantForm();
      toast(
        action === "activate"
          ? "Инвариант активирован."
          : "Инвариант деактивирован (правило сохранено).",
        "success",
        3000
      );
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function deleteInvariant(invariantId) {
    const invariant = state.invariants.find((item) => item.id === invariantId);
    const label = invariant ? invariant.data.rule : invariantId;
    if (!window.confirm(`Удалить инвариант «${label}»?`)) return;
    try {
      await api(`/api/invariants/${invariantId}`, { method: "DELETE" });
      if (state.editingInvariantId === invariantId) {
        state.editingInvariantId = null;
      }
      await loadInvariants();
      renderInvariantForm();
      toast("Инвариант удалён.", "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  // ------------------------------------------------------------ user profile
  const PROFILE_OPTIONS = {
    language: [
      ["auto", "Как в сообщении пользователя"],
      ["ru", "Русский"],
      ["en", "English"],
    ],
    style: [
      ["concise", "concise — кратко, без воды"],
      ["balanced", "balanced — достаточно деталей"],
      ["detailed", "detailed — подробно, с примерами"],
      ["professional", "professional — деловой тон, без эмодзи"],
    ],
    format: [
      ["markdown", "markdown — заголовки, списки, код"],
      ["plain", "plain — без разметки"],
      ["step_by_step", "step_by_step — пошагово"],
      ["structured", "structured — разделы и выводы"],
    ],
    technical_level: [
      ["beginner", "beginner — объяснять термины"],
      ["intermediate", "intermediate — средний уровень"],
      ["advanced", "advanced — плотно, без основ"],
    ],
  };

  function profileSelect(id, label, options, value) {
    return `<label class="field">
      <span class="field__label">${escapeHtml(label)}</span>
      <select class="input" id="${id}">
        ${options
          .map(
            ([optionValue, optionLabel]) =>
              `<option value="${escapeHtml(optionValue)}"${
                optionValue === value ? " selected" : ""
              }>${escapeHtml(optionLabel)}</option>`
          )
          .join("")}
      </select>
    </label>`;
  }

  function profileSummaryLine(profile) {
    const language = { auto: "Auto", ru: "Russian", en: "English" };
    return [
      profile.technical_level.charAt(0).toUpperCase() +
        profile.technical_level.slice(1),
      language[profile.language] || profile.language,
      profile.style.charAt(0).toUpperCase() + profile.style.slice(1),
    ].join(" · ");
  }

  // ------------------------------------------------------- profile switcher
  function renderProfileSwitcher() {
    const active = state.profiles.find(
      (profile) => profile.id === state.activeProfileId
    );
    els.profileSwitchName.textContent = active
      ? active.name || active.id
      : "—";
  }

  function renderProfileMenu() {
    const menu = els.profileSwitchMenu;
    menu.innerHTML = `
      ${state.profiles
        .map(
          (profile) => `<button class="profile-switch__item${
            profile.id === state.activeProfileId ? " is-active" : ""
          }" data-switch-profile="${escapeHtml(profile.id)}" role="option"
            aria-selected="${profile.id === state.activeProfileId}">
            <span class="profile-switch__check">${
              profile.id === state.activeProfileId ? "✓" : ""
            }</span>
            <span class="profile-switch__item-body">
              <span class="profile-switch__item-name">${escapeHtml(
                profile.name || profile.id
              )}</span>
              <span class="profile-switch__item-meta">${escapeHtml(
                profileSummaryLine(profile)
              )}</span>
            </span>
          </button>`
        )
        .join("")}
      <div class="profile-switch__divider"></div>
      <button class="profile-switch__item" data-action="create-profile">
        <span class="profile-switch__check">＋</span>
        <span class="profile-switch__item-body">
          <span class="profile-switch__item-name">Create profile</span>
        </span>
      </button>
      <button class="profile-switch__item" data-action="manage-profiles">
        <span class="profile-switch__check">⚙</span>
        <span class="profile-switch__item-body">
          <span class="profile-switch__item-name">Manage profiles</span>
        </span>
      </button>`;
  }

  function toggleProfileMenu(force) {
    const next =
      typeof force === "boolean" ? force : els.profileSwitchMenu.hidden;
    if (next) renderProfileMenu();
    els.profileSwitchMenu.hidden = !next;
    els.profileSwitchBtn.setAttribute("aria-expanded", String(next));
  }

  async function switchProfile(profileId) {
    try {
      await api(`/api/profiles/${profileId}/activate`, { method: "POST" });
      state.activeProfileId = profileId;
      await loadProfiles();
      renderProfileSwitcher();
      toggleProfileMenu(false);
      const active = state.profiles.find((p) => p.id === profileId);
      toast(
        `Активный профиль: ${active ? active.name || active.id : profileId}. Применяется к следующему запросу.`,
        "success",
        4000
      );
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function loadProfiles() {
    try {
      const payload = await api("/api/profiles");
      state.profiles = payload.profiles || [];
      state.activeProfileId = payload.active_profile_id;
    } catch (error) {
      state.profiles = [];
      toast(error.message, "error");
    }
  }

  // -------------------------------------------------------- profile manager
  function renderProfileForm() {
    const container = document.getElementById("profileForm");
    if (!container) return;

    const editing = state.editingProfileId
      ? state.profiles.find((p) => p.id === state.editingProfileId)
      : null;
    const profile = editing ? state.profile : null;
    const data = (profile && profile.data) || {};

    container.innerHTML = `
      <div class="profile-list">
        ${state.profiles
          .map(
            (item) => `<div class="profile-row${
              item.id === state.activeProfileId ? " is-active" : ""
            }">
              <div class="profile-row__body">
                <div class="profile-row__name">
                  ${item.id === state.activeProfileId ? "✓ " : ""}${escapeHtml(
              item.name || item.id
            )}
                </div>
                <div class="profile-row__meta">${escapeHtml(
                  profileSummaryLine(item)
                )}</div>
                ${
                  item.description
                    ? `<div class="profile-row__desc">${escapeHtml(
                        item.description
                      )}</div>`
                    : ""
                }
              </div>
              <div class="profile-row__actions">
                ${
                  item.id === state.activeProfileId
                    ? `<span class="profile-row__badge">активный</span>`
                    : `<button class="message__action" data-activate-profile="${escapeHtml(
                        item.id
                      )}">Activate</button>`
                }
                <button class="message__action" data-edit-profile="${escapeHtml(
                  item.id
                )}">Edit</button>
                <button class="message__action" data-duplicate-profile="${escapeHtml(
                  item.id
                )}">Duplicate</button>
                <button class="message__action" data-delete-profile="${escapeHtml(
                  item.id
                )}">Delete</button>
              </div>
            </div>`
          )
          .join("")}
      </div>

      <div class="settings__actions" style="margin-top:14px">
        <button class="btn btn--primary" data-action="create-profile">Создать профиль</button>
      </div>

      <div class="profile-editor" id="profileEditor">
        ${
          editing
            ? `
          <h4 class="card__title" style="margin-top:20px">
            Редактирование: ${escapeHtml(editing.name || editing.id)}
          </h4>
          <label class="field">
            <span class="field__label">Название</span>
            <input class="input" id="profileName" type="text"
              value="${escapeHtml(editing.name || "")}" />
          </label>
          <label class="field">
            <span class="field__label">Описание</span>
            <input class="input" id="profileDescription" type="text"
              value="${escapeHtml(editing.description || "")}"
              placeholder="Например: для рабочих задач" />
          </label>
          ${profileSelect("profileLanguage", "Язык ответа", PROFILE_OPTIONS.language, data.language)}
          ${profileSelect("profileStyle", "Стиль", PROFILE_OPTIONS.style, data.style)}
          ${profileSelect("profileFormat", "Формат", PROFILE_OPTIONS.format, data.format)}
          ${profileSelect(
            "profileLevel",
            "Технический уровень",
            PROFILE_OPTIONS.technical_level,
            data.technical_level
          )}
          <label class="field">
            <span class="field__label">Предпочтения (по одному в строке)</span>
            <textarea class="input" id="profilePreferences" rows="3"
              placeholder="Prefer code examples">${escapeHtml(
                (data.preferences || []).join("\n")
              )}</textarea>
          </label>
          <label class="field">
            <span class="field__label">Ограничения (по одному в строке)</span>
            <textarea class="input" id="profileConstraints" rows="3"
              placeholder="Explain terminology">${escapeHtml(
                (data.constraints || []).join("\n")
              )}</textarea>
          </label>
          <label class="field">
            <span class="field__label">Custom instructions</span>
            <textarea class="input" id="profileInstructions" rows="3"
              placeholder="Дополнительные указания для модели">${escapeHtml(
                data.custom_instructions || ""
              )}</textarea>
          </label>
          <div class="settings__actions">
            <button class="btn btn--primary" id="saveProfileBtn">Сохранить</button>
            <button class="btn btn--ghost" id="cancelProfileBtn">Отмена</button>
          </div>
          <div class="memory-field" style="margin-top:14px">
            <span class="memory-field__label">Что уходит в prompt</span>
            <pre class="memory-prompt" id="profilePromptBlock">${escapeHtml(
              state.profileBlock || "Профиль без персонализации — блок пуст."
            )}</pre>
          </div>`
            : `<div class="memory-empty" style="margin-top:16px">
                Выберите профиль и нажмите Edit, чтобы изменить настройки.
              </div>`
        }
      </div>`;

    const saveBtn = document.getElementById("saveProfileBtn");
    if (saveBtn) saveBtn.addEventListener("click", saveProfile);
    const cancelBtn = document.getElementById("cancelProfileBtn");
    if (cancelBtn) {
      cancelBtn.addEventListener("click", () => {
        state.editingProfileId = null;
        state.profile = null;
        state.profileBlock = "";
        renderProfileForm();
      });
    }
  }

  function splitLines(id) {
    const node = document.getElementById(id);
    if (!node) return [];
    return node.value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  }

  async function loadProfile() {
    try {
      state.profile = await api("/api/profile/active");
      const block = await api("/api/profile/prompt-block");
      state.profileBlock = block.block || "";
    } catch (error) {
      state.profile = null;
      state.profileBlock = "";
      toast(error.message, "error");
    }
  }

  async function editProfile(profileId) {
    state.editingProfileId = profileId;
    await loadProfile();
    state.profile = await api(`/api/profiles/${profileId}`);
    const block = await api(
      `/api/profile/prompt-block?profile_id=${encodeURIComponent(profileId)}`
    );
    state.profileBlock = block.block || "";
    renderProfileForm();
  }

  async function saveProfile() {
    const profileId = state.editingProfileId;
    if (!profileId) return;

    const payload = {
      name: document.getElementById("profileName").value.trim(),
      description: document.getElementById("profileDescription").value.trim(),
      data: {
        language: document.getElementById("profileLanguage").value,
        style: document.getElementById("profileStyle").value,
        format: document.getElementById("profileFormat").value,
        technical_level: document.getElementById("profileLevel").value,
        preferences: splitLines("profilePreferences"),
        constraints: splitLines("profileConstraints"),
        custom_instructions: document
          .getElementById("profileInstructions")
          .value.trim(),
      },
    };

    if (!payload.name) {
      toast("Укажите название профиля.", "error");
      return;
    }

    try {
      await api(`/api/profiles/${profileId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      await loadProfiles();
      await editProfile(profileId);
      renderProfileSwitcher();
      toast("Профиль сохранён.", "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function createProfile() {
    const name = window.prompt("Название нового профиля:", "Новый профиль");
    if (!name || !name.trim()) return;
    try {
      const created = await api("/api/profiles", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      await loadProfiles();
      await editProfile(created.id);
      renderProfileSwitcher();
      toast(`Профиль «${created.name}» создан.`, "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function duplicateProfile(profileId) {
    try {
      const copy = await api(`/api/profiles/${profileId}/duplicate`, {
        method: "POST",
      });
      await loadProfiles();
      renderProfileForm();
      renderProfileSwitcher();
      toast(`Создана копия: ${copy.name}.`, "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function deleteProfile(profileId) {
    const profile = state.profiles.find((p) => p.id === profileId);
    const label = profile ? profile.name || profile.id : profileId;
    if (!window.confirm(`Удалить профиль «${label}»?`)) return;
    try {
      await api(`/api/profiles/${profileId}`, { method: "DELETE" });
      if (state.editingProfileId === profileId) {
        state.editingProfileId = null;
        state.profile = null;
      }
      await loadProfiles();
      renderProfileForm();
      renderProfileSwitcher();
      toast("Профиль удалён.", "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  // ------------------------------------------------------- task state rules
  // The lifecycle is configuration, not code: the user defines the states and
  // the rules between them here, and the backend loads them from the database
  // on every transition, so a change applies without a restart.

  const CONDITION_TYPES = [
    ["field_equals", "field_equals — поле равно значению"],
    ["field_not_equals", "field_not_equals — поле не равно значению"],
    ["field_not_empty", "field_not_empty — поле заполнено"],
    ["field_empty", "field_empty — поле пусто"],
    ["boolean_true", "boolean_true — флаг включён"],
    ["boolean_false", "boolean_false — флаг выключен"],
  ];

  function conditionSummary(condition) {
    if (!condition) return "";
    if (condition.type === "field_equals") {
      return `${condition.field} == ${condition.value}`;
    }
    if (condition.type === "field_not_equals") {
      return `${condition.field} != ${condition.value}`;
    }
    if (condition.type === "field_not_empty") {
      return `${condition.field} заполнено`;
    }
    if (condition.type === "field_empty") return `${condition.field} пусто`;
    if (condition.type === "boolean_true") {
      return `${condition.field} == true`;
    }
    if (condition.type === "boolean_false") {
      return `${condition.field} == false`;
    }
    return condition.type;
  }

  function ruleConditionText(rule) {
    const conditions = rule.conditions || [];
    if (conditions.length) {
      return conditions.map(conditionSummary).join(" И ");
    }
    return rule.condition || "";
  }

  function stateLabel(stateId) {
    const found = state.taskStates.find((item) => item.id === stateId);
    return found ? found.name || found.id : stateId;
  }

  // A readable list view of the machine: from → to, with the condition.
  function transitionGraphHtml() {
    if (!state.transitionRules.length) {
      return `<div class="memory-empty">Правил переходов нет. Добавьте первое правило.</div>`;
    }
    return `<div class="transition-graph">${state.transitionRules
      .map((rule) => {
        const condition = ruleConditionText(rule) || "нет дополнительных условий";
        return `<div class="transition-edge${
          rule.active ? "" : " is-inactive"
        }">
          <div class="transition-edge__states">
            <span class="transition-edge__state">${escapeHtml(
              stateLabel(rule.from_state)
            )}</span>
            <span class="transition-edge__arrow">↓</span>
            <span class="transition-edge__state">${escapeHtml(
              stateLabel(rule.to_state)
            )}</span>
          </div>
          <div class="transition-edge__body">
            <div class="transition-edge__name">${escapeHtml(
              rule.name || `${rule.from_state} → ${rule.to_state}`
            )}</div>
            <div class="transition-edge__condition">Condition: ${escapeHtml(
              condition
            )}</div>
            <div class="transition-edge__status">Status: ${
              rule.active ? "Active" : "Inactive"
            }</div>
          </div>
        </div>`;
      })
      .join("")}</div>`;
  }

  function taskStatesHtml() {
    if (!state.taskStates.length) {
      return `<div class="memory-empty">Состояний нет.</div>`;
    }
    return `<div class="state-list">${state.taskStates
      .map(
        (item) => `<div class="state-row${item.active ? "" : " is-inactive"}">
          <div class="state-row__body">
            <div class="state-row__name">
              ${escapeHtml(item.name || item.id)}
              ${
                item.is_initial
                  ? '<span class="state-row__badge">initial</span>'
                  : ""
              }
              ${
                item.is_final
                  ? '<span class="state-row__badge state-row__badge--final">final</span>'
                  : ""
              }
              ${
                item.active
                  ? ""
                  : '<span class="state-row__badge state-row__badge--off">inactive</span>'
              }
            </div>
            <div class="state-row__meta">id: ${escapeHtml(item.id)}</div>
            ${
              item.description
                ? `<div class="state-row__desc">${escapeHtml(
                    item.description
                  )}</div>`
                : ""
            }
          </div>
          <div class="state-row__actions">
            <button class="message__action" data-edit-task-state="${escapeHtml(
              item.id
            )}">Edit</button>
            <button class="message__action" data-toggle-task-state="${escapeHtml(
              item.id
            )}">${item.active ? "Deactivate" : "Activate"}</button>
            <button class="message__action" data-delete-task-state="${escapeHtml(
              item.id
            )}">Delete</button>
          </div>
        </div>`
      )
      .join("")}</div>`;
  }

  function transitionRulesHtml() {
    if (!state.transitionRules.length) {
      return `<div class="memory-empty">Правил переходов нет.</div>`;
    }
    return `<div class="rule-list">${state.transitionRules
      .map(
        (rule) => `<div class="rule-row${rule.active ? "" : " is-inactive"}">
          <div class="rule-row__body">
            <div class="rule-row__head">
              <span class="rule-row__mark">${rule.active ? "✓" : "○"}</span>
              <span class="rule-row__edge">${escapeHtml(
                stateLabel(rule.from_state)
              )} → ${escapeHtml(stateLabel(rule.to_state))}</span>
            </div>
            ${
              rule.name
                ? `<div class="rule-row__name">${escapeHtml(rule.name)}</div>`
                : ""
            }
            <div class="rule-row__condition">Condition: ${escapeHtml(
              ruleConditionText(rule) || "нет дополнительных условий"
            )}</div>
            ${
              rule.description
                ? `<div class="rule-row__desc">${escapeHtml(
                    rule.description
                  )}</div>`
                : ""
            }
          </div>
          <div class="rule-row__actions">
            <button class="message__action" data-check-rule="${escapeHtml(
              rule.id
            )}">Проверить</button>
            <button class="message__action" data-edit-rule="${escapeHtml(
              rule.id
            )}">Edit</button>
            <button class="message__action" data-toggle-rule="${escapeHtml(
              rule.id
            )}">${rule.active ? "Deactivate" : "Activate"}</button>
            <button class="message__action" data-delete-rule="${escapeHtml(
              rule.id
            )}">Delete</button>
          </div>
        </div>`
      )
      .join("")}</div>`;
  }

  function conditionEditorHtml() {
    const draft = state.ruleConditionDraft || [];
    const rows = draft
      .map(
        (condition, index) => `<div class="condition-row">
          <select class="input condition-row__type" data-condition-type="${index}">
            ${CONDITION_TYPES.map(
              ([value, label]) =>
                `<option value="${escapeHtml(value)}"${
                  value === condition.type ? " selected" : ""
                }>${escapeHtml(label)}</option>`
            ).join("")}
          </select>
          <input class="input condition-row__field" type="text"
            data-condition-field="${index}"
            placeholder="поле, например plan_status"
            value="${escapeHtml(condition.field || "")}" />
          <input class="input condition-row__value" type="text"
            data-condition-value="${index}"
            placeholder="значение, например approved"
            value="${escapeHtml(condition.value || "")}" />
          <button class="message__action" data-remove-condition="${index}">✕</button>
        </div>`
      )
      .join("");

    return `<div class="condition-editor">
      <div class="field__label">Условия перехода (все должны выполняться)</div>
      ${rows || '<div class="memory-note">Условий нет — переход разрешён всегда.</div>'}
      <div class="settings__actions" style="margin-top:8px">
        <button class="btn btn--ghost" data-action="add-condition">Добавить условие</button>
      </div>
    </div>`;
  }

  function renderTaskStateRules() {
    const editingState = state.editingTaskStateId
      ? state.taskStates.find((item) => item.id === state.editingTaskStateId)
      : null;
    const editingRule = state.editingRuleId
      ? state.transitionRules.find((item) => item.id === state.editingRuleId)
      : null;
    const ruleData = editingRule || {};

    const stateOptions = state.taskStates
      .map(
        (item) =>
          `<option value="${escapeHtml(item.id)}">${escapeHtml(
            item.name || item.id
          )}</option>`
      )
      .join("");

    const notice = state.transitionNotice;
    const noticeHtml = notice
      ? `<div class="test-result ${
          notice.ok ? "is-ok" : "is-bad"
        }">${escapeHtml(notice.text)}</div>`
      : "";

    els.view.innerHTML = `
      <div class="settings">
        <div class="settings__inner">
          <h2 class="settings__title">Task State Rules</h2>
          <p class="settings__subtitle">
            Жизненный цикл задачи: какие состояния существуют и какие переходы
            между ними разрешены. AI сам определяет момент перехода, но
            TransitionManager применяет только те правила, что настроены здесь.
            Изменения действуют сразу, без перезапуска.
          </p>

          <div class="card">
            <h3 class="card__title">States</h3>
            <p class="card__text">
              Начальное состояние — то, в котором создаётся новая задача.
              Финальное — то, где задача считается завершённой.
            </p>
            ${taskStatesHtml()}
            <div class="settings__actions" style="margin-top:14px">
              <button class="btn btn--primary" data-action="create-task-state">Создать состояние</button>
            </div>
            ${
              editingState
                ? `<div class="state-editor">
                    <h4 class="card__title" style="margin-top:20px">
                      Редактирование состояния: ${escapeHtml(
                        editingState.name || editingState.id
                      )}
                    </h4>
                    <label class="field">
                      <span class="field__label">Название</span>
                      <input class="input" id="taskStateName" type="text"
                        value="${escapeHtml(editingState.name || "")}" />
                    </label>
                    <label class="field">
                      <span class="field__label">Описание</span>
                      <input class="input" id="taskStateDescription" type="text"
                        value="${escapeHtml(editingState.description || "")}"
                        placeholder="Проверка результата" />
                    </label>
                    <label class="field field--inline">
                      <input type="checkbox" id="taskStateInitial" ${
                        editingState.is_initial ? "checked" : ""
                      } />
                      <span>Initial state</span>
                    </label>
                    <label class="field field--inline">
                      <input type="checkbox" id="taskStateFinal" ${
                        editingState.is_final ? "checked" : ""
                      } />
                      <span>Final state</span>
                    </label>
                    <label class="field field--inline">
                      <input type="checkbox" id="taskStateActive" ${
                        editingState.active ? "checked" : ""
                      } />
                      <span>Active</span>
                    </label>
                    <div class="settings__actions">
                      <button class="btn btn--primary" data-action="save-task-state">Сохранить</button>
                      <button class="btn btn--ghost" data-action="cancel-task-state">Отмена</button>
                    </div>
                  </div>`
                : ""
            }
          </div>

          <div class="card">
            <h3 class="card__title">Allowed Transitions</h3>
            <p class="card__text">
              Из какого состояния → в какое → при каком условии можно перейти.
            </p>
            ${transitionGraphHtml()}
            <div class="settings__actions" style="margin-top:14px">
              <button class="btn btn--primary" data-action="create-rule">Создать правило</button>
            </div>
            ${noticeHtml}
            ${
              editingRule
                ? `<div class="rule-editor">
                    <h4 class="card__title" style="margin-top:20px">
                      Редактирование правила
                    </h4>
                    <label class="field">
                      <span class="field__label">From state</span>
                      <select class="input" id="ruleFrom">${stateOptions}</select>
                    </label>
                    <label class="field">
                      <span class="field__label">To state</span>
                      <select class="input" id="ruleTo">${stateOptions}</select>
                    </label>
                    <label class="field">
                      <span class="field__label">Name</span>
                      <input class="input" id="ruleName" type="text"
                        value="${escapeHtml(ruleData.name || "")}"
                        placeholder="Start implementation" />
                    </label>
                    <label class="field">
                      <span class="field__label">Description</span>
                      <input class="input" id="ruleDescription" type="text"
                        value="${escapeHtml(ruleData.description || "")}" />
                    </label>
                    <label class="field">
                      <span class="field__label">Condition (текстом, для чтения)</span>
                      <input class="input" id="ruleCondition" type="text"
                        value="${escapeHtml(ruleData.condition || "")}"
                        placeholder="Plan must be approved" />
                    </label>
                    ${conditionEditorHtml()}
                    <label class="field field--inline">
                      <input type="checkbox" id="ruleActive" ${
                        ruleData.active === false ? "" : "checked"
                      } />
                      <span>Active</span>
                    </label>
                    <div class="settings__actions">
                      <button class="btn btn--primary" data-action="save-rule">Сохранить</button>
                      <button class="btn btn--ghost" data-action="cancel-rule">Отмена</button>
                    </div>
                  </div>`
                : ""
            }
          </div>

          <div class="card">
            <h3 class="card__title">Правила переходов</h3>
            <p class="card__text">
              Список правил с условиями. «Проверить» показывает, выполняется ли
              условие сейчас.
            </p>
            ${transitionRulesHtml()}
          </div>
        </div>
      </div>`;

    if (editingRule) {
      const fromSelect = document.getElementById("ruleFrom");
      const toSelect = document.getElementById("ruleTo");
      if (fromSelect) fromSelect.value = ruleData.from_state || "";
      if (toSelect) toSelect.value = ruleData.to_state || "";
    }
  }

  async function loadTaskStateRules() {
    try {
      const [states, rules] = await Promise.all([
        api("/api/task-states"),
        api("/api/transition-rules"),
      ]);
      state.taskStates = states.states || [];
      state.initialTaskState = states.initial_state || "";
      state.finalTaskStates = states.final_states || [];
      state.transitionRules = rules.rules || [];
    } catch (error) {
      state.taskStates = [];
      state.transitionRules = [];
      toast(error.message, "error");
    }
  }

  async function openTaskStateRules() {
    state.view = "rules";
    state.editingTaskStateId = null;
    state.editingRuleId = null;
    state.ruleConditionDraft = [];
    state.transitionNotice = null;
    closeSidebar();
    render();
    await loadTaskStateRules();
    render();
  }

  function openTaskStateEditor(stateId) {
    state.editingTaskStateId = stateId;
    state.editingRuleId = null;
    renderTaskStateRules();
  }

  function openRuleEditor(ruleId) {
    const rule = state.transitionRules.find((item) => item.id === ruleId);
    state.editingRuleId = ruleId;
    state.editingTaskStateId = null;
    state.ruleConditionDraft = rule
      ? (rule.conditions || []).map((condition) => ({ ...condition }))
      : [];
    state.transitionNotice = null;
    renderTaskStateRules();
  }

  async function createTaskStateDefinition() {
    const name = window.prompt("Название состояния:", "Review");
    if (!name || !name.trim()) return;
    try {
      await api("/api/task-states", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      await loadTaskStateRules();
      renderTaskStateRules();
      toast("Состояние создано.", "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function saveTaskStateDefinition() {
    const stateId = state.editingTaskStateId;
    if (!stateId) return;
    const name = document.getElementById("taskStateName").value.trim();
    if (!name) {
      toast("Название не может быть пустым.", "error");
      return;
    }
    try {
      await api(`/api/task-states/${stateId}`, {
        method: "PUT",
        body: JSON.stringify({
          name,
          description: document
            .getElementById("taskStateDescription")
            .value.trim(),
          is_initial: document.getElementById("taskStateInitial").checked,
          is_final: document.getElementById("taskStateFinal").checked,
          active: document.getElementById("taskStateActive").checked,
        }),
      });
      state.editingTaskStateId = null;
      await loadTaskStateRules();
      renderTaskStateRules();
      toast("Состояние сохранено.", "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function toggleTaskStateDefinition(stateId) {
    const item = state.taskStates.find((entry) => entry.id === stateId);
    if (!item) return;
    try {
      await api(`/api/task-states/${stateId}`, {
        method: "PUT",
        body: JSON.stringify({ active: !item.active }),
      });
      await loadTaskStateRules();
      renderTaskStateRules();
      toast(
        item.active ? "Состояние деактивировано." : "Состояние активировано.",
        "success",
        3000
      );
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function deleteTaskStateDefinition(stateId) {
    if (!window.confirm(`Удалить состояние «${stateId}»?`)) return;
    try {
      await api(`/api/task-states/${stateId}`, { method: "DELETE" });
      if (state.editingTaskStateId === stateId) state.editingTaskStateId = null;
      await loadTaskStateRules();
      renderTaskStateRules();
      toast("Состояние удалено.", "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function createTransitionRule() {
    if (state.taskStates.length < 2) {
      toast("Нужно минимум два состояния.", "error");
      return;
    }
    state.editingRuleId = "new";
    state.editingTaskStateId = null;
    state.ruleConditionDraft = [];
    state.transitionNotice = null;
    renderTaskStateRules();
  }

  async function saveTransitionRule() {
    const ruleId = state.editingRuleId;
    if (!ruleId) return;

    const payload = {
      from_state: document.getElementById("ruleFrom").value,
      to_state: document.getElementById("ruleTo").value,
      name: document.getElementById("ruleName").value.trim(),
      description: document.getElementById("ruleDescription").value.trim(),
      condition: document.getElementById("ruleCondition").value.trim(),
      conditions: state.ruleConditionDraft,
      active: document.getElementById("ruleActive").checked,
    };

    try {
      if (ruleId === "new") {
        await api("/api/transition-rules", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      } else {
        await api(`/api/transition-rules/${ruleId}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
      }
      state.editingRuleId = null;
      state.ruleConditionDraft = [];
      await loadTaskStateRules();
      renderTaskStateRules();
      toast("Правило сохранено. Применяется к следующему переходу.", "success", 4000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function toggleTransitionRule(ruleId) {
    const rule = state.transitionRules.find((item) => item.id === ruleId);
    if (!rule) return;
    const action = rule.active ? "deactivate" : "activate";
    try {
      await api(`/api/transition-rules/${ruleId}/${action}`, { method: "POST" });
      await loadTaskStateRules();
      renderTaskStateRules();
      toast(
        action === "activate"
          ? "Правило активировано."
          : "Правило деактивировано (переход больше не разрешён).",
        "success",
        4000
      );
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function deleteTransitionRule(ruleId) {
    if (!window.confirm("Удалить правило перехода?")) return;
    try {
      await api(`/api/transition-rules/${ruleId}`, { method: "DELETE" });
      if (state.editingRuleId === ruleId) state.editingRuleId = null;
      await loadTaskStateRules();
      renderTaskStateRules();
      toast("Правило удалено.", "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function checkTransitionRule(ruleId) {
    try {
      const result = await api(`/api/transition-rules/${ruleId}/check`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      const parts = [];
      if (result.satisfied) {
        parts.push(
          `Условие выполнено: ${result.condition || "нет дополнительных условий"}.`
        );
      } else {
        parts.push(`Условие не выполнено: ${result.condition}.`);
        if (result.actual) parts.push(`Текущее значение: ${result.actual}.`);
      }
      // A rule that reads a fact nothing sets can never fire; say so here,
      // where the rule is configured, rather than only when it blocks a
      // request.
      const missing = result.missing_fields || [];
      if (missing.length) {
        parts.push(
          `Правило читает факты, которых нет у задачи: ${missing.join(", ")}. ` +
            "Задайте их в блоке Task state (кнопка «Изменить факты»), иначе " +
            "переход не выполнится."
        );
      }
      state.transitionNotice = {
        ok: result.satisfied && !missing.length,
        text: parts.join(" "),
      };
      renderTaskStateRules();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function addConditionDraft() {
    state.ruleConditionDraft = [
      ...(state.ruleConditionDraft || []),
      { type: "field_equals", field: "", value: "" },
    ];
    renderTaskStateRules();
  }

  function removeConditionDraft(index) {
    state.ruleConditionDraft = (state.ruleConditionDraft || []).filter(
      (_, position) => position !== index
    );
    renderTaskStateRules();
  }

  function syncConditionDraftFromInputs() {
    const draft = state.ruleConditionDraft || [];
    draft.forEach((condition, index) => {
      const typeNode = document.querySelector(`[data-condition-type="${index}"]`);
      const fieldNode = document.querySelector(
        `[data-condition-field="${index}"]`
      );
      const valueNode = document.querySelector(
        `[data-condition-value="${index}"]`
      );
      if (typeNode) condition.type = typeNode.value;
      if (fieldNode) condition.field = fieldNode.value.trim();
      if (valueNode) condition.value = valueNode.value.trim();
    });
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
      ${taskStateBlockHtml()}

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

  // ------------------------------------------------------------- task state
  function taskStateBlockHtml() {
    const taskState = state.taskState;
    if (!taskState || !taskState.exists) {
      return `<div class="memory-panel__section">
        <div class="memory-panel__title">Task state</div>
        <div class="memory-empty">
          Задача не создана. Состояние появится, когда вы опишете задачу.
        </div>
        <div class="settings__actions">
          <button class="btn btn--ghost" data-action="create-task">Создать задачу</button>
        </div>
      </div>`;
    }

    const data = taskState.data || {};
    const stages = (taskState.progress || [])
      .map(
        (item) => `<span class="task-stage task-stage--${item.marker}">
          ${item.marker === "done" ? "✓" : item.marker === "current" ? "●" : "○"}
          ${escapeHtml(item.label)}
        </span>`
      )
      .join("");

    const paused = data.status === "paused";
    const completed = data.status === "completed" || data.stage === "done";

    return `<div class="memory-panel__section task-state">
      <div class="memory-panel__title">
        Task state
        <span class="task-status task-status--${escapeHtml(data.status)}">
          ${escapeHtml(data.status)}
        </span>
      </div>

      <div class="task-stages">${stages}</div>

      <div class="memory-grid">
        ${memoryField("Stage", data.stage)}
        ${memoryField("Current step", data.current_step)}
        ${memoryField("Expected action", data.expected_action)}
      </div>
      ${
        state.taskStepRefreshing
          ? `<div class="memory-note task-step-refreshing">
              Пересчитываю шаг по диалогу…
            </div>`
          : ""
      }
      ${
        paused && data.pause_reason
          ? `<div class="memory-note">Причина паузы: ${escapeHtml(
              data.pause_reason
            )}</div>`
          : ""
      }
      ${
        data.completed_steps && data.completed_steps.length
          ? `<div class="memory-field">
              <span class="memory-field__label">Выполнено</span>
              ${memoryList(data.completed_steps)}
            </div>`
          : ""
      }

      ${taskFactsHtml()}

      ${availableTransitionsHtml()}

      <div class="settings__actions">
        ${
          completed
            ? `<span class="memory-note">Задача завершена.</span>`
            : paused
            ? `<button class="btn btn--primary" data-action="resume-task">Resume</button>`
            : `<button class="btn btn--ghost" data-action="pause-task">Pause</button>
               <button class="btn btn--ghost" data-action="complete-task">Done</button>`
        }
        <button class="btn btn--ghost" data-action="refresh-task-step">Пересчитать шаг</button>
        <button class="btn btn--ghost" data-action="edit-task">Изменить шаг</button>
      </div>
    </div>`;
  }

  // The facts transition conditions are checked against. Facts are read from
  // the user's own messages, so the panel shows both the values and where they
  // came from; a fact the rules need but the task lacks is called out, because
  // a condition on it can never hold.
  function taskFactsHtml() {
    const facts = state.taskFacts;
    if (!facts) return "";

    const missing = facts.missing || [];
    const extracted = new Set(facts.extracted || []);
    const entries = Object.entries(facts.facts || {}).filter(
      ([key]) => !["stage", "status", "current_step", "expected_action"].includes(key)
    );

    const rows = entries.length
      ? entries
          .map(
            ([key, value]) => `<div class="fact-row">
              <span class="fact-row__key">${escapeHtml(key)}</span>
              <span class="fact-row__value">${escapeHtml(value)}</span>
              ${
                extracted.has(key)
                  ? '<span class="fact-row__badge fact-row__badge--auto">из сообщения</span>'
                  : ""
              }
            </div>`
          )
          .join("")
      : `<div class="memory-note">Факты не заданы.</div>`;

    const missingHtml = missing.length
      ? `<div class="fact-warning">
          Условия правил читают факты, которых у задачи нет:
          ${missing.map((name) => `<code>${escapeHtml(name)}</code>`).join(", ")}.
          Они определятся автоматически, когда вы напишете об этом в чате, —
          или задайте их вручную.
        </div>`
      : "";

    return `<div class="task-facts">
      <div class="memory-field__label">Факты задачи</div>
      ${rows}
      ${missingHtml}
      <div class="settings__actions" style="margin-top:8px">
        <button class="btn btn--ghost" data-action="edit-facts">Изменить факты</button>
      </div>
    </div>`;
  }

  // The moves the configured lifecycle allows from the current stage. A move
  // whose condition does not hold is shown as unavailable, with the reason.
  function availableTransitionsHtml() {
    const available = state.availableTransitions;
    if (!available || !available.transitions.length) {
      return `<div class="memory-note">
        Разрешённых переходов нет. Настройте их на странице Task State Rules.
      </div>`;
    }

    const rows = available.transitions
      .map(
        (item) => `<div class="available-transition${
          item.allowed ? "" : " is-blocked"
        }">
          <div class="available-transition__body">
            <div class="available-transition__target">
              ${item.allowed ? "→" : "✕"} ${escapeHtml(
          stateLabel(item.to_state)
        )}
            </div>
            <div class="available-transition__condition">${escapeHtml(
              item.condition || "нет дополнительных условий"
            )}</div>
            ${
              item.allowed
                ? ""
                : `<div class="available-transition__reason">${escapeHtml(
                    item.reason
                  )}${
                    item.actual
                      ? ` Текущее значение: ${escapeHtml(item.actual)}.`
                      : ""
                  }</div>`
            }
          </div>
          ${
            item.allowed
              ? `<button class="btn btn--ghost" data-action="transition-task"
                   data-target="${escapeHtml(item.to_state)}">Перейти</button>`
              : ""
          }
        </div>`
      )
      .join("");

    return `<div class="available-transitions">
      <div class="memory-field__label">Available transitions</div>
      ${rows}
    </div>`;
  }

  async function loadAvailableTransitions() {
    if (!state.activeChatId) {
      state.availableTransitions = null;
      return;
    }
    try {
      state.availableTransitions = await api(
        `/api/tasks/${state.activeChatId}/available-transitions`
      );
    } catch (error) {
      state.availableTransitions = null;
    }
  }

  async function transitionTaskTo(target) {
    if (!state.activeChatId || !target) return;
    try {
      const outcome = await api(
        `/api/tasks/${state.activeChatId}/transitions/apply`,
        {
          method: "POST",
          body: JSON.stringify({ to_state: target, trigger: "user" }),
        }
      );
      if (outcome.allowed) {
        toast(
          `Переход выполнен: ${outcome.from_state} → ${outcome.to_state}.`,
          "success",
          4000
        );
      } else {
        toast(
          `Переход недоступен. ${outcome.reason}${
            outcome.actual ? ` Текущее значение: ${outcome.actual}.` : ""
          }`,
          "error",
          7000
        );
      }
      await refreshTaskState();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function loadTaskState() {
    if (!state.activeChatId) {
      state.taskState = null;
      state.availableTransitions = null;
      state.taskFacts = null;
      return;
    }
    try {
      state.taskState = await api(`/api/tasks/${state.activeChatId}/state`);
    } catch (error) {
      state.taskState = null;
    }
    await loadAvailableTransitions();
    await loadTaskFacts();
  }

  async function loadTaskFacts() {
    if (!state.activeChatId) {
      state.taskFacts = null;
      return;
    }
    try {
      state.taskFacts = await api(`/api/tasks/${state.activeChatId}/facts`);
    } catch (error) {
      state.taskFacts = null;
    }
  }

  async function pollTaskStep(attempts = 6, delayMs = 1500) {
    if (!state.activeChatId) return;
    const before = state.taskState && state.taskState.data
      ? `${state.taskState.data.current_step}|${state.taskState.data.expected_action}`
      : "";

    state.taskStepRefreshing = true;
    renderMemoryPanel();

    for (let attempt = 0; attempt < attempts; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      await loadTaskState();
      const data = state.taskState && state.taskState.data;
      const after = data ? `${data.current_step}|${data.expected_action}` : "";
      if (after !== before) break;
    }

    state.taskStepRefreshing = false;
    renderMemoryPanel();
  }

  async function refreshTaskStep() {
    if (!state.activeChatId) return;
    state.taskStepRefreshing = true;
    renderMemoryPanel();
    try {
      await api(`/api/tasks/${state.activeChatId}/refresh-step`, {
        method: "POST",
      });
      await loadTaskState();
      toast("Шаг задачи пересчитан по диалогу.", "success", 3000);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      state.taskStepRefreshing = false;
      renderMemoryPanel();
    }
  }

  async function refreshTaskState() {
    await loadTaskState();
    renderMemoryPanel();
  }

  async function createTaskState() {
    if (!state.activeChatId) return;
    try {
      await api(`/api/tasks/${state.activeChatId}/state`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      toast("Задача создана: этап planning.", "success", 3000);
      await refreshTaskState();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function pauseTask() {
    if (!state.activeChatId) return;
    try {
      await api(`/api/tasks/${state.activeChatId}/pause`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      toast("Задача поставлена на паузу. Состояние сохранено.", "success", 4000);
      await refreshTaskState();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function resumeTask() {
    if (!state.activeChatId) return;
    try {
      const result = await api(`/api/tasks/${state.activeChatId}/resume`, {
        method: "POST",
      });
      const data = result.data || {};
      toast(
        `Продолжаем этап ${data.stage}. Шаг: ${data.current_step || "—"}.`,
        "success",
        5000
      );
      await refreshTaskState();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function completeTask() {
    if (!state.activeChatId) return;
    try {
      await api(`/api/tasks/${state.activeChatId}/complete`, { method: "POST" });
      toast("Задача завершена.", "success", 3000);
      await refreshTaskState();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function openTaskEditor() {
    const data = (state.taskState && state.taskState.data) || {};
    els.view.innerHTML = `
      <div class="settings">
        <div class="settings__inner">
          <h2 class="settings__title">Состояние задачи</h2>
          <p class="settings__subtitle">
            Этап и статус меняются только через разрешённые переходы
            (Pause / Resume / Done), поэтому здесь редактируются только шаг и
            ожидаемое действие.
          </p>
          <div class="card">
            <label class="field">
              <span class="field__label">Текущий шаг</span>
              <input class="input" id="taskStep" type="text"
                value="${escapeHtml(data.current_step || "")}" />
            </label>
            <label class="field">
              <span class="field__label">Ожидаемое действие</span>
              <input class="input" id="taskExpected" type="text"
                value="${escapeHtml(data.expected_action || "")}" />
            </label>
            <div class="settings__actions">
              <button class="btn btn--primary" data-action="save-task">Сохранить</button>
              <button class="btn btn--ghost" data-action="open-memory">Отмена</button>
            </div>
          </div>
        </div>
      </div>`;
  }

  function openFactsEditor() {
    const facts = state.taskFacts || { facts: {}, missing: [] };
    const values = facts.facts || {};
    const missing = facts.missing || [];

    // The fields the rules need come first, so a missing fact is one click
    // away from being filled in.
    const names = [];
    missing.forEach((name) => {
      if (!names.includes(name)) names.push(name);
    });
    Object.keys(values).forEach((name) => {
      if (
        !names.includes(name) &&
        !["stage", "status", "current_step", "expected_action"].includes(name)
      ) {
        names.push(name);
      }
    });

    const rows = names.length
      ? names
          .map(
            (name) => `<label class="field">
              <span class="field__label">
                ${escapeHtml(name)}${
              missing.includes(name)
                ? ' <span class="fact-row__badge">нужен правилу</span>'
                : ""
            }
              </span>
              <input class="input" data-fact-name="${escapeHtml(name)}"
                type="text" value="${escapeHtml(values[name] || "")}"
                placeholder="значение" />
            </label>`
          )
          .join("")
      : `<div class="memory-empty">
          Правила не читают ни одного факта. Добавьте условие на странице
          Task State Rules, и нужные поля появятся здесь.
        </div>`;

    els.view.innerHTML = `
      <div class="settings">
        <div class="settings__inner">
          <h2 class="settings__title">Факты задачи</h2>
          <p class="settings__subtitle">
            Значения, против которых проверяются условия переходов. Например,
            условие <code>plan_status == approved</code> выполнится, когда факт
            <code>plan_status</code> равен <code>approved</code>. Пустое поле
            очищает факт.
          </p>
          <div class="card">
            ${rows}
            <label class="field">
              <span class="field__label">Новый факт (имя)</span>
              <input class="input" id="newFactName" type="text"
                placeholder="например plan_status" />
            </label>
            <label class="field">
              <span class="field__label">Значение нового факта</span>
              <input class="input" id="newFactValue" type="text"
                placeholder="например approved" />
            </label>
            <div class="settings__actions">
              <button class="btn btn--primary" data-action="save-facts">Сохранить</button>
              <button class="btn btn--ghost" data-action="open-memory">Отмена</button>
            </div>
          </div>
        </div>
      </div>`;
  }

  async function saveTaskFacts() {
    if (!state.activeChatId) return;

    const facts = {};
    document.querySelectorAll("[data-fact-name]").forEach((node) => {
      facts[node.dataset.factName] = node.value.trim();
    });

    const newName = document.getElementById("newFactName").value.trim();
    const newValue = document.getElementById("newFactValue").value.trim();
    if (newName) facts[newName] = newValue;

    try {
      state.taskFacts = await api(`/api/tasks/${state.activeChatId}/facts`, {
        method: "PUT",
        body: JSON.stringify({ facts }),
      });
      toast("Факты задачи сохранены.", "success", 3000);
      await openMemory();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function saveTaskState() {
    if (!state.activeChatId) return;
    try {
      await api(`/api/tasks/${state.activeChatId}/state`, {
        method: "PUT",
        body: JSON.stringify({
          current_step: document.getElementById("taskStep").value.trim(),
          expected_action: document.getElementById("taskExpected").value.trim(),
        }),
      });
      toast("Состояние задачи обновлено.", "success", 3000);
      await openMemory();
    } catch (error) {
      toast(error.message, "error");
    }
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
    await loadTaskState();
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
    } else if (state.view === "rules") {
      renderTaskStateRules();
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
      toggleProfileMenu(false);
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
    Promise.all([loadProfiles(), loadProfile(), loadInvariants()]).then(() => {
      renderProfileForm();
      renderProfileSwitcher();
      renderInvariantForm();
    });
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

  function stopStreaming() {
    if (state.abortController) {
      state.abortController.abort();
      state.abortController = null;
    }
    state.streaming = false;
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
      updateSendButton();

      if (!failed && received) {
        state.messages.push(assistantMessage);
      }

      // After the answer is complete, always jump to the newest message.
      scrollToBottom(true);

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
        // The step is recomputed in the background after the reply, so poll
        // briefly until it changes (or give up after a few attempts).
        await pollTaskStep();
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
      if (name === "create-profile") createProfile();
      if (name === "create-invariant") createInvariant();
      if (name === "save-invariant") saveInvariant();
      if (name === "cancel-invariant") {
        state.editingInvariantId = null;
        renderInvariantForm();
      }
      if (name === "create-task") createTaskState();
      if (name === "pause-task") pauseTask();
      if (name === "resume-task") resumeTask();
      if (name === "complete-task") completeTask();
      if (name === "edit-task") openTaskEditor();
      if (name === "refresh-task-step") refreshTaskStep();
      if (name === "save-task") saveTaskState();
      if (name === "edit-facts") openFactsEditor();
      if (name === "save-facts") saveTaskFacts();
      if (name === "manage-profiles") {
        toggleProfileMenu(false);
        openSettings();
      }
      if (name === "create-task-state") createTaskStateDefinition();
      if (name === "save-task-state") saveTaskStateDefinition();
      if (name === "cancel-task-state") {
        state.editingTaskStateId = null;
        renderTaskStateRules();
      }
      if (name === "create-rule") createTransitionRule();
      if (name === "save-rule") {
        syncConditionDraftFromInputs();
        saveTransitionRule();
      }
      if (name === "cancel-rule") {
        state.editingRuleId = null;
        state.ruleConditionDraft = [];
        state.transitionNotice = null;
        renderTaskStateRules();
      }
      if (name === "add-condition") {
        syncConditionDraftFromInputs();
        addConditionDraft();
      }
      if (name === "transition-task") transitionTaskTo(action.dataset.target);
      return;
    }

    const editTaskStateBtn = event.target.closest("[data-edit-task-state]");
    if (editTaskStateBtn) {
      openTaskStateEditor(editTaskStateBtn.dataset.editTaskState);
      return;
    }

    const toggleTaskStateBtn = event.target.closest("[data-toggle-task-state]");
    if (toggleTaskStateBtn) {
      await toggleTaskStateDefinition(toggleTaskStateBtn.dataset.toggleTaskState);
      return;
    }

    const deleteTaskStateBtn = event.target.closest("[data-delete-task-state]");
    if (deleteTaskStateBtn) {
      await deleteTaskStateDefinition(
        deleteTaskStateBtn.dataset.deleteTaskState
      );
      return;
    }

    const editRuleBtn = event.target.closest("[data-edit-rule]");
    if (editRuleBtn) {
      openRuleEditor(editRuleBtn.dataset.editRule);
      return;
    }

    const toggleRuleBtn = event.target.closest("[data-toggle-rule]");
    if (toggleRuleBtn) {
      await toggleTransitionRule(toggleRuleBtn.dataset.toggleRule);
      return;
    }

    const deleteRuleBtn = event.target.closest("[data-delete-rule]");
    if (deleteRuleBtn) {
      await deleteTransitionRule(deleteRuleBtn.dataset.deleteRule);
      return;
    }

    const checkRuleBtn = event.target.closest("[data-check-rule]");
    if (checkRuleBtn) {
      await checkTransitionRule(checkRuleBtn.dataset.checkRule);
      return;
    }

    const removeConditionBtn = event.target.closest("[data-remove-condition]");
    if (removeConditionBtn) {
      syncConditionDraftFromInputs();
      removeConditionDraft(Number(removeConditionBtn.dataset.removeCondition));
      return;
    }

    const activateProfile = event.target.closest("[data-activate-profile]");
    if (activateProfile) {
      await switchProfile(activateProfile.dataset.activateProfile);
      renderProfileForm();
      return;
    }

    const toggleInvariantBtn = event.target.closest("[data-toggle-invariant]");
    if (toggleInvariantBtn) {
      await toggleInvariant(toggleInvariantBtn.dataset.toggleInvariant);
      return;
    }

    const editInvariantBtn = event.target.closest("[data-edit-invariant]");
    if (editInvariantBtn) {
      openInvariantEditor(editInvariantBtn.dataset.editInvariant);
      return;
    }

    const deleteInvariantBtn = event.target.closest("[data-delete-invariant]");
    if (deleteInvariantBtn) {
      await deleteInvariant(deleteInvariantBtn.dataset.deleteInvariant);
      return;
    }

    const editProfileBtn = event.target.closest("[data-edit-profile]");
    if (editProfileBtn) {
      await editProfile(editProfileBtn.dataset.editProfile);
      return;
    }

    const duplicateBtn = event.target.closest("[data-duplicate-profile]");
    if (duplicateBtn) {
      await duplicateProfile(duplicateBtn.dataset.duplicateProfile);
      return;
    }

    const deleteProfileBtn = event.target.closest("[data-delete-profile]");
    if (deleteProfileBtn) {
      await deleteProfile(deleteProfileBtn.dataset.deleteProfile);
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
  els.rulesBtn.addEventListener("click", openTaskStateRules);
  els.memoryToggle.addEventListener("click", () => toggleMemoryPanel());
  els.profileSwitchBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleProfileMenu();
  });

  els.profileSwitchMenu.addEventListener("click", async (event) => {
    const switchTo = event.target.closest("[data-switch-profile]");
    if (switchTo) {
      await switchProfile(switchTo.dataset.switchProfile);
      return;
    }
    const action = event.target.closest("[data-action]");
    if (!action) return;
    if (action.dataset.action === "create-profile") {
      toggleProfileMenu(false);
      await createProfile();
    }
    if (action.dataset.action === "manage-profiles") {
      toggleProfileMenu(false);
      openSettings();
    }
  });

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
    if (!els.profileSwitch.contains(event.target)) toggleProfileMenu(false);
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
    await loadProfiles();
    renderProfileSwitcher();
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