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
* **Инварианты** — обязательные ограничения проекта: ассистент не предлагает
  решения, нарушающие активные правила, и не меняет их без явной просьбы —
  см. раздел [Invariants](#11-invariants).
* **Настраиваемый жизненный цикл задачи**: пользователь сам задаёт состояния и
  правила переходов с условиями, AI определяет момент перехода и читает нужные
  факты прямо из сообщений, а `TransitionManager` гарантирует, что правила не
  нарушены. Если запрос требует запрещённого перехода, он **не выполняется** —
  см. раздел [Task State Rules](#12-task-state-rules).

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
* **⚙ Настройки → Invariants** — обязательные ограничения проекта. Запрос,
  нарушающий активное правило, получает объяснение конфликта вместо решения
  (см. [Invariants](#11-invariants)).

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
│   │   ├── tasks.py            # /api/tasks/{id}/state, pause, resume, ...
│   │   ├── invariants.py       # /api/invariants, activate, check
│   │   └── transitions.py      # /api/task-states, /api/transition-rules
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
│   ├── invariants/             # обязательные ограничения
│   │   ├── models.py           # scope, категории, приоритеты, конфликты
│   │   ├── detector.py         # InvariantConflictDetector: ищет конфликты
│   │   └── manager.py          # InvariantManager: CRUD, активация, проверка
│   ├── transitions/            # настраиваемый жизненный цикл задачи
│   │   ├── models.py           # состояния, правила, условия, история
│   │   ├── conditions.py       # безопасный вычислитель условий
│   │   ├── detector.py         # TransitionDetector: предлагает переход
│   │   ├── facts.py            # FactExtractor: читает факты из сообщения
│   │   └── manager.py          # TransitionManager: проверяет и применяет
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
│   │   ├── task_repository.py      # доступ к task_states
│   │   ├── invariant_repository.py # доступ к invariants
│   │   └── transition_repository.py # состояния, правила, история переходов
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
| GET    | `/api/invariants`                      | все инварианты                        |
| POST   | `/api/invariants`                      | создать инвариант                     |
| GET    | `/api/invariants/{id}`                 | один инвариант                        |
| PUT    | `/api/invariants/{id}`                 | изменить инвариант                    |
| DELETE | `/api/invariants/{id}`                 | удалить инвариант                     |
| POST   | `/api/invariants/{id}/activate`        | активировать правило                  |
| POST   | `/api/invariants/{id}/deactivate`      | деактивировать (правило сохраняется)  |
| POST   | `/api/invariants/check`                | проверить запрос на конфликт          |
| GET    | `/api/tasks/{id}/invariants`           | инварианты задачи + глобальные        |
| POST   | `/api/tasks/{id}/invariants`           | создать инвариант задачи              |
| GET    | `/api/task-states`                     | состояния жизненного цикла            |
| POST   | `/api/task-states`                     | создать состояние                     |
| GET    | `/api/task-states/{id}`                | одно состояние                        |
| PUT    | `/api/task-states/{id}`                | изменить состояние                    |
| DELETE | `/api/task-states/{id}`                | удалить (409, если используется)      |
| GET    | `/api/transition-rules`                | правила переходов                     |
| POST   | `/api/transition-rules`                | создать правило                       |
| GET    | `/api/transition-rules/{id}`           | одно правило                          |
| PUT    | `/api/transition-rules/{id}`           | изменить правило                      |
| DELETE | `/api/transition-rules/{id}`           | удалить правило                       |
| POST   | `/api/transition-rules/{id}/activate`  | активировать правило                  |
| POST   | `/api/transition-rules/{id}/deactivate`| деактивировать правило                |
| POST   | `/api/transition-rules/{id}/check`     | проверить условие правила             |
| GET    | `/api/tasks/{id}/available-transitions`| доступные переходы с вердиктом        |
| POST   | `/api/tasks/{id}/transitions/apply`    | перейти (отказ — не ошибка)           |
| GET    | `/api/tasks/{id}/facts`                | факты задачи + недостающие поля       |
| PUT    | `/api/tasks/{id}/facts`                | задать факты задачи                   |
| GET    | `/api/tasks/{id}/transition-history`   | история переходов                     |
| GET    | `/api/tasks/{id}/transition-prompt-block` | текст правил, уходящий в prompt    |
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

Переходы **настраиваются пользователем** на странице
[Task State Rules](#12-task-state-rules) и хранятся в БД. Ниже — конфигурация
по умолчанию, которая создаётся при первом запуске:

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

## 11. Invariants

Инвариант — это **обязательное ограничение**: правило, которое ассистент не
должен нарушать без явного изменения самого правила. Он отвечает на вопрос,
какие решения **недопустимы**, тогда как остальные слои описывают, что известно
и как отвечать.

### 11.1 Что хранит инвариант

| Поле | Значения | Что делает |
| --- | --- | --- |
| `scope` | `global`, `task` | где действует правило |
| `category` | `architecture`, `technology`, `business`, `security`, `design`, `technical_decision`, `constraint`, `other` | тип правила |
| `rule` | текст | само ограничение |
| `description` | текст | почему оно принято |
| `status` | `active`, `inactive` | применяется ли сейчас |
| `priority` | `low`, `medium`, `high`, `critical` | насколько жёстко |
| `task_id` | id задачи | для `scope = task` |

Примеры:

```text
architecture       Использовать монолитную архитектуру
technology         Backend — Python + FastAPI
technology         Database — SQLite
technical_decision Авторизация через JWT
business           Один активный заказ на пользователя
constraint         Не использовать Redis
```

### 11.2 Чем инвариант отличается от остальных слоёв

| Слой | Отвечает на вопрос | Пример |
| --- | --- | --- |
| **Profile** | *как* отвечать | «отвечай кратко, по-русски» |
| **Long-term memory** | что помнить о пользователе | «пользователь предпочитает FastAPI» |
| **Working memory** | что за задача сейчас | «стек: FastAPI, PostgreSQL» |
| **Task state** | где задача в жизненном цикле | «этап execution, шаг JWT» |
| **Invariant** | какие решения **недопустимы** | «Backend обязан использовать FastAPI» |

Разница между памятью и инвариантом видна на одном примере:

```text
Long-Term Memory:  Пользователь предпочитает FastAPI.   ← предпочтение
Invariant:         Backend проекта обязан использовать FastAPI.  ← ограничение
```

Предпочтение можно не учесть; ограничение нарушить нельзя.

### 11.3 Как инварианты попадают в prompt

`PromptBuilder` добавляет блок `## ACTIVE INVARIANTS` после состояния задачи и
явно объясняет модели, как с ним обращаться:

```text
System instructions
+ ACTIVE USER PROFILE
+ Long-term Memory
+ Working Memory
+ TASK STATE
+ ACTIVE INVARIANTS   ← InvariantManager.build_prompt_block()
+ Short-term Memory
+ Current user message
```

Блок сгруппирован по категориям, критичные правила помечены:

```text
## ACTIVE INVARIANTS

Technology:
- Backend: FastAPI
- Database: SQLite
- Do not use Redis

Technical decisions:
- Authentication: JWT

INVARIANT RULES:
1. Active invariants are mandatory constraints.
2. Do not propose solutions that violate them.
3. If the user request conflicts with an invariant, explicitly identify the conflict.
4. Do not silently modify or ignore an invariant.
5. Do not change an invariant unless the user explicitly requests to change it.
6. When possible, propose an alternative that satisfies all active invariants.
```

### 11.4 Проверка конфликтов

Перед тем как просить модель о решении, запрос проверяется против активных
инвариантов:

```text
User Message
      ↓
Profile → Memory → Task State → Invariants
      ↓
Conflict Check
      ↓
PromptBuilder → AI Model
```

`InvariantConflictDetector` (`backend/invariants/detector.py`) предлагает
конфликты, а `InvariantManager.check_conflict()` их проверяет: конфликт с
правилом, которого нет среди активных, отбрасывается. Модель не может выдумать
инвариант.

Если конфликт найден, модель **не вызывается** — ассистент отвечает сам:

```text
Я не могу предложить это решение: запрос конфликтует с активным
инвариантом проекта.

Нарушаемое ограничение:
«Не использовать Redis»
Запрошено: «Добавить Redis для кеширования»

Я не буду менять это ограничение автоматически. Если решение
действительно изменилось, скажите об этом явно — тогда я обновлю
инвариант.

Совместимая альтернатива: встроенный in-memory кэш или Memcached.
```

В интерфейсе такое сообщение помечается бейджем **⚠ Constraint conflict**.

### 11.5 Явное изменение инварианта

Обычный запрос **не** меняет правило. Изменение применяется только когда
пользователь прямо говорит, что решение изменилось:

| Сообщение | Что происходит |
| --- | --- |
| «Добавь Redis» | конфликт, правило остаётся активным |
| «Мы отменяем это ограничение. Теперь Redis разрешён.» | старое правило деактивируется, новое активируется |

Изменение выполняет `InvariantManager.replace_rule()`: старое правило
переводится в `inactive` (не удаляется), новое создаётся активным. Текст нового
правила берётся из сообщения пользователя и очищается от вводных фраз, поэтому
в базе лежит «Redis разрешён», а не целое предложение.

### 11.6 Scope: global и task

* `global` — действует для всего проекта, попадает в каждый запрос;
* `task` — действует только для своей задачи.

Правила одной задачи не попадают в prompt другой — это проверяется тестами
`test_task_invariants_are_isolated` и
`test_task_invariant_reaches_only_its_own_prompt`. При удалении задачи её
инварианты удаляются, глобальные остаются.

### 11.7 UI

**⚙ Настройки → Invariants** — список правил с категорией, приоритетом, scope
и кнопками `Activate` / `Deactivate` / `Edit` / `Delete`. Активные правила
отмечены галочкой, неактивные приглушены.

### 11.8 Проверка

```bash
# Создать инвариант
curl -X POST http://127.0.0.1:8005/api/invariants \\
  -H 'Content-Type: application/json' \\
  -d '{"scope":"global","category":"constraint",
       "rule":"Не использовать Redis","priority":"high"}'

# Проверить запрос на конфликт
curl -X POST http://127.0.0.1:8005/api/invariants/check \\
  -H 'Content-Type: application/json' \\
  -d '{"request":"Добавь Redis для кеширования"}'

# Деактивировать правило (не удаляя)
curl -X POST http://127.0.0.1:8005/api/invariants/<id>/deactivate
```

Сквозной сценарий: создать «Не использовать Redis» → попросить Redis → получить
конфликт с альтернативой → явно отменить ограничение → попросить Redis снова →
ассистент предлагает решение.

---

## 12. Task State Rules

Жизненный цикл задачи — это **конфигурация, а не код**. Пользователь сам
задаёт, какие состояния существуют и какие переходы между ними разрешены, а
`TransitionManager` гарантирует, что AI физически не сможет нарушить
настроенный жизненный цикл.

### 12.1 Главный принцип

```text
Запрос пользователя
        ↓
AI определяет необходимость перехода
        ↓
TransitionManager
        ↓
загружает правила из БД
        ↓
проверяет условия
        ↓
разрешён → запрос выполняется, stage изменяется
запрещён → запрос НЕ выполняется, stage не изменяется
```

AI отвечает за **определение момента перехода**, `TransitionManager` — за
**контроль допустимости перехода**. Модель может ошибиться, поэтому её
предложение — это только *запрос*, который проходит ту же проверку, что и
ручной переход.

Проверка идёт **до** выполнения запроса: если переход запрещён, запрос не
выполняется вообще (см. [12.8](#128-проверка-перехода-перед-выполнением-запроса)).

### 12.2 Чем этот слой отличается от остальных

| Слой | Отвечает на вопрос | Пример |
| --- | --- | --- |
| **Profile** | *как* отвечать | «отвечай кратко, по-русски» |
| **Long-term memory** | что помнить о пользователе | «предпочитает FastAPI» |
| **Working memory** | что за задача сейчас | «стек: FastAPI, PostgreSQL» |
| **Task state** | где задача в жизненном цикле | «этап execution, шаг JWT» |
| **Invariants** | какие решения **недопустимы** | «Backend обязан использовать FastAPI» |
| **Task State Rules** | **какие переходы разрешены и когда** | «Planning → Execution при plan_status == approved» |

Task State хранит *позицию*, Task State Rules описывает *правила движения*.
Это разные таблицы: `task_states` (позиция задачи) и `task_state_definitions`
(словарь состояний).

### 12.3 Состояния

Состояния хранятся в БД, а не в коде. При первом запуске создаются четыре
стандартных (`planning`, `execution`, `validation`, `done`) и три правила
между ними — без условий, чтобы привычное поведение сохранилось. Дальше
пользователь может:

* создать состояние;
* изменить название и описание;
* активировать/деактивировать;
* указать начальное состояние (ровно одно);
* указать финальное состояние (минимум одно);
* удалить состояние, если оно не используется правилами.

| Поле | Значения |
| --- | --- |
| `id` | стабильный идентификатор (из названия) |
| `name` | отображаемое название |
| `description` | пояснение |
| `is_initial` | с этого состояния начинается новая задача |
| `is_final` | здесь задача считается завершённой |
| `active` | участвует ли состояние в жизненном цикле |
| `position` | порядок отображения |

**Нельзя удалить состояние, пока на него ссылается правило** — вернётся `409
state_in_use` со списком мешающих правил.

### 12.4 Правила переходов

| Поле | Значения |
| --- | --- |
| `from_state` | откуда |
| `to_state` | куда |
| `name` | название правила |
| `description` | пояснение |
| `condition` | условие текстом (для чтения и prompt) |
| `conditions` | структурированные условия (проверяются) |
| `active` | применяется ли правило |

Серверная валидация не даёт создать некорректную конфигурацию:

* оба состояния должны существовать (`422 invalid_rule`);
* переход в то же состояние запрещён;
* дублирующее правило отклоняется (`409 duplicate_rule`);
* в жизненном цикле должно остаться хотя бы одно финальное состояние;
* начальным может быть только одно состояние;
* правило не может ссылаться на несуществующее состояние.

### 12.5 Условия переходов

Условия структурированы, а не только текстовые:

```json
{"type": "field_equals", "field": "plan_status", "value": "approved"}
```

Поддерживаемые типы — небольшой безопасный набор, без языка выражений:

| Тип | Что проверяет |
| --- | --- |
| `field_equals` | поле равно значению (без учёта регистра) |
| `field_not_equals` | поле не равно значению |
| `field_not_empty` | поле заполнено |
| `field_empty` | поле пусто |
| `boolean_true` | флаг включён (`true`, `1`, `yes`, `да`, …) |
| `boolean_false` | флаг выключен |
| `all_conditions` | все вложенные условия |
| `any_condition` | любое из вложенных условий |

Условия проверяются против **фактов задачи**: `metadata` задачи плюс её
позиция (`stage`, `status`, `current_step`, `expected_action`). Поэтому
возможны и `plan_status == approved`, и `stage == planning`.

Неизвестный тип условия отклоняется при создании правила — правило не может
быть молча неисполнимым.

**Факты извлекаются из сообщения автоматически.** Условие
`plan_status == approved` выполнится, когда у задачи есть факт `plan_status`
со значением `approved`. Пользователь не вводит это значение руками: он пишет
«план утверждён», и `FactExtractor` читает значение из его же сообщения.

```text
Сообщение пользователя: «план утверждён, начинаем реализацию»
        ↓
FactExtractor: какие факты читают правила? → plan_status
        ↓
plan_status = «утверждён»   ← записано в задачу
        ↓
TransitionManager: условие plan_status == утвержден выполнено
        ↓
переход planning → execution выполнен
```

Извлечение ограничено правилами:

* запрашиваются только те факты, которые читают **активные правила**;
* принимаются значения только для этих фактов — модель не может добавить
  факт, которого правила не знают;
* позиция задачи (`stage`, `status`) через извлечение не меняется никогда;
* при низкой уверенности значение не записывается;
* если в сообщении фактов нет, уже сохранённые значения не затираются.

Факты видны в блоке **Task state**; прочитанные из сообщения помечены бейджем
**из сообщения**. Их можно поправить вручную (кнопка **Изменить факты**) или
через `GET`/`PUT /api/tasks/{id}/facts`.

**Сравнение значений не зависит от регистра и «ё».** Пользователь пишет
«план утвержден», модель может вернуть «утверждён» — для правила это одно и то
же значение. Без этого правило молча не срабатывало бы из-за одной буквы.

Если правило читает факт, которого у задачи нет, условие **не может
выполниться никогда**. Это отдельный случай, и приложение говорит о нём прямо:

* в блоке Task state появляется предупреждение со списком недостающих полей;
* кнопка **Проверить** на странице правил показывает те же поля;
* отказ в переходе называет факт, который нужно задать, а не пустое значение.

```text
Я не могу выполнить этот запрос: он требует перехода, который запрещён
правилами жизненного цикла задачи.

Запрошенный переход: planning → execution
Требуемое условие: plan_status == утвержден
Факт «plan_status» у задачи не задан, поэтому условие не может выполниться.

Состояние задачи не изменено, запрос не выполнен. Укажите факт «plan_status»
в блоке Task state (кнопка «Изменить факты») или измените правила на странице
Task State Rules.
```

Позицию задачи (`stage`, `status`) через факты подменить нельзя: она
вычисляется автоматом, а не задаётся вручную.

### 12.6 Как правила попадают в prompt

`PromptBuilder` добавляет блок `## TASK STATE RULES` сразу после `TASK STATE`:

```text
System instructions
+ ACTIVE USER PROFILE
+ Long-term Memory
+ Working Memory
+ TASK STATE
+ TASK STATE RULES    ← TransitionManager.build_prompt_block()
+ ACTIVE INVARIANTS
+ Short-term Memory
+ Current user message
```

```text
## TASK STATE RULES

Current state: Planning
Allowed transitions:
- Planning → Execution | condition: plan_status == approved  [condition not met]

TRANSITION RULES:
1. You may decide that the task should move to another state and request the transition.
2. A transition is applied only if an active rule exists for that exact edge and its condition holds.
3. Never claim that the state changed unless the transition was accepted.
4. If a transition is rejected, explain the required condition and continue the work without changing the state.
```

### 12.7 Отказ в переходе

Отказ — это нормальный результат, а не ошибка. Stage не меняется, а причина
понятна пользователю:

```text
Transition rejected.

Required condition:
plan_status == approved

Current value:
pending
```

Через API это `POST /api/tasks/{id}/transitions/apply` с `allowed: false`:

```json
{
  "from_state": "planning",
  "to_state": "execution",
  "allowed": false,
  "reason": "Условие перехода не выполнено: plan_status == approved.",
  "required_condition": "plan_status == approved",
  "actual": "pending"
}
```

### 12.8 Проверка перехода перед выполнением запроса

Если задача уже начата, переход проверяется **до** выполнения запроса, а не
после:

```text
Запрос пользователя
        ↓
Transition Detector: в какое состояние перейдёт задача после выполнения?
        ↓
TransitionManager: разрешён ли этот переход по правилам?
        ↓
разрешён  → запрос выполняется, stage меняется
запрещён  → запрос НЕ выполняется, stage не меняется,
            пользователю сообщается причина
```

Модель отвечает только на вопрос **намерения** — к какому состоянию ведёт
запрос. Проверку условий и решение о допустимости делает `TransitionManager`,
поэтому модель не может ни обойти правило, ни отказаться от перехода из-за
неизвестных ей значений условий.

Если переход запрещён, запрос **не отправляется модели** и не выполняется.
Ассистент отвечает причиной:

```text
Я не могу выполнить этот запрос: он требует перехода, который запрещён
правилами жизненного цикла задачи.

Запрошенный переход: planning → execution
Требуемое условие: plan_status == approved

Состояние задачи не изменено, запрос не выполнен. Выполните условие
перехода или измените правила на странице Task State Rules.
```

В интерфейсе такое сообщение помечается бейджем **⚠ Transition blocked**.

Запрос, который **не двигает** задачу (обычный вопрос, уточнение, обсуждение),
выполняется как обычно — переход не требуется, поэтому и проверять нечего.

| Ситуация | Что происходит |
| --- | --- |
| Запрос не меняет состояние | запрос выполняется, stage не меняется |
| Переход разрешён | запрос выполняется, stage меняется |
| Переход запрещён | запрос **не выполняется**, stage не меняется, причина сообщается |
| Задачи нет | проверка пропускается, запрос выполняется |
| Нет активных правил | проверка пропускается, запрос выполняется |
| Детектор недоступен | проверка пропускается, запрос выполняется |

Проверка идёт **после** инвариантов: если запрос конфликтует с инвариантом,
ответом будет конфликт, а не отказ жизненного цикла.

**Этап меняет только эта проверка.** Фоновый пересчёт шага (`Task State
Extractor`) обновляет `current_step` и `expected_action`, но не `stage`: иначе
у задачи появился бы второй, непроверяемый путь смены состояния.

### 12.9 История переходов

Каждая попытка — и принятая, и отклонённая — пишется в
`task_state_transitions`:

```text
planning → execution | trigger: ai_detected | result: rejected
  reason: Условие перехода не выполнено: plan_status == approved.
planning → execution | trigger: ai_detected | result: success
execution → validation | trigger: user | result: success
```

`trigger` показывает, кто инициировал переход: `ai_detected`, `user`,
`manual`, `system`, `pause`, `resume`.

### 12.10 Динамические изменения

Правила читаются из БД **на каждом переходе**, поэтому изменение применяется
сразу, без перезапуска. Если пользователь убрал условие
`plan_status == approved`, следующий же запрос пройдёт.

### 12.11 Pause / Resume

Пауза — это статус, а не состояние: этап и шаг сохраняются. Пауза **не
позволяет обойти правила** — после `resume` действуют текущие правила
переходов.

### 12.12 UI

**⇄ Правила переходов** в сайдбаре — отдельная страница:

```text
Task State Rules

States
────────────────────────────
Planning   [initial]        Edit  Deactivate  Delete
Execution                   Edit  Deactivate  Delete
Validation                  Edit  Deactivate  Delete
Done       [final]          Edit  Deactivate  Delete

Allowed Transitions
────────────────────────────
┌──────────┐
│ Planning │
└────┬─────┘
     │ ↓
┌───────────┐
│ Execution │
└───────────┘
Start implementation
Condition: plan_status == approved
Status: Active
```

В панели задачи (кнопка **🧠**) видно текущий автомат, факты задачи и
доступные переходы:

```text
Task state                    ACTIVE
✓ Planning  ● Execution  ○ Validation  ○ Done

Факты задачи
plan_status        утверждён  [из сообщения]
Условия правил читают факты, которых у задачи нет:
implementation_status, validation_status. Они определятся
автоматически, когда вы напишете об этом в чате.  [Изменить факты]

Available transitions
→ Validation
  нет дополнительных условий          [Перейти]
```

Если переход недоступен, он показан с причиной:

```text
✕ Execution
  plan_status == approved
  Условие перехода не выполнено: plan_status == approved.
```

### 12.13 Проверка

```bash
# Состояния
curl http://127.0.0.1:8005/api/task-states
curl -X POST http://127.0.0.1:8005/api/task-states \
  -H 'Content-Type: application/json' \
  -d '{"name":"Review","description":"Проверка результата"}'

# Правило с условием
curl -X POST http://127.0.0.1:8005/api/transition-rules \
  -H 'Content-Type: application/json' \
  -d '{"from_state":"planning","to_state":"execution",
       "name":"Start implementation","condition":"plan_status == approved",
       "conditions":[{"type":"field_equals","field":"plan_status","value":"approved"}]}'

# Доступные переходы и попытка перехода
curl http://127.0.0.1:8005/api/tasks/<task_id>/available-transitions
curl -X POST http://127.0.0.1:8005/api/tasks/<task_id>/transitions/apply \
  -H 'Content-Type: application/json' -d '{"to_state":"execution"}'

# История
curl http://127.0.0.1:8005/api/tasks/<task_id>/transition-history
```

Сквозной сценарий: создать правила с условиями → задача в `planning` →
«Начинай реализацию» при `plan_status = pending` → переход отклонён, **запрос
не выполнен**, stage не изменился → «План утверждён, начинаем реализацию» →
переход выполнен, запрос выполнен → `execution → validation` →
`validation → done`. Затем убрать условие на странице правил → следующий
переход проходит без перезапуска.

---

## 13. Хранение данных

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
invariants:        id, scope, category, rule, description, status, priority,
                   task_id, data (JSON), created_at, updated_at
task_state_definitions: id, name, description, is_initial, is_final, active,
                   position, created_at, updated_at
transition_rules:  id, from_state, to_state, name, description, condition,
                   conditions (JSON), active, created_at, updated_at
task_state_transitions: id, task_id, from_stage, to_stage, trigger, reason,
                   result, created_at
```

`task_state_definitions` — это словарь состояний жизненного цикла, а
`task_states` — позиция конкретной задачи. Это разные таблицы: первая
описывает, какие состояния вообще существуют, вторая хранит, где находится
задача сейчас. `transition_rules` хранит правила переходов, а
`task_state_transitions` — историю попыток (включая отклонённые).

`messages` — это short-term memory, `working_memory` — рабочая память,
`long_term_memory` — долговременная. Три отдельные таблицы с разной
структурой и разным временем жизни. `user_profiles` — четвёртая, отдельная
сущность: она описывает, *как* отвечать, а не *что* известно. Каждый профиль —
своя строка, поэтому профили не перезаписывают друг друга. Активный профиль
хранится в `app_state`, а не колонкой у профиля: «активный» — свойство
приложения, а не профиля, и так «активен ровно один» верно по построению.

---

## 14. Тесты

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

Файл `tests/test_invariants.py` покрывает ограничения:

| Тест | Что доказывает |
| --- | --- |
| `test_invariant_creation` | инвариант сохраняется со всеми полями |
| `test_invariant_included_in_prompt` | активное правило уходит в модель |
| `test_invariant_rules_are_explained_to_the_model` | модель знает, как обращаться с правилами |
| `test_no_conflict` | совместимый запрос обрабатывается обычно |
| `test_direct_conflict` | конфликт обнаруживается и объясняется |
| `test_prohibited_solution_is_not_offered` | нарушающее решение не предлагается, есть альтернатива |
| `test_explicit_invariant_change` | явное изменение деактивирует старое правило |
| `test_ordinary_request_does_not_change_invariant` | обычный запрос правило не меняет |
| `test_invariant_persists_after_restart` | правила переживают перезапуск |
| `test_task_invariants_are_isolated` | правила задач не смешиваются |
| `test_conflict_with_unknown_rule_is_dropped` | модель не может выдумать правило |
| `test_invariants_do_not_touch_memory_or_task_state` | слои независимы |

Файл `tests/test_transitions.py` покрывает настраиваемый жизненный цикл:

| Тест | Что доказывает |
| --- | --- |
| `test_default_lifecycle_is_seeded` | стандартные состояния и правила создаются один раз |
| `test_create_state` / `test_update_state` | состояние создаётся и изменяется |
| `test_deactivate_and_activate_state` | состояние можно выключить и включить |
| `test_delete_unused_state` | неиспользуемое состояние удаляется |
| `test_cannot_delete_state_used_by_a_rule` | состояние под правилом защищено (409) |
| `test_only_one_initial_state` | начальное состояние ровно одно |
| `test_create_rule` / `test_update_rule` / `test_delete_rule` | CRUD правил |
| `test_rule_requires_existing_states` | правило не может ссылаться на несуществующее состояние |
| `test_duplicate_rule_is_refused` | дублирующее правило отклоняется (409) |
| `test_deactivate_rule_blocks_the_move` | выключенное правило запрещает переход |
| `test_condition_field_equals` | `plan_status == approved` выполняется, `pending` — нет |
| `test_condition_all_and_any` | групповые условия работают |
| `test_unknown_condition_type_is_refused` | неизвестный тип условия отклоняется |
| `test_allowed_transition` | `planning → execution` разрешён |
| `test_forbidden_transition_does_not_change_stage` | `planning → done` отклонён, stage не изменён |
| `test_condition_blocks_the_transition` | отказ называет условие и текущее значение |
| `test_available_transitions_report_the_verdict` | UI получает вердикт и причину |
| `test_history_records_success` / `test_history_records_rejection` | история пишет оба исхода |
| `test_ai_initiates_transition` | AI сам инициирует переход (`trigger=ai_detected`) |
| `test_ai_cannot_bypass_a_condition` | AI не может обойти условие |
| `test_ai_cannot_jump_over_a_stage` | прыжок через этап отклоняется |
| `test_ai_proposal_outside_the_allowed_set_is_dropped` | выдуманное состояние не применяется |
| `test_step_extractor_stage_goes_through_the_rules` | этап от экстрактора тоже проходит правила |
| `test_rules_reach_the_prompt` | правила уходят в модель |
| `test_rules_persist_after_restart` | правила переживают перезапуск |
| `test_rule_change_applies_without_restart` | изменение правила действует сразу |
| `test_new_rule_applies_without_restart` | новое правило действует сразу |
| `test_pause_keeps_stage_and_rules_still_apply` | пауза не обходит правила |
| `test_resume_uses_the_current_rules` | после resume действуют текущие правила |
| `test_blocked_request_is_not_executed` | запрос с запрещённым переходом не выполняется |
| `test_blocked_request_is_recorded_in_history` | отказ записывается в историю |
| `test_allowed_request_runs_and_advances_the_stage` | разрешённый запрос выполняется, stage меняется |
| `test_request_that_does_not_move_the_task_runs` | обычный вопрос выполняется |
| `test_gate_is_skipped_without_a_task` | без задачи проверка пропускается |
| `test_gate_is_skipped_without_active_rules` | без активных правил проверка пропускается |
| `test_blocked_request_in_streaming` | streaming тоже отказывает |
| `test_gate_uses_its_own_api_call` | проверка идёт отдельным запросом до ответа |
| `test_gate_does_not_block_when_the_model_is_unavailable` | сбой детектора не ломает чат |
| `test_invariant_conflict_wins_over_the_gate` | инварианты проверяются раньше |
| `test_step_extractor_does_not_move_the_stage` | фоновый пересчёт шага не двигает stage |
| `test_facts_endpoint_reports_the_values` | факты задачи видны через API |
| `test_facts_endpoint_lists_missing_fields` | недостающие поля правил перечислены |
| `test_setting_facts_unblocks_the_transition` | задать факт — и переход разрешён |
| `test_empty_fact_value_clears_it` | пустое значение очищает факт |
| `test_facts_cannot_forge_the_stage` | позицию задачи через факты не подменить |
| `test_refusal_names_the_missing_fact` | отказ называет незаданный факт |
| `test_refusal_shows_the_value_when_the_fact_is_set` | заданный факт показывается значением |
| `test_rule_check_reports_missing_fields` | проверка правила показывает недостающие поля |
| `test_facts_are_isolated_per_task` | факты задач не смешиваются |
| `test_facts_survive_a_restart` | факты переживают перезапуск |
| `test_facts_are_extracted_from_the_message` | факт читается из сообщения, переход выполняется |
| `test_extraction_marks_the_fact_as_read_from_the_message` | видно происхождение факта |
| `test_extraction_only_accepts_fields_the_rules_read` | выдуманный факт не сохраняется |
| `test_extraction_cannot_forge_the_stage` | позицию задачи извлечение не меняет |
| `test_low_confidence_extraction_is_ignored` | неуверенное значение не пишется |
| `test_extraction_does_not_overwrite_with_nothing` | пустое сообщение не затирает факты |
| `test_extraction_uses_its_own_api_call` | извлечение идёт отдельным запросом |
| `test_extraction_is_skipped_without_conditions` | без условий запрос не делается |
| `test_extraction_failure_does_not_break_the_chat` | сбой извлечения не ломает чат |
| `test_extracted_facts_are_isolated_per_task` | факты задач не смешиваются |
| `test_condition_ignores_yo_and_case` | «утвержден» и «утверждён» — одно значение |
| `test_lifecycle_is_separate_from_memory_and_invariants` | слои независимы |

---

## 15. Troubleshooting

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