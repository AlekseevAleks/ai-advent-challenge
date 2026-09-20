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
  [Memory Model](#8-memory-model).
* **Несколько профилей персонализации** с переключением: язык, стиль, формат,
  технический уровень и свои инструкции. Активный профиль подключается к
  каждому запросу автоматически — см. раздел [User Profile](#9-user-profile).
* **Состояние задачи как конечный автомат**: этапы
  `planning → execution → validation → done`, пауза и продолжение с
  сохранённого шага — см. раздел [Task State Machine](#10-task-state-machine).

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
* **Profile: [ … ▾ ]** в шапке чата — переключение активного профиля.
  Профилей может быть сколько угодно; активный применяется к каждому запросу
  автоматически (см. [User Profile](#9-user-profile)).
* **⚙ Настройки → User Profile** — создание, редактирование, дублирование и
  удаление профилей, а также выбор активного.
* **Task state** в панели памяти — этап задачи, текущий шаг, ожидаемое
  действие и кнопки **Pause** / **Resume** / **Done**
  (см. [Task State Machine](#10-task-state-machine)).

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
│   │   ├── memory.py           # /api/memory, /api/chats/{id}/memory/*
│   │   ├── profile.py          # /api/profiles, /api/profile
│   │   └── tasks.py            # /api/tasks/{id}/state, pause, resume, ...
│   ├── memory/                 # модель памяти агента
│   │   ├── models.py           # схемы слоёв и результата извлечения
│   │   ├── short_term.py       # слой 1: текущий диалог
│   │   ├── working.py          # слой 2: состояние задачи
│   │   ├── long_term.py        # слой 3: факты о пользователе + валидация
│   │   ├── extractor.py        # MemoryExtractor: только предлагает
│   │   └── manager.py          # MemoryManager: решает и строит контекст
│   ├── profile/                # персонализация (как отвечать)
│   │   ├── models.py           # схема профиля и словари формулировок
│   │   └── manager.py          # ProfileManager: CRUD, активация, рендер
│   ├── tasks/                  # состояние задачи (конечный автомат)
│   │   ├── models.py           # этапы, статусы, разрешённые переходы
│   │   ├── extractor.py        # TaskStateExtractor: считает этап и шаг
│   │   └── manager.py          # TaskStateManager: переходы, пауза, resume
│   ├── models/                 # Pydantic-схемы (chat, message, settings)
│   ├── services/
│   │   ├── ai_client.py        # клиент OpenAI-compatible API
│   │   ├── chat_service.py     # логика чатов и сообщений
│   │   ├── memory_service.py   # связка памяти и профиля с приложением
│   │   ├── prompt_builder.py   # сборка контекста запроса
│   │   └── settings_service.py # хранение настроек (data/config.json)
│   ├── database/
│   │   ├── database.py         # SQLite: подключение и схема
│   │   ├── repositories.py     # доступ к чатам и сообщениям
│   │   ├── memory_repositories.py  # доступ к working / long-term
│   │   ├── profile_repository.py   # доступ к user_profiles + app_state
│   │   └── task_repository.py      # доступ к task_states
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
| GET    | `/api/profiles`                        | все профили + активный                |
| POST   | `/api/profiles`                        | создать профиль                       |
| GET    | `/api/profiles/{id}`                   | один профиль                          |
| PUT    | `/api/profiles/{id}`                   | изменить профиль                      |
| DELETE | `/api/profiles/{id}`                   | удалить профиль (409 для активного)   |
| POST   | `/api/profiles/{id}/activate`          | сделать профиль активным              |
| POST   | `/api/profiles/{id}/duplicate`         | дублировать профиль                   |
| GET    | `/api/profile/active`                  | текущий активный профиль              |
| GET    | `/api/profile/prompt-block`            | текст профиля, уходящий в prompt      |
| GET    | `/api/profile`                         | активный профиль (совместимость)      |
| PUT    | `/api/profile`                         | изменить активный профиль             |
| DELETE | `/api/profile`                         | сбросить настройки профиля            |
| GET    | `/api/tasks/{id}/state`                | состояние задачи                      |
| POST   | `/api/tasks/{id}/state`                | создать состояние задачи              |
| PUT    | `/api/tasks/{id}/state`                | изменить шаг и ожидаемое действие     |
| POST   | `/api/tasks/{id}/transition`           | перейти на другой этап (с валидацией) |
| POST   | `/api/tasks/{id}/pause`                | поставить на паузу                    |
| POST   | `/api/tasks/{id}/resume`               | продолжить с сохранённого шага        |
| POST   | `/api/tasks/{id}/complete`             | завершить задачу                      |
| POST   | `/api/tasks/{id}/refresh-step`         | пересчитать шаг по диалогу вручную    |
| GET    | `/api/tasks/{id}/prompt-block`         | текст состояния, уходящий в prompt    |
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

## 9. User Profile

Профиль отвечает на вопрос **«как отвечать»**, тогда как память — на вопрос
**«что известно»**. Это разные сущности, и они хранятся раздельно.

Профилей может быть **сколько угодно**, и ровно один из них активен. Активный
профиль применяется к каждому запросу автоматически.

### 9.1 Что хранит профиль

| Поле | Значения | Что делает |
| --- | --- | --- |
| `name` | текст | название профиля (Developer, Student, …) |
| `description` | текст | короткое описание для списка |
| `language` | `auto`, `ru`, `en` | язык ответа |
| `style` | `concise`, `balanced`, `detailed`, `professional` | насколько подробно и в каком тоне |
| `format` | `markdown`, `plain`, `step_by_step`, `structured` | как оформлять |
| `technical_level` | `beginner`, `intermediate`, `advanced` | глубина и терминология |
| `preferences` | список строк | предпочтения («Prefer code») |
| `constraints` | список строк | ограничения («Explain terminology») |
| `custom_instructions` | текст | свободные указания модели |

Профиль без персонализации не добавляет в prompt ничего: блок появляется
только когда пользователь что-то изменил.

### 9.2 Чем профиль отличается от трёх слоёв памяти

| Сущность | Отвечает на вопрос | Где хранится | Время жизни |
| --- | --- | --- | --- |
| **User Profile** | *как* отвечать | `user_profiles` | постоянно, пока не удалён |
| **Short-term** | что сказано в этом диалоге | `messages` | удаляется с чатом |
| **Working** | что за задача сейчас | `working_memory` | удаляется с чатом |
| **Long-term** | что помнить о пользователе | `long_term_memory` | постоянно |

Профиль **не** пополняется автоматически из диалога: его задаёт пользователь.
Память, наоборот, наполняется из разговора. Поэтому «предпочитаю Python» —
это long-term memory, а «отвечай кратко» — это профиль.

**Переключение профиля не трогает память.** Меняется только способ подачи
ответа; диалог, задача и факты о пользователе остаются теми же.

### 9.3 Как активный профиль попадает в prompt

`PromptBuilder` (`backend/services/prompt_builder.py`) собирает контекст
заново на **каждый** запрос:

```
System instructions
+ ACTIVE USER PROFILE   ← ProfileManager.build_prompt_block()
+ Long-term Memory      ┐
+ Working Memory        ├─ MemoryManager.build_prompt_context()
+ Short-term Memory     ┘
+ Current user message
```

Активный профиль читается из БД в момент сборки, поэтому переключение
применяется уже к следующему сообщению — перезапуск не нужен. Пользователь
нигде не повторяет свои предпочтения вручную.

Порядок блоков зафиксирован и проверяется тестом
`test_prompt_order_is_profile_then_memory_then_dialogue`.

### 9.4 Переключение профиля

В шапке чата есть переключатель:

```
Profile: [ Developer ▾ ]
```

При открытии списка видно все профили с пометкой активного и краткой
характеристикой, а также действия `Create profile` и `Manage profiles`:

```
✓ Developer      Advanced · Russian · Concise
  Student        Beginner · Russian · Detailed
  English Work   Advanced · English · Professional

＋ Create profile
⚙ Manage profiles
```

Выбор профиля сохраняет `active_profile_id`, обновляет UI и применяется к
следующему запросу.

### 9.5 Управление профилями

**⚙ Настройки → User Profile** — список профилей с кнопками
`Activate`, `Edit`, `Duplicate`, `Delete` и кнопкой создания. Для каждого
профиля показана строка вида `Advanced · Russian · Concise`.

Правила:

* активным может быть только один профиль;
* активный профиль нельзя удалить — сначала переключитесь на другой (409);
* должен остаться хотя бы один профиль (409);
* дубликат копирует настройки, но не активируется автоматически.

### 9.6 Как проверить персонализацию

**Через интерфейс:** переключите профиль в шапке чата и задайте один и тот же
вопрос — ответ изменится. В **⚙ Настройки → User Profile** видно блок
«Что уходит в prompt» с точным текстом для модели.

**Через API:**

```bash
# Создать три профиля
curl -X POST http://127.0.0.1:8005/api/profiles -H 'Content-Type: application/json' \
  -d '{"name":"Developer","data":{"language":"ru","style":"concise",
       "format":"markdown","technical_level":"advanced",
       "preferences":["Prefer code","Practical examples"]}}'

curl -X POST http://127.0.0.1:8005/api/profiles -H 'Content-Type: application/json' \
  -d '{"name":"Student","data":{"language":"ru","style":"detailed",
       "format":"step_by_step","technical_level":"beginner",
       "preferences":["Explain terminology"]}}'

curl -X POST http://127.0.0.1:8005/api/profiles -H 'Content-Type: application/json' \
  -d '{"name":"English Work","data":{"language":"en","style":"professional",
       "format":"structured","technical_level":"advanced",
       "preferences":["Business-oriented answers","No emojis"]}}'

# Переключиться и посмотреть, что уйдёт в prompt
curl -X POST http://127.0.0.1:8005/api/profiles/student/activate
curl http://127.0.0.1:8005/api/profile/prompt-block
```

Один и тот же вопрос `Объясни dependency injection в FastAPI.` даёт разные
ответы:

| | Developer | Student | English Work |
| --- | --- | --- | --- |
| Язык | русский | русский | английский |
| Стиль | concise | detailed | professional |
| Формат | markdown | step-by-step | structured |
| Уровень | advanced | beginner | advanced |
| Объём | ~1.2k символов, 45 строк | ~2.7k символов, 70 строк | ~2.4k символов, 35 строк |
| Подача | плотно, trade-offs, код | нумерованные шаги, пояснение терминов | разделы, выводы, без эмодзи |

### 9.7 Изоляция профилей

Каждый профиль адресуется своим `id`, и все чтения/записи ограничены этим
`id`. Профили не смешиваются: после переключения `Developer → Student` в
prompt попадают только настройки Student, а настройки Developer исчезают.
Профили хранятся как данные — в коде нет ни одного `if profile == "developer"`.

Это покрыто тестами `test_profiles_are_isolated`,
`test_profile_prompt_blocks_are_isolated`,
`test_switching_profile_changes_prompt` и
`test_editing_one_profile_does_not_touch_another`.

### 9.8 Миграция старых баз

`CREATE TABLE IF NOT EXISTS` не добавляет колонки в существующую таблицу,
поэтому при старте выполняется идемпотентная миграция: она проверяет текущие
колонки и добавляет недостающие (`name`, `description`). Старые профили
сохраняются, настройки не теряются — см. тесты
`test_migration_adds_columns_to_existing_database` и
`test_migration_is_idempotent`.

---

## 10. Task State Machine

Состояние задачи — это **формализованная позиция в конечном автомате**, а не
свободный текст. Оно хранится отдельно от памяти и меняется только через
разрешённые переходы.

### 10.1 Этапы и статусы

```
planning ──► execution ──► validation ──► done
    │            │             │
    └────────────┴─────────────┴──► paused ──► (тот же этап)
```

`paused` — это **статус**, а не этап: при паузе этап и шаг сохраняются.

| Поле | Значения |
| --- | --- |
| `stage` | `planning`, `execution`, `validation`, `done` |
| `current_step` | текущий шаг, например `implement refresh token` |
| `expected_action` | что нужно сделать дальше |
| `status` | `active`, `paused`, `completed` |
| `previous_stage` | этап, с которого ушли |
| `pause_reason` | причина паузы |
| `completed_steps` | шаги, закрытые при переходах |

### 10.2 Разрешённые переходы

| Из | Куда можно |
| --- | --- |
| `planning` | `execution` |
| `execution` | `validation` |
| `validation` | `done` |
| `done` | — |

Всё остальное отклоняется с `409 invalid_transition`. Например
`planning → done` запрещён:

```json
{
  "error": {
    "code": "invalid_transition",
    "message": "Переход «Planning → Done» не разрешён. Из этапа «Planning» допустимо: execution."
  }
}
```

Завершение (`complete`) не обходит автомат: оно проходит оставшиеся этапы
по порядку.

### 10.3 Чем Task State отличается от Working Memory

| Сущность | Что хранит | Где |
| --- | --- | --- |
| **Working Memory** | свободный контекст задачи: стек, требования, решения | `working_memory` |
| **Task State** | формализованную позицию: этап, шаг, ожидаемое действие, статус | `task_states` |

Пример:

```
Working Memory:            Task State:
  Task: authentication API   Stage: execution
  Technology: FastAPI        Current step: implement refresh token
  Requirements: JWT          Expected action: write refresh token endpoint
                             Status: active
```

Task State может опираться на данные Working Memory, но хранится и
управляется отдельно. Тест `test_task_state_is_separate_from_working_memory`
проверяет, что они не смешиваются.

### 10.4 Как состояние попадает в prompt

`PromptBuilder` добавляет блок `## TASK STATE` после рабочей памяти:

```
System instructions
+ ACTIVE USER PROFILE
+ Long-term Memory
+ Working Memory
+ TASK STATE          ← TaskStateManager.build_prompt_block()
+ Short-term Memory
+ Current user message
```

Модель видит, на каком этапе задача и что делать дальше, поэтому не
предлагает заново уже сделанное.

### 10.5 Пауза и продолжение

**Пауза** сохраняет всё: этап, шаг, ожидаемое действие, рабочую память,
долговременную память и историю диалога. Ничего не удаляется.

**Продолжение** восстанавливает состояние и продолжает с того же шага —
пользователю не нужно заново объяснять задачу.

Проверено сквозным сценарием: `execution → pause → перезапуск приложения →
resume → execution` с сохранением `current_step` и `expected_action`.

### 10.6 UI

В панели памяти (кнопка **🧠** в шапке чата) есть блок **Task state**:

```
┌──────────────────────────────┐
│ Task state          ACTIVE   │
├──────────────────────────────┤
│ ✓ Planning  ● Execution      │
│ ○ Validation  ○ Done         │
│                              │
│ STAGE            execution   │
│ CURRENT STEP     implement…  │
│ EXPECTED ACTION  create…     │
│                              │
│ [Pause] [Done] [Пересчитать] │
└──────────────────────────────┘
```

При паузе статус меняется на `PAUSED`, а кнопка — на **Resume**.

### 10.7 Как считаются stage, current step и expected action

Всё состояние задачи **выводится из диалога одним запросом к модели**:
и этап, и текущий шаг, и ожидаемое действие. Один вызов вместо трёх держит
поля согласованными между собой.

`TaskStateExtractor` (`backend/tasks/extractor.py`) получает текущий этап,
известные шаг и ожидаемое действие и последние сообщения диалога, а возвращает:

```json
{
  "stage": "execution",
  "current_step": "написание security.py для JWT-авторизации",
  "expected_action": "создать pwd_context и oauth2_scheme",
  "confidence": 0.9
}
```

Как и `MemoryExtractor`, он ничего не пишет в БД: предложение применяет
`TaskStateManager.apply_step_suggestion()`, и только если уверенность не ниже
`0.4` и есть содержимое.

**Этап всё равно проходит через автомат.** Модель может ошибиться, поэтому
предложенный `stage` применяется только по разрешённым рёбрам:

* переход вперёд по одному шагу — применяется;
* прыжок через этап (`planning → done`) — проходится по порядку
  (`planning → execution → validation → done`), а не берётся напрямую;
* переход назад — игнорируется, шаг при этом всё равно сохраняется;
* неизвестный этап — отбрасывается.

`status` при пересчёте не меняется: приостановленная задача остаётся на паузе.

**Когда это происходит.** После каждого ответа ассистента пересчёт запускается
**в фоне** (`asyncio.create_task`), поэтому ответ пользователю не задерживается.
В панели на это время виден индикатор «Пересчитываю шаг по диалогу…», а после
завершения шаг обновляется сам.

Пересчитать вручную можно кнопкой **Пересчитать шаг** в блоке Task state или
запросом `POST /api/tasks/{id}/refresh-step`.

### 10.8 Автоматическое обновление

Состояние двигается по сообщениям пользователя, но только по разрешённым
рёбрам и только когда сообщение явно указывает на следующий шаг:

| Сообщение | Что происходит |
| --- | --- |
| «Подтверждаю план» | модель предлагает `execution`, автомат применяет переход |
| «Готово, проверь» | модель предлагает `validation` |
| «Поставь задачу на паузу» | `status = paused` (команда пользователя) |
| «Продолжить» | `status = active`, тот же этап (команда пользователя) |

Этап определяет модель по смыслу диалога, а не по ключевым словам. Явные
команды паузы и продолжения обрабатываются отдельно, потому что это прямое
указание пользователя, а не вывод из контекста.

Обычные сообщения состояние не меняют — это проверяется тестом
`test_plain_message_does_not_change_state`.

### 10.9 Проверка

```bash
# Создать состояние и перевести в execution
curl -X POST http://127.0.0.1:8005/api/tasks/<chat_id>/state -d '{}' \
  -H 'Content-Type: application/json'
curl -X POST http://127.0.0.1:8005/api/tasks/<chat_id>/transition \
  -H 'Content-Type: application/json' \
  -d '{"stage":"execution","current_step":"implement authentication",
       "expected_action":"create login endpoint"}'

# Запрещённый переход
curl -X POST http://127.0.0.1:8005/api/tasks/<chat_id>/transition \
  -H 'Content-Type: application/json' -d '{"stage":"done"}'   # 409

# Пауза и продолжение
curl -X POST http://127.0.0.1:8005/api/tasks/<chat_id>/pause -d '{}' \
  -H 'Content-Type: application/json'
curl -X POST http://127.0.0.1:8005/api/tasks/<chat_id>/resume
```

---

## 11. Хранение данных

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
user_profiles:     id, name, description, data (JSON), created_at, updated_at
app_state:         key, value, updated_at   -- хранит active_profile_id
task_states:       task_id, chat_id, stage, current_step, expected_action,
                   status, data (JSON), created_at, updated_at
```

`messages` — это short-term memory, `working_memory` — рабочая память,
`long_term_memory` — долговременная. Три отдельные таблицы с разной
структурой и разным временем жизни. `user_profiles` — четвёртая, отдельная
сущность: она описывает, *как* отвечать, а не *что* известно. Каждый профиль —
своя строка, поэтому профили не перезаписывают друг друга. Активный профиль
хранится в `app_state`, а не колонкой у профиля: «активный» — свойство
приложения, а не профиля, и так «активен ровно один» верно по построению.

---

## 12. Тесты

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

Файл `tests/test_profile.py` покрывает персонализацию:

| Тест | Что доказывает |
| --- | --- |
| сохранение/загрузка | профиль пишется и читается, переживает перезапуск |
| передача в prompt | профиль уходит в модель на каждом запросе |
| язык | `language` меняет язык ответа в system-сообщении |
| стиль | `style` меняет требуемую подробность |
| технический уровень | `technical_level` меняет глубину и терминологию |
| изоляция | профили `alice` и `bob` не смешиваются |
| порядок блоков | profile → long-term → working → short-term |
| независимость | профиль не создаёт записей в памяти, память не попадает в профиль |

Файл `tests/test_profiles_multi.py` покрывает несколько профилей:

| Тест | Что доказывает |
| --- | --- |
| `test_create_profile` | профиль создаётся со своими настройками |
| `test_update_profile` | настройки и название изменяются |
| `test_delete_profile` | профиль удаляется |
| `test_duplicate_profile` | копия сохраняет настройки и не активируется |
| `test_activate_profile` | переключение активного профиля |
| `test_only_one_active_profile` | активен ровно один профиль |
| `test_active_profile_is_used_in_prompt` | активный профиль уходит в модель |
| `test_switching_profile_changes_prompt` | после переключения в prompt только новый профиль |
| `test_profiles_are_isolated` | настройки профилей не смешиваются |
| `test_memory_is_preserved_when_switching_profile` | память не меняется при переключении |
| `test_cannot_delete_active_profile` | активный профиль защищён (409) |
| `test_cannot_delete_last_profile` | последний профиль защищён (409) |
| `test_migration_*` | старые базы обновляются без потери данных |

Файл `tests/test_task_state.py` покрывает конечный автомат:

| Тест | Что доказывает |
| --- | --- |
| `test_initial_task_state` | новая задача начинается в `planning` |
| `test_valid_transition` | `planning → execution → validation → done` |
| `test_invalid_transition` | `planning → done` отклоняется (409) |
| `test_pause_preserves_state` | пауза сохраняет этап, шаг и ожидаемое действие |
| `test_resume_restores_state` | продолжение возвращает тот же этап и шаг |
| `test_state_persists_after_restart` | `pause → restart → resume` сохраняет всё |
| `test_state_is_added_to_prompt` | блок `TASK STATE` уходит в модель |
| `test_task_completion` | завершение проходит этапы по порядку |
| `test_pause_does_not_touch_memory` | пауза не удаляет память и диалог |
| `test_task_state_is_separate_from_working_memory` | слои не смешиваются |
| `test_plain_message_does_not_change_state` | состояние не меняется случайно |
| `test_step_is_computed_after_reply` | шаг считается по диалогу после ответа |
| `test_step_extraction_uses_a_separate_api_call` | пересчёт идёт отдельным запросом |
| `test_step_extraction_does_not_block_the_reply` | сбой пересчёта не ломает ответ |
| `test_low_confidence_step_is_ignored` | неуверенное предложение не сохраняется |
| `test_step_refresh_keeps_stage_and_status` | пересчёт не двигает автомат |
| `test_step_is_visible_in_prompt` | посчитанный шаг уходит в модель |
| `test_stage_is_computed_in_the_same_call` | этап и шаг приходят одним запросом |
| `test_extraction_prompt_asks_for_the_stage` | промпт запрашивает этап |
| `test_stage_jump_walks_intermediate_stages` | прыжок через этап идёт по порядку |
| `test_stage_does_not_move_backwards` | переход назад игнорируется |
| `test_unknown_stage_is_ignored` | неизвестный этап отбрасывается |
| `test_paused_task_keeps_status_when_stage_is_recomputed` | пауза не сбрасывается |

---

## 13. Troubleshooting

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