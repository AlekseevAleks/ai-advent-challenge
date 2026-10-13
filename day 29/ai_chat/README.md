# AI Chat

Локальный сервис ИИ-чата с веб-интерфейсом. Работает с любым OpenAI-совместимым API
(OpenAI, OpenRouter, локальные серверы вроде LM Studio / Ollama / vLLM и т. п.).
Адрес API и ключ задаёт пользователь в настройках.

## Возможности

- Настройки подключения (`api_url`, `api_key`, `default_model`) с проверкой соединения.
- Загрузка списка моделей из `GET {api_url}/models` и выбор модели при создании чата.
- Чаты с историей сообщений, авто-заголовком по первому сообщению и удалением.
- **Стриминговый** ответ ассистента (SSE) с кнопкой «Стоп».
- Markdown-рендер ответов с подсветкой блоков кода.
- Экспорт чата в Markdown, поиск по чатам, хоткей `Ctrl+K`.
- Тёмная тема, адаптивная вёрстка (на мобильных панель табов уходит вниз).
- Ключ API никогда не отдаётся на фронтенд в открытом виде — только маска `sk-...abcd`.

## Слои памяти агента

Агент использует три слоя памяти (модуль `memory_layers.py`):

| Слой | Что хранит | Где хранится | Политика |
|------|------------|--------------|----------|
| **short-term** | последние сообщения диалога (role + content + timestamp) | in-memory, ключ — `session_id` (chat_id) | FIFO, лимит 20 сообщений / ~2000 токенов |
| **working** | цель, ограничения, план, промежуточные результаты, статус | in-memory, ключ — `session_id` | живёт пока задача активна; при завершении «схлопывается» в long-term |
| **long-term** | профиль, устойчивые предпочтения, итоги задач | SQLite (`memory.db`), ключ — `user_id` | сохраняется между сессиями |

Единый интерфейс — `MemoryManager`:

```python
read_short_term(session_id)          # -> list[dict]
read_working(session_id)             # -> dict
read_long_term(user_id)              # -> list[dict]
add_short_term(session_id, message)  # -> dict
update_working(session_id, key, value)
save_long_term(user_id, fact, metadata)
```

Роутер записи `decide_where_to_store(fact)` возвращает слой и обоснование:

- явное предпочтение («предпочитаю», «запомни», «меня зовут») или факт,
  подтверждённый ≥2 раз → `long`;
- маркеры задачи («цель», «нужно сделать», «дедлайн») → `working`;
- остальное → `short`.

Сборка промта (`build_prompt_messages`) формирует контекст:
`system` (long-term top-k по релевантности) + `system` (working) + short-term + текущий вопрос.

### Дашборд памяти

Экран `/dashboard/memory` показывает все три слоя одновременно в реальном времени
(автообновление раз в секунду):

- три колонки: SHORT-TERM (синий), WORKING (оранжевый), LONG-TERM (зелёный);
- счётчики записей и оценка токенов;
- кнопки «Схлопнуть в long-term» и «Очистить» для рабочей памяти;
- поиск и удаление фактов в long-term;
- чекбоксы слоёв — ablation вживую;
- блок «Собранный промт для LLM» с подсветкой источника каждого блока;
- лог маршрутизации: кто и куда записал.

Эндпоинты дашборда:

| Метод  | Путь                              | Назначение                          |
|--------|-----------------------------------|-------------------------------------|
| GET    | `/dashboard/memory`               | Экран мониторинга памяти            |
| GET    | `/memory/short-term?session_id=`  | Краткосрочная память                |
| GET    | `/memory/working?session_id=`     | Рабочая память                      |
| GET    | `/memory/long-term?user_id=`      | Долговременная память               |
| GET    | `/memory/snapshot?session_id=&user_id=` | Все три слоя одним ответом    |
| GET    | `/memory/prompt-preview?session_id=&user_id=&message=` | Собранный промт |
| GET    | `/memory/events?limit=`           | Журнал маршрутизации                |
| DELETE | `/memory/events`                  | Очистить журнал                     |
| POST   | `/memory/working/collapse`        | Схлопнуть working в long-term       |
| DELETE | `/memory/long-term/{fact_id}`     | Удалить факт                        |
| PATCH  | `/memory/toggles`                 | Вкл/выкл слои (ablation)            |

