# RAG Document Indexing Lab

Локальное веб-приложение для изучения и демонстрации процесса индексации документов
для Retrieval-Augmented Generation (RAG):

**загрузка файлов → извлечение текста → chunking (Fixed-size и Structural) →
эмбеддинги через локальный Ollama (`nomic-embed-text`) → векторные индексы FAISS →
семантический поиск → сравнение стратегий.**

Всё работает локально: никакие документы не отправляются во внешние сервисы.

---

## Возможности

- Загрузка нескольких файлов (drag-and-drop + диалог): PDF, DOCX, TXT, Markdown (MD/MDX),
  RST, Python, JavaScript/TypeScript, HTML, JSON, YAML, XML, CSV, SQL и другие текстовые форматы.
- Извлечение текста: постранично у PDF (с номерами страниц), заголовки Markdown/DOCX/RST,
  классы и функции Python/JS/TS, читаемое представление CSV/JSON. Предупреждение об OCR
  для сканированных PDF.
- Две стратегии chunking с собственными параметрами и валидацией:
  - **Fixed-size**: размер, overlap, единица (символы / токены при наличии `tiktoken`),
    аккуратные границы предложений и слов;
  - **Structural**: заголовки, функции/классы, страницы PDF, разделы; рекурсивное деление
    больших разделов, объединение мелких, fallback на абзацы. Хранит путь заголовков и символы.
- Эмбеддинги через локальный **Ollama** (`/api/embed` + fallback на `/api/embeddings`),
  повторные попытки с backoff, проверка размерности и конечности значений, тест подключения.
- Векторные индексы **FAISS** (cosine similarity: нормализованные векторы + `IndexFlatIP`),
  метаданные чанков в JSON, атомарная публикация, контроль целостности, защита от
  параллельной записи, запрет добавления в несовместимый индекс.
- **SQLite** для состояния, коллекций и истории запусков; переживает перезапуск приложения.
- Семантический поиск Top-K с метаданными и оценкой сходства.
- Сравнение стратегий по фактическим метрикам с графиками (recharts).
- Демонстрационный корпус из 5 документов — кнопка «Загрузить демонстрационные документы».
- Тёмная/светлая тема, русский интерфейс (i18n-ready).

## Архитектура

```
RAG service/
├── backend/                  # FastAPI + Python 3.11+
│   ├── app/
│   │   ├── main.py           # приложение, CORS, обработчики ошибок
│   │   ├── config.py         # настройки (.env + рантайм-переопределения)
│   │   ├── api/              # роутеры: health, ollama, documents, indexing,
│   │   │                     #   collections, search, comparison, history, settings
│   │   ├── models/           # доменные модели (Document, Collection, IndexRecord)
│   │   ├── schemas/          # Pydantic-схемы запросов/ответов
│   │   ├── services/
│   │   │   ├── text_extractor.py   # извлечение текста по форматам
│   │   │   ├── chunking/           # fixed_size.py, structural.py, common.py
│   │   │   ├── ollama_service.py   # клиент Ollama (эмбеддинги)
│   │   │   ├── faiss_store.py      # FAISS + JSON-метаданные, атомарное сохранение
│   │   │   ├── indexing_service.py # оркестрация задания
│   │   │   ├── job_service.py      # фоновые задания, отмена, прогресс
│   │   │   ├── search_service.py   # поиск Top-K
│   │   │   ├── comparison_service.py
│   │   │   └── stats_service.py    # сводка для «Обзора»
│   │   └── repositories/      # SQLite
│   ├── tests/                 # unit + интеграционные (без Ollama, фейковый клиент)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                 # React + TypeScript + Vite + Tailwind + Recharts + Lucide
│   ├── src/
│   │   ├── pages/            # 7 страниц
│   │   ├── components/       # layout, ui (shadcn-стиль), charts, documents, indexing, comparison
│   │   ├── services/api.ts   # типизированный REST-клиент
│   │   ├── types/api.ts
│   │   └── app/i18n/         # i18n (русский, с запасом под английский)
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

Хранилище по умолчанию: `backend/storage/`

```
storage/
├── app.db                        # SQLite: документы, коллекции, индексы, задания, настройки
├── uploads/<doc_id>/             # оригиналы файлов + extracted.json (кэш текста)
└── collections/<collection_id>/
    ├── fixed_size/
    │   ├── index.faiss           # векторы (позиция = запись в metadata.json)
    │   ├── metadata.json         # метаданные чанков в том же порядке
    │   └── config.json           # модель, размерность, параметры chunking, схема
    └── structural/               # то же для второй стратегии
