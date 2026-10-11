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

## Reranking Experiment

Учебный модуль **«Реранкинг и фильтрация результатов поиска в RAG»** — второй этап
обработки результатов поверх обычного vector search:

```text
User Query
   ↓
Query Rewrite (опционально, локальная LLM)
   ↓
Embedding (nomic-embed-text через Ollama)
   ↓
FAISS Retrieval (Initial Top-K)
   ↓
Similarity Filter (опционально) → Deduplication (опц.) → MMR (опц.)
   ↓
Reranker (опционально)
   ↓
Final Top-K → RAG Context
```

Новые страницы: **«Reranking & Filtering»** (одиночный поиск со всеми этапами и
визуализацией pipeline) и **«Эксперимент»** (сравнение режимов по evaluation-dataset).
Новые endpoint'ы: `POST /api/rag/query-rewrite`, `POST /api/rag/retrieve`,
`POST /api/rag/filter`, `POST /api/rag/rerank`, `POST /api/rag/search`,
`GET /api/rag/rerankers/status`, `GET|POST /api/evaluation/datasets(…/run)`,
`GET /api/evaluation/runs/…`, `GET|POST /api/experiments(…/export|…/compare)`.

### Режимы

| Режим | Пайплайн |
|---|---|
| Baseline | Query → Embedding → FAISS → Top-K |
| Similarity Filter | … → Similarity Threshold → Top-K |
| Reranking | FAISS (Initial Top-K) → Cross-Encoder/Heuristic → Final Top-K |
| Query Rewrite | Query → LLM Rewrite → Embedding → FAISS |
| Rewrite + Rerank | … → Rewrite → FAISS → Reranker → Top-K |
| Full Pipeline | Rewrite → FAISS → Filter → Reranker → Final Top-K |

### Как это устроено честно

- **Reranking ≠ пересортировка по FAISS.** Ранжирование по `similarity` — это
  baseline; реранкер даёт **отдельный сигнал** по паре `query + chunk`:
  - `heuristic` — `0.7·semantic + 0.2·keyword + 0.1·metadata` (учебный);
  - `similarity` — контрольный слой (повтор retrieval-score);
  - `cross_encoder` — локальная cross-encoder модель (`BAAI/bge-reranker-base`
    через sentence-transformers). Модель/библиотеку нужно установить самому:
    `pip install sentence-transformers`; при отсутствии показывается понятное
    сообщение и предлагается fallback — автоматической подмены нет.
- **Query rewrite** использует **другую (генеративную) модель**, не
  `nomic-embed-text`: настройка `QUERY_REWRITE_MODEL` (пример `llama3.2`).
  Запрос пользователя обрабатывается строго как данные (system prompt выше,
  prompt-injection невозможен), длина ограничена. Если модель не установлена —
  ошибка с командой `ollama pull <model>`; никакого автоматического «подделывания».
- **Метрики** (Hit@K, Precision@K, Recall@K, MRR) вычисляются только при наличии
  ground truth из evaluation-dataset; без него показывается «N/A» + технические
  показатели (число кандидатов, отфильтрованных, средние similarity/reranker-score,
  latency) — **без слова «качество»**.
- **Правило фильтра:** `score >= threshold` → оставлен, `score < threshold` →
  отброшен (строго зафиксировано и протестировано).
- **Валидация:** `initial_top_k >= final_top_k`, `threshold ∈ [0;1]`, запрос не
  пустой и не длиннее 2000 символов, ошибки индексов/размерностей — понятные.

### Что показывается

- Визуальный pipeline с количеством на каждом этапе
  (`Retrieved: 20 → Passed threshold: 7 → Reranked: 7 → Final: 5`);
- таблица кандидатов: FAISS rank/score, reranker score/rank, final rank, статус
  (в финале / отфильтрован / дубликат / вне Top-K);
- **Rank Movement** — стрелки ↑ поднялся / ↓ опустился / → без изменений / ✕ отфильтрован;
- latency по этапам (rewrite/embedding/retrieval/filter/rerank/total);
- сравнение режимов в «Эксперименте», «Сохранить эксперимент» (SQLite), экспорт
  JSON/CSV, копирование итогового RAG-контекста.

