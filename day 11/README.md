# Local AI Chat

Локальное приложение для общения с LLM через любой **OpenAI-compatible API**.
Работает на вашем компьютере: Python-бэкенд (FastAPI) + веб-интерфейс в браузере.

* Никакой регистрации и внешних баз данных.
* Base URL и API Key указываете сами — они хранятся локально.
* Список моделей всегда загружается из вашего API (ничего не зашито в код).
* Чаты сохраняются между перезапусками (SQLite).
* Ответ модели отображается постепенно (streaming / SSE).
* **Три слоя памяти агента** (short-term / working / long-term) с явным
  решением о том, что и куда сохраняется — см. раздел
  [Memory Model](#memory-model).

```
Browser  →  FastAPI (локально)  →  OpenAI-compatible API
```

API Key никогда не попадает во frontend и не пишется в логи.

---

## 1. Требования

* Python **3.9+**
* Любой браузер
* Доступ к OpenAI-compatible API (например, `https://api.openai.com/v1`,
  `http://localhost:8000/v1` или ваш собственный сервер)

Frontend написан на чистых HTML/CSS/JS и не требует сборки — никаких `npm install`.

---

## 2. Установка

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

> **Если `pip` не найден** (`zsh: command not found: pip`): на macOS команда
> `pip` часто отсутствует в PATH — есть только `pip3`. Используйте
> `python -m pip` (внутри активированного окружения) или `python3 -m pip`.
> Вариант без активации окружения:
>
> ```bash
> python3 -m venv .venv
> .venv/bin/python -m pip install -r requirements.txt
> .venv/bin/python run.py
> ```

---

## 3. Запуск

```bash
python run.py
```

В консоли появится:

```
AI Chat started
Open http://127.0.0.1:8005
Data directory: /path/to/project/data
```

Браузер откроется автоматически.

Полезные флаги:

```bash
python run.py --no-browser        # не открывать браузер
python run.py --port 9000         # другой порт
python run.py --host 0.0.0.0      # слушать все интерфейсы
python run.py --reload            # автоперезагрузка для разработки
```

Запуск вручную через uvicorn:

```bash
uvicorn backend.main:app --reload
```

---

## 4. Настройка API

1. Нажмите **⚙ Настройки** в сайдбаре.
2. Заполните:
   * **API Base URL** — например `https://api.openai.com/v1`
   * **API Key** — например `sk-...`
3. Нажмите **Сохранить**.
4. Нажмите **Проверить подключение** — приложение запросит список моделей
   и покажет результат.

### Примеры Base URL

| Провайдер                | Base URL                          |
| ------------------------ | --------------------------------- |
| OpenAI                   | `https://api.openai.com/v1`       |
| Локальный сервер (vLLM)  | `http://localhost:8000/v1`        |
| Ollama (OpenAI-совместимый) | `http://localhost:11434/v1`    |
| LM Studio                | `http://localhost:1234/v1`        |
| Свой сервер              | `https://my-server.example/v1`    |

Провайдер не зашит в код — все запросы строятся относительно указанного Base URL.

---

## 5. Использование

* **＋ Новый чат** — модель выбирается через поле поиска с выпадающим списком:
  начните вводить название, стрелки — навигация, `Enter` — выбор. Список
  загружается из вашего API (у больших провайдеров это сотни моделей).
* **Отправка** — `Enter` отправляет, `Shift+Enter` переносит строку.
* Ответ появляется постепенно; кнопка **■** останавливает генерацию.
* **⟳** — повторная генерация последнего ответа.
* Название чата автоматически берётся из первого сообщения.
* Кнопки «Копировать» — для ответа и для каждого code block.
* **🗑** у чата в сайдбаре — удаление с подтверждением.
* **🧠 Память** — экран с тремя слоями памяти агента (см. раздел
  [Memory Model](#8-memory-model)).
* **🧠 в шапке чата** — та же память в виде панели справа от диалога: видно,
  что попало в каждый слой, не уходя с экрана чата. Панель обновляется после
  каждого ответа и запоминает своё состояние при переключении чатов.

---

## 6. Структура проекта

```
ai-chat/
├── backend/
│   ├── main.py                 # создание FastAPI-приложения, обработчики ошибок
│   ├── config.py               # системная конфигурация (host/port/пути)
│   ├── api/
│   │   ├── dependencies.py     # dependency injection
│   │   ├── settings.py         # /api/settings
│   │   ├── models.py           # /api/models
│   │   ├── chats.py            # /api/chats (+ SSE streaming)
│   │   └── memory.py           # /api/memory, /api/chats/{id}/memory/*
│   ├── memory/                 # модель памяти агента
│   │   ├── models.py           # схемы слоёв и результата извлечения
│   │   ├── short_term.py       # слой 1: текущий диалог
│   │   ├── working.py          # слой 2: состояние задачи
│   │   ├── long_term.py        # слой 3: профиль пользователя + валидация
│   │   ├── extractor.py        # MemoryExtractor: только предлагает
│   │   └── manager.py          # MemoryManager: решает и строит prompt
│   ├── models/                 # Pydantic-схемы (chat, message, settings)
│   ├── services/
│   │   ├── ai_client.py        # клиент OpenAI-compatible API
│   │   ├── chat_service.py     # логика чатов и сообщений
│   │   ├── memory_service.py   # связка памяти с приложением
│   │   └── settings_service.py # хранение настроек (data/config.json)
│   ├── database/
│   │   ├── database.py         # SQLite: подключение и схема
│   │   ├── repositories.py     # доступ к чатам и сообщениям
│   │   └── memory_repositories.py  # доступ к working / long-term
│   └── utils/                  # логирование с маскированием секретов, ошибки
├── frontend/
│   ├── index.html
│   └── static/{styles.css, app.js}
├── data/                       # создаётся автоматически, в git не попадает
│   ├── config.json             # настройки (chmod 600)
│   └── chat.db                 # чаты и сообщения
├── tests/                      # pytest
├── run.py                      # запуск одной командой
├── requirements.txt
└── README.md
```

---

## 7. API backend

| Метод  | Путь                                   | Описание                              |
| ------ | -------------------------------------- | ------------------------------------- |
| GET    | `/api/settings`                        | текущие настройки (ключ замаскирован) |
| PUT    | `/api/settings`                        | сохранить настройки                   |
| POST   | `/api/settings/test`                   | проверить подключение                 |
| GET    | `/api/models`                          | список моделей из API                 |
| GET    | `/api/chats`                           | список чатов                          |
| POST   | `/api/chats`                           | создать чат                           |
| GET    | `/api/chats/{chat_id}`                 | получить чат                          |
| PATCH  | `/api/chats/{chat_id}`                 | переименовать / сменить модель        |
| DELETE | `/api/chats/{chat_id}`                 | удалить чат и его сообщения           |
| GET    | `/api/chats/{chat_id}/messages`        | история сообщений                     |
| POST   | `/api/chats/{chat_id}/messages`        | отправить сообщение (обычный режим)   |
| POST   | `/api/chats/{chat_id}/messages/stream` | отправить сообщение (SSE streaming)   |
| POST   | `/api/chats/{chat_id}/regenerate`      | повторить последний ответ             |
| POST   | `/api/chats/{chat_id}/regenerate/stream` | повтор с streaming                  |
| GET    | `/api/memory`                          | все три слоя сразу (+ prompt preview)  |
| GET    | `/api/chats/{chat_id}/memory/short-term` | текущий диалог чата                  |
| GET    | `/api/chats/{chat_id}/memory/working`  | состояние задачи чата                 |
| PUT    | `/api/chats/{chat_id}/memory/working`  | перезаписать рабочую память           |
| DELETE | `/api/chats/{chat_id}/memory/working`  | очистить рабочую память               |
| POST   | `/api/chats/{chat_id}/memory/analyze`  | принудительный анализ памяти          |
| GET    | `/api/memory/long-term`                | долговременные факты                  |
| POST   | `/api/memory/long-term`                | добавить факт вручную                 |
| PUT    | `/api/memory/long-term/{memory_id}`    | изменить факт                         |
| DELETE | `/api/memory/long-term/{memory_id}`    | удалить факт                          |
| GET    | `/health`                              | health-check                          |

Интерактивная документация: `http://127.0.0.1:8005/docs`.

### Формат ошибок

Ошибки возвращаются в едином виде и без traceback:

```json
{
  "error": {
    "code": "api_auth_error",
    "message": "API отклонил запрос авторизации (401). Проверьте API Key."
  }
}
```

Обрабатываются: неверный API Key, неверный Base URL, недоступный сервер,
timeout, HTTP 400/401/403/404/429/500+, некорректный формат ответа,
пустой список моделей и сетевые ошибки.

### Streaming

`POST /api/chats/{chat_id}/messages/stream` возвращает `text/event-stream`
с событиями `user_message`, `delta`, `done`, `error`, `end`.
Если провайдер не поддерживает SSE, клиент автоматически переходит
в обычный режим.

---

## 8. Memory Model

У агента **три независимых слоя памяти**. Они отличаются не только таблицей,
но и назначением, временем жизни и ролью в prompt.

```
                    ┌─────────────────┐
                    │ User message    │
                    └────────┬────────┘
                             ↓
                    ┌─────────────────┐
                    │ Memory Extractor│   только предлагает, в БД не пишет
                    └────────┬────────┘
                             ↓
              ┌──────────────┼──────────────┐
              ↓              ↓              ↓
       Short-term       Working        Long-term
       current chat     task state     user profile
       (messages)       (working_      (long_term_
                         memory)        memory)
              │              │              │
              └──────────────┼──────────────┘
                             ↓
                       Prompt Builder
                             ↓
                            LLM
```

### 8.1 Short-term memory — текущий диалог

**Что хранит:** сообщения текущего чата (`user` / `assistant`).
**Зачем:** чтобы модель понимала, о чём идёт речь прямо сейчас.
**Где:** таблица `messages`, привязана к `chat_id`.
**Когда попадает:** каждое сообщение сохраняется сразу при отправке.
**Как используется:** как история диалога, обрезанная до последних
`MAX_CONTEXT_MESSAGES` (40) сообщений.
**Время жизни:** удаляется вместе с чатом.

### 8.2 Working memory — текущая задача

**Что хранит:** структурированное состояние задачи, а не переписку:

```json
{
  "task": "Разработка REST API интернет-магазина",
  "goal": "Создать backend интернет-магазина",
  "stack": ["Python", "FastAPI", "PostgreSQL"],
  "current_step": "Реализация корзины",
  "completed": ["Регистрация", "Авторизация", "JWT"],
  "constraints": ["Использовать async SQLAlchemy"],
  "decisions": ["Использовать JWT authentication"]
}
```

**Зачем:** чтобы на вопрос «что нам осталось сделать?» через 30 сообщений
агент отвечал из состояния задачи, а не перечитывал весь диалог.
**Где:** таблица `working_memory` (`chat_id` → JSON), одна запись на чат.
**Когда попадает:** когда extractor распознаёт в сообщении постановку задачи,
этап, ограничение или решение. Списки объединяются, скаляры перезаписываются.
**Как используется:** компактным текстовым блоком в system prompt.
**Время жизни:** удаляется вместе с чатом.

### 8.3 Long-term memory — профиль пользователя

**Что хранит:** устойчивые факты о пользователе и постоянные решения:

```
category: preference, key: preferred_language, value: Python
category: preference, key: response_style,     value: concise
category: decision,   key: auth_strategy,      value: JWT
```

**Зачем:** чтобы **новый чат** уже знал предпочтения пользователя.
**Где:** таблица `long_term_memory`, не привязана к чату.
**Когда попадает:** только если extractor предложил кандидата **и** он прошёл
валидацию (см. 8.5).
**Как используется:** блоком `## Long-term memory` в system prompt.
**Время жизни:** **не удаляется** при удалении чата — принадлежит пользователю.

### 8.4 Кто принимает решение о сохранении

Это ключевая часть модели: **extractor не пишет в базу**.

```
MemoryExtractor.extract(...)  →  MemoryExtractionResult
                                 ├── short_term: bool
                                 ├── working_memory: WorkingMemoryPatch | None
                                 └── long_term_candidates: [LongTermCandidate]

MemoryManager.analyze(...)    →  решает, что реально сохранить
                                 ├── save_to_short_term(...)
                                 ├── save_to_working_memory(...)
                                 └── long_term.accept_candidates(...)
```

`MemoryExtractor` (`backend/memory/extractor.py`) анализирует сообщение и
возвращает **кандидатов**. Он умеет работать двумя способами:

* `llm` — отдельный запрос к модели со строгой JSON-схемой (по умолчанию);
* `rules` — детерминированные эвристики, если API не настроен или модель
  вернула неразбираемый ответ.

`MemoryManager` (`backend/memory/manager.py`) — единственный, кто пишет в БД.

### 8.5 Правила: что НЕ попадает в long-term memory

LLM может ошибаться, поэтому кандидаты проходят валидацию
(`LongTermMemory.validate_candidate`):

| Правило | Пример отклонения |
| --- | --- |
| уверенность ниже `0.6` | `confidence = 0.2` |
| ключ относится к задаче | `current_step`, `task`, `todo` |
| значение не несёт смысла | `нет`, `unknown`, `n/a` |
| значение слишком длинное | > 500 символов |

Отклонённые кандидаты не теряются: они возвращаются в отчёте
(`long_term_rejected`) с причиной и видны в логах.

### 8.6 Как память попадает в prompt

`MemoryManager.build_messages()` собирает контекст в порядке
**long-term → working → short-term → текущее сообщение** и отдаёт его
компактным текстом, а не сырым JSON:

```
## Long-term memory

User preferences:
- Python
- FastAPI
- concise

## Working memory

Current task:
API интернет-магазина

Stack:
Python, FastAPI, PostgreSQL

Current step:
Авторизация
```

Дальше идёт обычная история сообщений этого чата.

### 8.7 Что происходит при создании и удалении чата

| Событие | Short-term | Working | Long-term |
| --- | --- | --- | --- |
| Новый чат | пусто | пусто | **виден** |
| Удаление чата | удаляется | удаляется | **сохраняется** |

Именно это демонстрирует разницу слоёв: новый чат получает профиль
пользователя, но не получает старую задачу и старый диалог.

### 8.8 Демонстрационный сценарий

| Пользователь говорит | Куда попадает |
| --- | --- |
| «Я предпочитаю Python и FastAPI» | Long-term: `preferred_language`, `preferred_framework` |
| «Сейчас мы разрабатываем API интернет-магазина» | Working: `task` |
| «Давай теперь сделаем авторизацию» | Short-term + Working: `current_step` |
| «Используем JWT в этом проекте» | Working: `decisions` |
| «Отвечай кратко» | Long-term: `response_style = concise` |

Одно сообщение может обновлять несколько слоёв — это и есть модель памяти,
а не три отдельные таблицы.

### 8.9 Логи памяти

Каждое решение видно в логах (API Key туда не попадает):

```
[MEMORY] Message analyzed (чат 3f2a...)
[MEMORY] Short-term: yes
[MEMORY] Working memory update: current_step = авторизацию
[MEMORY] Long-term candidate: preferred_framework = FastAPI (confidence 0.90)
[MEMORY] Long-term candidate accepted: preferred_framework = FastAPI
[MEMORY] Long-term candidate rejected: current_step = Авторизация (ключ относится к текущей задаче)
[MEMORY] Чат 3f2a... удалён: short-term и working очищены, long-term сохранена
```

### 8.10 Память в интерфейсе

Память доступна в двух местах, и оба используют одни и те же блоки разметки
(`shortTermBlockHtml` / `workingBlockHtml` / `longTermBlockHtml`), поэтому
не могут разойтись:

**1. Экран «Память»** — кнопка **🧠 Память** в сайдбаре. Полноразмерный экран
с тремя карточками и блоком «Что уходит в prompt».

**2. Панель в чате** — кнопка **🧠** в шапке чата. Та же информация справа от
диалога, чтобы видеть память, не покидая разговор:

* **Short-term** — сообщения текущего чата;
* **Working** — задача, этап, стек, выполнено, ограничения, решения
  (можно изменить или очистить);
* **Long-term** — факты с категорией, ключом, значением и источником
  (`llm` / `manual`); можно добавить, изменить и удалить запись;
* **Что уходит в prompt** — точный текст, который получит модель.

Панель обновляется после каждого ответа (анализ памяти выполняется после
генерации) и сохраняет открытое состояние при переключении чатов. На узких
экранах она превращается в накладку поверх диалога.

---

## 9. Хранение данных

* `data/config.json` — настройки, права `0600`, атомарная запись.
* `data/chat.db` — SQLite (WAL), таблицы `chats` и `messages`.

Директория `data/` создаётся автоматически и полностью исключена из git:
API Key не попадает в репозиторий. Также действует фильтр логирования,
маскирующий всё, что похоже на `Authorization: Bearer ...` или `sk-...`.

Схема БД:

```
chats:             id, title, model, created_at, updated_at
messages:          id, chat_id, role (system|user|assistant), content, created_at
working_memory:    chat_id, data (JSON), updated_at
long_term_memory:  id, category, key, value, source, confidence,
                   created_at, updated_at
```

`messages` — это short-term memory, `working_memory` — рабочая память,
`long_term_memory` — долговременная. Три отдельные таблицы с разной
структурой и разным временем жизни.

---

## 10. Тесты

```bash
python -m pytest
```

Тесты используют изолированную временную директорию данных и подменяют
HTTP-клиент, поэтому реальных сетевых запросов не делают. Покрыты: создание
и удаление чатов, сохранение настроек, получение моделей, отправка сообщений,
streaming, повторная генерация и обработка ошибок API.

Отдельный файл `tests/test_memory.py` проверяет модель памяти:

| Тест | Что доказывает |
| --- | --- |
| Test 1 | сообщение попадает в short-term текущего чата |
| Test 2 | постановка задачи попадает в working memory |
| Test 3 | предпочтение попадает в long-term memory |
| Test 4 | удаление чата чистит short-term и working, но не long-term |
| Test 5 | новый чат видит long-term, но не working старого чата |
| Test 6 | в prompt попадают все три слоя, компактным текстом |

Плюс проверяются правила валидации кандидатов, работа LLM-пути извлечения,
фолбэк на правила и CRUD по всем слоям.

---

## 11. Troubleshooting

**«Не удалось подключиться к API»**
Проверьте Base URL (должен заканчиваться на `/v1`), API Key и доступность сервера.

**401 / 403**
Неверный ключ или недостаточно прав. Сохраните ключ заново в настройках.

**404 на `/models`**
Сервер не поддерживает OpenAI-compatible endpoint `/models`
или Base URL указан без `/v1`.

**429**
Лимит запросов — подождите и повторите.

**`pip install` не находит пакеты / `command not found: pip`**
На macOS команды `pip` может не быть в PATH (есть только `pip3`).
Используйте `python -m pip` внутри активированного окружения или
`.venv/bin/python -m pip` без активации.

**Порт 8005 занят**
Запустите с другим портом: `python run.py --port 9000`.

**Нужно начать с чистого листа**
Остановите приложение и удалите `data/config.json` (настройки)
или `data/chat.db` (чаты).