```

---

## Вариант A. Локальная разработка

### 1. Предварительные требования

- **Python 3.11+** — проверьте: `python3 --version`
- **Node.js 20+** — проверьте: `node --version`
- **Ollama** — скачайте с [ollama.com](https://ollama.com) и запустите сервис.

### 2. Ollama и модель эмбеддингов

```bash
ollama pull nomic-embed-text     # загрузка модели (~260 МБ)
ollama list                       # проверить наличие
```

Проверить, что API отвечает:

```bash
curl http://localhost:11434/api/version
```

### 3. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Swagger UI: http://127.0.0.1:8000/docs

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Веб-интерфейс: **http://localhost:5173**

Vite проксирует `/api` на `http://localhost:8000`, отдельная настройка не нужна.

### 5. Быстрая проверка

1. Откройте http://localhost:5173 — на странице «Обзор» статус Ollama должен быть «онлайн».
2. Перейдите в «Документы» → «Загрузить демонстрационные документы» (5 файлов).
3. «Индексация» → выберите все документы, обе стратегии → «Запустить индексацию».
   Прогресс отображается в реальном времени.
4. «Сравнение стратегий» → метрики и графики по обеим стратегиям.
5. «Поиск по индексу» → выберите коллекцию и стратегию, введите запрос, например
   «зачем нужна индексация в RAG», нажмите «Найти».
6. «История запусков» → статистика задания (хранится в SQLite).

### 6. Собственные документы (требование о 20–30 страницах)

Загрузите свои файлы через «Документы» (многократно, до 100 файлов за запрос,
до 50 МБ на файл — лимиты настраиваются). Для учебного объёма 20–30 страниц подойдут:
5–8 PDF-файлов по 3–5 страниц или Markdown-файлы по 500–1500 символов (≈ 2–4 страницы
каждый). После загрузки создайте коллекцию и запустите индексацию. Файлы можно добавить
позже через режим «Добавить документы в существующий индекс».

---

## Вариант B. Docker

```bash
docker compose up --build
```

- Frontend: http://localhost:8080
- Backend API: http://localhost:8000, Swagger: http://localhost:8000/docs
- Данные сохраняются в `./docker-data/storage` (постоянный том).

**Ollama остаётся на хост-машине** — контейнер обращается к нему по
`http://host.docker.internal:11434` (переменная `OLLAMA_URL` в `docker-compose.yml`).

> **Linux без Docker Desktop:** `host.docker.internal` резолвится через
> `extra_hosts: host-gateway` (работает в Compose ≥ 2.20). Если у вас это не работает,
> укажите адрес шлюза явно: `OLLAMA_URL: http://172.17.0.1:11434` (проверьте `ip route`)
> либо `network_mode: host` для сервиса backend.

---

## Конфигурация

Все настройки backend задаются в `backend/.env` (см. `backend/.env.example`) и могут
переопределяться в рантайме на странице «Настройки» (сохраняются в SQLite):

| Переменная | По умолчанию | Описание |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | адрес Ollama |
| `EMBEDDING_MODEL` | `nomic-embed-text` | модель эмбеддингов |
| `EMBEDDING_BATCH_SIZE` | `32` | texts за один запрос |
| `EMBEDDING_RETRIES` | `3` | повторные попытки с backoff |
| `OLLAMA_TIMEOUT` / `OLLAMA_CONNECTION_TIMEOUT` | `120` / `10` | таймауты, c |
| `MAX_FILE_SIZE_MB` | `50` | лимит размера файла |
| `MAX_FILES_PER_REQUEST` | `100` | лимит файлов за запрос |
| `STORAGE_DIR` | `storage` | директория данных |
| `DEFAULT_CHUNK_SIZE` / `DEFAULT_CHUNK_OVERLAP` | `1200` / `200` | параметры fixed-size |
| `DEFAULT_STRUCTURAL_MAX/MIN_CHUNK_SIZE` | `1500` / `200` | параметры structural |
| `CORS_ORIGINS` | `http://localhost:5173,…` | разрешённые origin frontend |