### Демонстрация

```bash
python demo_memory.py
```

Скрипт прогоняет диалог из 4 реплик, логирует содержимое каждого слоя после
каждого шага и выполняет ablation-эксперимент (отключение слоёв) — видно, как
меняется контекст и ответ агента.

### Ablation через API

В теле `POST /api/chats/{id}/messages` можно передать `memory_layers`:

```json
{ "content": "...", "memory_layers": ["short", "long"] }
```

По умолчанию включены все три слоя.
## Структура проекта

```
ai_chat/
├── main.py              # FastAPI-приложение и роуты
├── config_manager.py    # Работа с config.json
├── chats_manager.py     # Работа с chats.json
├── api_client.py        # Обёртка над OpenAI-совместимым API
├── memory_layers.py     # Три слоя памяти + MemoryManager + роутер
├── demo_memory.py       # Демо слоёв памяти и ablation-эксперимент
├── templates/memory_dashboard.html  # Экран мониторинга памяти
├── static/memory_dashboard.js       # Логика дашборда
├── static/memory_dashboard.css      # Стили дашборда
├── templates/index.html # Интерфейс
├── static/style.css     # Стили
├── static/app.js        # Клиентская логика (SPA)
├── config.json          # Генерируется автоматически
├── chats.json           # Генерируется автоматически
└── memory.db            # SQLite для long-term (генерируется автоматически)
```
## Установка и запуск

Требуется Python 3.11+ (код совместим и с 3.9).

```bash
cd ai_chat
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Откройте <http://127.0.0.1:8000>. Альтернативный запуск с автооткрытием браузера:

```bash
python main.py
```

## Первые шаги

1. Откройте таб ⚙️ **Настройки**, укажите `API URL` (например, `https://api.openai.com/v1`),
   `API Key` и модель по умолчанию.
2. Нажмите **Проверить подключение** — должен появиться статус ✅ и число доступных моделей.
3. Нажмите **Сохранить**.
4. Таб ➕ **Новый чат** → выберите модель (есть поиск) → **Создать**.
5. Напишите сообщение и нажмите `Enter`. Ответ появится по мере генерации.

## API приложения

| Метод  | Путь                        | Назначение                          |
|--------|-----------------------------|-------------------------------------|
| GET    | `/`                         | Интерфейс                           |
| GET    | `/api/config`               | Текущий конфиг (ключ маскирован)    |
| POST   | `/api/config`               | Сохранить конфиг                    |
| POST   | `/api/config/test`          | Проверить подключение               |
| GET    | `/api/models`               | Список моделей из внешнего API      |
| GET    | `/api/chats`                | Список чатов                        |
| POST   | `/api/chats`                | Создать чат                         |
| GET    | `/api/chats/{id}`           | Чат с сообщениями                   |
| DELETE | `/api/chats/{id}`           | Удалить чат                         |
| POST   | `/api/chats/{id}/clear`     | Очистить историю                    |
| GET    | `/api/chats/{id}/export`    | Экспорт чата в Markdown             |
| POST   | `/api/chats/{id}/messages`  | Отправить сообщение (SSE-стрим)     |
| GET    | `/api/memory/{id}`          | Снимок всех слоёв памяти чата       |
| DELETE | `/api/memory/{id}`          | Очистить short-term и working       |

## Хранение данных

- `config.json` — адрес API, ключ, модель по умолчанию.
- `chats.json` — список чатов и сообщений.
- `memory.db` — SQLite с фактами long-term памяти (по `user_id`).
- `logs/` — JSON-логи запросов к внешнему API.

Все файлы создаются автоматически при первом запуске и сохраняются между перезапусками.

Оба файла создаются автоматически при первом запуске и сохраняются между перезапусками.