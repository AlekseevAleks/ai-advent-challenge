const form = document.getElementById("chat-form");
const promptField = document.getElementById("prompt");
const expertsField = document.getElementById("experts");
const sendButton = document.getElementById("send");
const pipelineStatus = document.getElementById("pipeline-status");
const resultsEl = document.getElementById("results");

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

function metaRows(data) {
  const settings = data.settings || {};
  return [
    ["Токены", formatTokens(data.usage)],
    ["Модель", settings.model || data.model || "—"],
    ["Temperature", settings.temperature ?? "—"],
    ["System prompt", settings.system_prompt || "—"],
    ["Request prompt", data.request_prompt || "—"],
    ["Endpoint", settings.endpoint || "—"],
  ];
}

function renderMeta(data) {
  const dl = document.createElement("dl");
  dl.className = "meta";
  for (const [label, value] of metaRows(data)) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = String(value);
    dl.append(dt, dd);
  }
  return dl;
}

function appendResult({ title, body, data, extra }) {
  const article = document.createElement("article");
  article.className = "result";

  const heading = document.createElement("h2");
  heading.textContent = title;
  article.append(heading);

  if (extra) {
    const note = document.createElement("p");
    note.className = "prompt-used";
    note.textContent = extra;
    article.append(note);
  }

  const pre = document.createElement("pre");
  pre.textContent = body;
  article.append(pre);

  if (data) article.append(renderMeta(data));
  resultsEl.append(article);
}

function parseExperts(raw) {
  return raw
    .split(/[\n,;]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function setStatus(text, isError = false) {
  pipelineStatus.classList.toggle("error", isError);
  pipelineStatus.textContent = text;
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
  return { ...data, request_prompt: data.request_prompt || prompt };
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const task = promptField.value.trim();
  if (!task) return;

  const experts = parseExperts(expertsField.value);
  sendButton.disabled = true;
  resultsEl.replaceChildren();
  setStatus("Запускаю цепочку запросов…");

  try {
    setStatus("1/5 · простой запрос");
    const direct = await askModel(task);
    appendResult({
      title: "Прямой ответ",
      body: direct.reply,
      data: direct,
    });

    setStatus("2/5 · решай пошагово");
    const stepwise = await askModel(`решай пошагово\n\n${task}`);
    appendResult({
      title: "Пошаговое решение",
      body: stepwise.reply,
      data: stepwise,
    });

    setStatus("3/5 · генерирую промт (на экран не выводится)");
    const invented = await askModel(
      [
        "Придумай промт для решения следующей задачи.",
        "Верни только текст промта, без заголовков и пояснений.",
        "",
        "Задача:",
        task,
      ].join("\n")
    );
    const generatedPrompt = invented.reply.trim();

    setStatus("4/5 · запрос с сгенерированным промтом");
    const withPrompt = await askModel(`${generatedPrompt}\n\nЗадача:\n${task}`);
    appendResult({
      title: "Ответ по сгенерированному промту",
      extra: `Использованный промт: ${generatedPrompt}`,
      body: withPrompt.reply,
      data: withPrompt,
    });

    if (!experts.length) {
      setStatus("Готово. Поле экспертов пустое — пятый шаг пропущен.");
      return;
    }

    for (let i = 0; i < experts.length; i += 1) {
      const expert = experts[i];
      setStatus(`5/5 · эксперт ${i + 1} из ${experts.length}: ${expert}`);
      const expertReply = await askModel(
        [
          `Ты эксперт: ${expert}.`,
          "Реши задачу с позиции этого эксперта. Дай самостоятельное решение.",
          "",
          "Задача:",
          task,
        ].join("\n")
      );
      appendResult({
        title: `Решение эксперта: ${expert}`,
        body: expertReply.reply,
        data: expertReply,
      });
    }

    setStatus("Готово. Все шаги выполнены по очереди.");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    sendButton.disabled = false;
  }
});
