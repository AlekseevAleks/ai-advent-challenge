const form = document.getElementById("chat-form");
const promptField = document.getElementById("prompt");
const formatField = document.getElementById("format");
const lengthField = document.getElementById("length");
const stopField = document.getElementById("stop");
const sendButton = document.getElementById("send");

const panes = {
  left: {
    status: document.getElementById("status-left"),
    answer: document.getElementById("answer-left"),
    meta: document.getElementById("meta-left"),
  },
  right: {
    status: document.getElementById("status-right"),
    answer: document.getElementById("answer-right"),
    meta: document.getElementById("meta-right"),
  },
};

function formatTokens(usage) {
  if (!usage || usage.total == null) {
    return "токены: нет данных";
  }
  const parts = [
    `всего ${usage.total}`,
    `вход ${usage.prompt ?? "—"}`,
    `выход ${usage.completion ?? "—"}`,
  ];
  if (usage.reasoning != null) parts.push(`рассуждение ${usage.reasoning}`);
  if (usage.cached != null) parts.push(`кэш ${usage.cached}`);
  return parts.join(" · ");
}

function renderMeta(metaEl, data) {
  const settings = data.settings || {};
  const rows = [
    ["Токены", formatTokens(data.usage)],
    ["Модель", settings.model || data.model || "—"],
    ["Temperature", settings.temperature ?? "—"],
    ["System prompt", settings.system_prompt || "—"],
    ["Endpoint", settings.endpoint || "—"],
  ];
  metaEl.replaceChildren(
    ...rows.flatMap(([label, value]) => {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = String(value);
      return [dt, dd];
    })
  );
  metaEl.hidden = false;
}

function resetPane(pane, loadingText) {
  pane.status.classList.remove("error");
  pane.status.textContent = loadingText;
  pane.answer.hidden = true;
  pane.answer.textContent = "";
  pane.meta.hidden = true;
  pane.meta.replaceChildren();
}

function showError(pane, message) {
  pane.status.classList.add("error");
  pane.status.textContent = message;
}

function showReply(pane, data) {
  pane.status.classList.remove("error");
  pane.status.textContent = `Ответ модели ${data.model}:`;
  pane.answer.hidden = false;
  pane.answer.textContent = data.reply;
  renderMeta(pane.meta, data);
}

function buildConstrainedPrompt(prompt) {
  const format = formatField.value.trim() || "не задано";
  const length = lengthField.value.trim() || "не задано";
  const stop = stopField.value.trim() || "не задано";
  return [
    prompt,
    "",
    "Дополнительные условия к ответу:",
    `Описание формата ответа: ${format}`,
    `Ограничение на длину ответа: ${length}`,
    `Условие завершения ответа: ${stop}`,
  ].join("\n");
}

async function askModel(prompt) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Не удалось получить ответ.");
  }
  return data;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = promptField.value.trim();
  if (!prompt) return;

  sendButton.disabled = true;
  resetPane(panes.left, "Отправляю запрос…");
  resetPane(panes.right, "Отправляю запрос с условиями…");

  const leftRun = askModel(prompt)
    .then((data) => showReply(panes.left, data))
    .catch((error) => showError(panes.left, error.message));

  const rightRun = askModel(buildConstrainedPrompt(prompt))
    .then((data) => showReply(panes.right, data))
    .catch((error) => showError(panes.right, error.message));

  await Promise.allSettled([leftRun, rightRun]);
  sendButton.disabled = false;
});