Смена модели эмбеддингов выводит из строя существующие индексы: их нужно перестроить
(режим «Перестроить» на странице «Индексация»). Backend запрещает добавление векторов
в индекс с несовместимой моделью или параметрами.

## REST API (кратко)

- `GET /api/health`, `GET /api/stats/overview`
- `GET /api/ollama/status`, `POST /api/ollama/test`, `GET /api/ollama/models`
- `POST /api/documents/upload` (multipart `files`), `GET /api/documents`,
  `GET /api/documents/{id}/text`, `DELETE /api/documents/{id}`, `POST /api/documents/{id}/extract`,
  `POST /api/documents/demo`
- `POST /api/indexing/jobs`, `GET /api/indexing/jobs`, `GET /api/indexing/jobs/{id}`
  (прогресс), `GET /api/indexing/jobs/{id}/result`, `POST /api/indexing/jobs/{id}/cancel`
- `GET/POST /api/collections`, `GET /api/collections/{id}`, `GET /api/collections/{id}/indexes`,
  `GET /api/indexes/{index_id}/stats|chunks|chunks/{chunk_id}`, `DELETE /api/indexes/{index_id}`
- `POST /api/search` — Top-K поиск (cosine similarity)
- `GET /api/comparison`, `GET /api/comparison/{collection_id}`
- `GET /api/history`, `GET /api/history/{job_id}`
- `GET/PATCH /api/settings`

Описания и интерактивные примеры — в Swagger UI на `/docs`.

## Тестирование

Обычные тесты не требуют Ollama (клиент эмбеддингов подменяется на фейковый):

```bash
cd backend
.venv/bin/pytest
```

Покрыто: извлечение TXT/PDF/DOCX/Markdown/CSV/JSON, структура Python/JS, обе стратегии
chunking (overlap, пустые документы, длинные разделы, fallback), метаданные, статистика,
совместимость индекса, загрузка нескольких файлов, создание/сохранение/загрузка FAISS,
соответствие позиций FAISS↔метаданные, поиск Top-K, отмена задания, обработка ошибок Ollama.

**Тест с настоящим Ollama** (запущенный сервис + загруженная модель):

```bash
cd backend
.venv/bin/pytest -m real_ollama
```

Запуск вручную: `uvicorn app.main:app --reload`, затем в браузере выполните сценарий
из раздела «Быстрая проверка».

## Решение типичных проблем

| Проблема | Решение |
|---|---|
| «Ollama недоступен» в шапке | Запустите `ollama serve` (или приложение Ollama); проверьте `curl localhost:11434/api/version` и адрес в «Настройках» |
| «Модель не установлена» при проверке | Выполните `ollama pull nomic-embed-text` (кнопка на странице «Индексация» копирует команду) |
| Медленная индексация | Уменьшите batch или chunks; эмбеддинги считаются процессором |
| «Индекс несовместим» при добавлении | Изменены модель/размерность/параметры chunking — выберите «Перестроить» или создайте новый индекс |
| Токены недоступны | Единица «токены» требует `pip install tiktoken` (не входит в requirements по умолчанию) |
| Сканированный PDF без текста | Требуется OCR — приложение показывает предупреждение и не утверждает, что текст извлечён |
| Порт занят | `uvicorn ... --port 8001` + правка прокси в `frontend/vite.config.ts` |
| CORS-ошибки | Добавьте origin frontend в `CORS_ORIGINS` (backend/.env) |

## Известные ограничения

- FAISS `IndexFlatIP` — точный (не приближённый) индекс; для миллионов векторов потребуется IVF/HNSW.
- Подсчёт «токенов» требует `tiktoken`; без него — только символы.
- OCR для сканированных PDF не реализован (по ТЗ необязателен) — показывается предупреждение.
- HTML/XML/YAML сохраняются как исходный текст (без потери содержимого), разметка не удаляется.
- При перезапуске приложения незавершённые задания помечаются как «прерваны перезапуском».
- Генерация ответов LLM (chat) не входит в приложение: реализованы индексация и retrieval.