### Фактические результаты (демо-корпус, nomic-embed-text, structural, K=5)

Прогон: evaluation-датасет из 10 вопросов к демонстрационному корпусу,
`initial_top_k=20`, `final_top_k=5`, порог фильтра 0.5, heuristic-реранкер.
Реальные метрики (не выдуманы):

| Режим | Hit@5 | Precision@5 | Recall@5 | MRR | Latency, ms | Ошибки |
|---|---|---|---|---|---|---|
| Baseline | 0.900 | 0.320 | 0.767 | 0.390 | ~19 | 0 |
| Filter (0.5) | 0.900 | 0.320 | 0.767 | 0.390 | ~18 | 0 |
| Reranking (heuristic) | 0.800 | 0.300 | 0.717 | 0.370 | ~20 | 0 |
| Query Rewrite* | — | — | — | — | — | 10 |
| Rewrite + Rerank* | — | — | — | — | — | 10 |
| Full Pipeline* | — | — | — | — | — | 10 |

\* В среде без установленной generative-модели режимы rewrite дают ошибку
«Модель … не установлена» (10 из 10 вопросов). Установите модель
(`ollama pull llama3.2`) — режимы заработают автоматически (путь pipeline
проверен интеграционными тестами с мок-rewriter'ом).

**Выводы по факту:** на этом корпусе при данных параметрах реранкинг/heuristic
**не улучшили** метрики (0.90 → 0.80 Hit@5), а порог 0.5 ничего не отсекал.
Это ожидаемый учебный результат: польза reranker'а проявляется на корпусе, где
retrieval-similarity плохо предсказывает релевантность; он увеличивает latency.
Никакого «реранкинг всегда лучше» — только измерение.

### Почему так устроено (шпаргалка)

- **Reranking vs retrieval:** retrieval находит похожие по вектору кандидатов,
  reranker оценивает релевантность пары `query+document` отдельной моделью — они
  дают разные порядки.
- **Зачем Initial Top-K:** маленький K рискует потерять релевантные чанки до
  фильтра/реранкера; большой — шум и latency. Final Top-K — размер контекста RAG.
- **Зачем threshold:** отсечение шума; слишком высокий порог удаляет полезные
  результаты (чей similarity ниже, но релевантность выше).
- **Почему reranker дороже:** cross-encoder вычисляет пары `query×chunk`
  (N прямых прогонов модели), в отличие от одного embedding запроса.
- **Почему rewrite полезен и опасен:** уточняет неясный запрос терминами корпуса,
  но может изменить намерение и увеличить latency — оценивается только на
  evaluation-датасете, где есть ground truth.

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
| «Cross-encoder не установлен» в Reranking | Установите: `pip install sentence-transformers` (модель подтянется сама) или выберите Heuristic/отключите реранкинг |
| «Модель для query rewrite не установлена» | Выполните `ollama pull llama3.2` (или замените `QUERY_REWRITE_MODEL` в настройках на доступную generative-модель) |
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
- Cross-encoder реранкер требует локальной установки `sentence-transformers` и модели
  (в обычном окружении — недоступен с понятной ошибкой и fallback на heuristic).
- Query rewrite работает только при установленной генеративной модели Ollama
  (например `ollama pull llama3.2`); без неё такие режимы эксперимента дают ошибку.
---

# Grounded RAG: ответы с источниками, цитатами и контролем релевантности

Новый учебный слой поверх существующего retrieval: каждый ответ grounded в найденных
чанках, содержит источники и цитаты, и имеет ДВА защитных gate против выдумывания
(«не знаю» вместо галлюцинации).

## Pipeline

```text
Question
   ↓
Query Rewrite (optional)
   ↓
Embedding
   ↓
FAISS Retrieval (Initial Top-K)
   ↓
Filtering
   ↓
Reranking
   ↓
Relevance Gate  ── FAIL → «Не знаю» (LLM не вызывается)
   ↓ PASS
Context
   ↓
LLM (structured JSON: answer + claims с chunk_id)
   ↓
Grounding Validator  ── FAIL → «Не знаю» (grounding_failed)
   ↓ PASS
Citations (backend извлекает цитаты из реальных чанков)
   ↓
Answer + Sources + Citations + Claims
```

## Как это работает

* **Relevance Gate (Gate 1)**. Перед вызовом generative-модели оценивается лучший сигнал
  релевантности найденных чанков (`reranker_score`, либо `retrieval_score`). Если он ниже
  `answer_relevance_threshold` ИЛИ подтверждающих чанков меньше, чем
  `min_supporting_chunks` — возвращается `insufficient_context`, LLM вообще не вызывается.
* **Grounding (Gate 2)**. Сгенерированный ответ разбивается на claims. Каждый claim должен
  ссылаться на реальный `chunk_id` из retrieval-результата и иметь текстовую поддержку
  (лексическую + опциональную embedding-проверку `claim ↔ chunk`). Доля подтверждённых
  claims = `grounding_score`. Если `grounding_score < grounding_threshold` — `grounding_failed`.
* **Цитаты формирует backend, а не LLM**. Модель возвращает только `chunk_id`; фрагмент
  цитаты извлекается из реального текста чанка и проверяется, что он является его подстрокой
  (`validate_quote`). Поэтому несуществующие/придуманные цитаты невозможны.
* **Источники формирует backend** из реальных metadata чанков — LLM не может подсунуть
  фиктивное имя документа (защита от source injection).
* **Защита от prompt injection в документах**. Системный промпт явно объявляет найденные
  документы «недоверенными данными»: инструкции внутри документов игнорируются.

## Почему «не знаю» — это корректно

Если найденные документы не подтверждают ответ, система НЕ придумывает его, а возвращает
`insufficient_context` или `grounding_failed` с пустыми `sources`/`citations`. Это валидный
результат RAG, а не ошибка сервера.

## Чем relevance отличается от grounding

* **Relevance score** — насколько подходит найденный КОНТЕКСТ (до генерации; например
  0.91). Это не «вероятность правильного ответа».
* **Grounding score** — насколько сформированный ОТВЕТ подтверждается этими чанками
  (после генерации; доля подтверждённых claims).

## API

* `POST /api/rag/answer` — grounded-ответ. Тело: `{collection_id, strategy, query, config}`.
  Ответ: `{status, answer, sources[], citations[], claims[], grounding{}, retrieval{}, latency{}}`.
* `GET /api/rag/answers`, `GET/DELETE /api/rag/answers/{id}` — история ответов.
* `POST /api/rag/evaluation/dataset` — создать датасет grounded-оценки (10 вопросов).
* `POST /api/rag/evaluation/run` — прогон 10 вопросов, считает метрики.
* `GET /api/rag/evaluation/runs`, `GET /api/rag/evaluation/runs/{id}` — история оценок.

Статусы ответа: `answered`, `insufficient_context`, `grounding_failed`.

## RAG Evaluation (10 вопросов)

Для оценки качества создан датасет из 10 вопросов (9 — по демонстрационному корпусу,
1 — намеренно без ответа в документах для проверки честного отказа). По каждому вопросу
проверяется: наличие ответа, источников, цитат, валидность цитат, grounded-ность и число
неподтверждённых claims. Итоговые метрики:

* **Source Coverage** — доля ответов с источниками;
* **Citation Coverage** — доля ответов с цитатами;
* **Citation Validity** — доля валидных цитат;
* **Grounding Accuracy** — доля grounded-ответов;
* **Abstention Accuracy** — доля корректных отказов «не знаю».

Все метрики считаются по фактическим результатам — без заранее заданных чисел.

## Настройка

В `Settings` (и `.env`) добавлены:

```env
ANSWER_MODEL=llama3.2                 # генеративная модель Ollama для ответов
DEFAULT_RELEVANCE_THRESHOLD=0.65       # Gate 1
DEFAULT_GROUNDING_THRESHOLD=0.70       # Gate 2
DEFAULT_MIN_SUPPORTING_CHUNKS=1        # минимум подтверждающих чанков
GROUNDING_SIMILARITY_THRESHOLD=0.70    # семантическая проверка claim↔chunk
```

Для работы ответов нужна установленная генеративная модель, например:
`ollama pull llama3.2`.

## Тесты

`backend/tests/unit/test_grounded_answer.py` и `test_grounded_service.py` — unit-тесты
relevance gate, цитат, источников, grounding-валидатора, abstention и схем.
`backend/tests/integration/test_grounded_answer_api.py` — HTTP-тесты (с фейковыми
embedding-клиентом и LLM). Все тесты работают без установленного Ollama.

## Известные ограничения

* Для реальной генерации ответа нужна установленная generative-модель Ollama;
  пока она отсутствует — `/api/rag/answer` возвращает понятную ошибку с командой установки.
* Семантическая проверка claims использует embedding-модель и может деградировать к
  лексической при недоступности эмбеддингов.
* Источники и цитаты содержат реальный текст чанков, но полный «Show source chunk»
  показывается по фрагменту цитаты (полный текст чанка доступен через Возможность расширения).

---

# Chat Architecture: диалог с историей и Task Memory поверх существующего RAG

Чат — это **не отдельная подсистема**, а тонкий слой поверх единого RAG pipeline.
Никакой второй RAG не создаётся: используется существующий retrieval, reranker,
relevance gate, grounding validator и citation builder.

```text
Message
   ↓
Conversation History
   ↓
Task Memory (цель/ограничения/решения/фокус)
   ↓
Contextual Query (разрешение местоимений + текущая задача)
   ↓
RAG (embedding → FAISS → reranking → relevance gate)
   ↓
LLM (получает Task State + история + RAG-контекст)
   ↓
Grounding Validator →
   ↓
Citations (backend формирует из реальных чанков)
   ↓
Save message + Update Task Memory
```

## Conversation History

Каждое сообщение (включая неуспешные «не знаю») сохраняется в SQLite. В промпт LLM
попадают только последние релевантные сообщения (лимит `MAX_HISTORY_MESSAGES=10`,
`MAX_HISTORY_TOKENS=6000`) вместе с Task Memory.

## Task Memory

Структурированная память задачи: `goal`, `constraints`, `defined_terms`,
`decisions`, `open_questions`, `current_focus`, `version`. Отличается от истории:
история — «что сказано», Task Memory — «что сейчас важно».

Решения версионируются: смена `FAISS → Chroma` помечает FAISS как `superseded`,
активным становится Chroma. State основан только на подтверждённых пользователем
данных (`source=user_message`), версия растёт при каждом изменении.

## Contextual Query

Короткий вопрос («А какой лучше?», «Почему?») разрешается через Task Memory и
восстанавливается в полноценный поисковый запрос. Query Rewrite не изменяет смысл
и не добавляет требований пользователя.

## Гарантии

* Каждое сообщение проходит через RAG (embedding → FAISS → reranking → relevance gate).
* Task Memory и история помогают формулировать запрос, но НЕ заменяют RAG-контекст.
* LLM отвечает только по найденному контексту, источник/`chunk_id`/цитату формирует backend.
* Если релевантность ниже порога или grounding не подтверждается — честный отказ «не знаю».

## API чата

* `POST /api/chat` — `{conversation_id?, message, collection_id?, strategy?}` → полный ответ
  с `task_state`, `sources`, `citations`, `grounding`, `search_query`.
* `POST /api/chat/new` — новая изолированная беседа.
* `GET /api/chat/{id}` — история + task_state.
* `GET /api/chat/{id}/state` — Task Memory.
* `GET /api/chat` — список бесед.
* `POST /api/chat/evaluation/run` — прогон сценариев длинного диалога, метрики.

## Как оценивается чат

Два автоматизированных сценария (по 12 и 13 сообщений) прогоняют полный pipeline
и считают честные метрики: RAG Call Coverage, Reranking Coverage, Source Coverage,
Citation Coverage, Grounding Accuracy, Goal/Constraint/Decision Retention,
Contextual Query Accuracy, Abstention.

## Запуск чата

Backend и frontend запускаются как обычно (см. выше); страница чата — `http://localhost:5173/chat`.
Для реальных ответов нужна установленная generative-модель Ollama (`ollama pull llama3.2`).
