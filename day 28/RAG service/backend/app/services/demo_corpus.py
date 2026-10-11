"""Демонстрационный корпус документов.

Позволяет проверить приложение сразу после запуска: загружаются через
POST /api/documents/demo. Это учебные примеры, а не полноценный корпус.
"""

from __future__ import annotations

from typing import Dict, List

from ..schemas.documents import UploadResponse
from .document_loader import loader

DEMO_FILES: Dict[str, str] = {
    "rag_principles.md": """# RAG: извлечение с генерацией

## Что такое RAG

Retrieval-Augmented Generation (RAG) — подход, при котором языковая модель
генерирует ответ, опираясь на документы корпуса, найденные по запросу.
Такой подход снижает галлюцинации и позволяет отвечать по внутренней базе знаний.

## Основные этапы RAG

1. Индексация: документы разбиваются на чанки, для каждого строится вектор.
2. Извлечение (retrieval): по запросу ищутся наиболее похожие чанки.
3. Генерация: найденные чанки попадают в контекст языковой модели.

## Зачем нужна индексация

Качество RAG напрямую зависит от качества индекса: как выбраны границы чанков,
насколько точны эмбеддинги и как устроен поиск. Плохой chunking приводит к потере
смысловых фрагментов даже при сильной модели генерации.

## Компромиссы при выборе стратегии

Маленькие чанки точнее локализуют ответ, но теряют контекст. Большие чанки
сохраняют контекст, но снижают точность поиска. Оптимальный размер зависит от
корпуса и типа вопросов.

## Заключение

RAG — практичный способ использовать актуальные данные вместе с языковой
моделью. Эксперименты с chunking и векторизацией — ключ к качеству системы.
""",
    "embeddings_guide.md": """# Векторные представления текста

## Что такое эмбеддинг

Эмбеддинг — это вектор чисел, описывающий смысл текста. Близкие по смыслу
тексты получают близкие векторы. Модель nomic-embed-text преобразует текст
в вектор размерности 768.

## Метрики сходства

- Косинусное сходство: угол между векторами, диапазон от −1 до 1.
- Евклидово расстояние: обычное расстояние между точками.
- Для RAG обычно используют косинусное сходство: оно не зависит от длины текста.

## Почему нужна нормализация

При косинусном сходстве важна только ориентация вектора, а не его длина.
Нормализация к единичной длине позволяет искать через скалярное произведение
(Inner Product) в FAISS — это быстрее и проще.

## Практические советы

Для эмбеддингов важна согласованность: запрос и документы должны обрабатываться
одной моделью. Меняя модель, перестраивайте индекс, иначе размерности могут
не совпасть.
""",
    "faiss_and_search.md": """# FAISS и векторный поиск

## Введение

FAISS (Facebook AI Similarity Search) — библиотека для быстрого поиска
похожих векторов. Она хранит векторы в специальных структурах и умеет
искать ближайших соседей за миллисекунды даже на миллионах точек.

## Как устроен поиск

1. Запрос превращается в вектор той же моделью, что и документы.
2. FAISS ищет векторы, наиболее близкие к вектору запроса.
3. По позициям найденных векторов достаются метаданные чанков.

## IndexFlatIP

Это простой и точный индекс на основе скалярного произведения. Для умеренных
объёмов данных он оптимален. Существуют более быстрые, но приближённые индексы
(IVF, HNSW) — они нужны для миллионов векторов.

## Координация индекс и метаданные

Номер вектора в индексе совпадает с номером записи в JSON-файле метаданных.
Это ключевое условие целостности: проверка выполняется при каждой операции.

## Ограничения

Векторный поиск находит похожие фрагменты, но не гарантирует их релевантность
вопросу. Cosine similarity — мера сходства, а не истинность ответа.
""",
    "example_rag_pipeline.py": """\"\"\"Пример пайплайна RAG: от загрузки до поиска.

Учебный код: классы и функции для демонстрации структурного chunking.
\"\"\"

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Document:
    title: str
    text: str
    source: str = "local"
    tags: List[str] = field(default_factory=list)

    def word_count(self) -> int:
        return len(self.text.split())


class Chunker:
    \"\"\"Базовый класс стратегий разбиения.\"\"\"

    def __init__(self, max_size: int = 1500):
        self.max_size = max_size

    def split(self, text: str) -> List[str]:
        raise NotImplementedError


class FixedSizeChunker(Chunker):
    def split(self, text: str) -> List[str]:
        return [
            text[i:i + self.max_size]
            for i in range(0, len(text), self.max_size)
        ]


class StructuralChunker(Chunker):
    def split(self, text: str) -> List[str]:
        sections = []
        current = []
        for line in text.splitlines():
            if line.startswith("#") and current:
                sections.append("\n".join(current))
                current = []
            current.append(line)
        if current:
            sections.append("\n".join(current))
        return sections


class EmbeddingModel:
    def embed(self, texts: List[str]) -> List[List[float]]:
        \"\"\"В реальном приложении здесь Ollama + nomic-embed-text.\"\"\"
        raise NotImplementedError


class Index:
    def __init__(self, model: EmbeddingModel):
        self.model = model
        self.vectors: List[List[float]] = []
        self.metadata: List[dict] = []

    def add(self, chunks: List[dict]):
        vectors = self.model.embed([c["text"] for c in chunks])
        self.vectors.extend(vectors)
        self.metadata.extend(chunks)


def build_pipeline(chunker: Chunker, model: EmbeddingModel, docs: List[Document]) -> Index:
    \"\"\"Собрать индекс из документов выбранной стратегией.\"\"\"
    index = Index(model)
    for doc in docs:
        parts = chunker.split(doc.text)
        meta = [
            {"title": doc.title, "text": t, "section": None}
            for t in parts
        ]
        index.add(meta)
    return index
""",
    "project_documentation.md": """# Документация проекта

## Установка

### Предварительные требования

Перед началом установите Python 3.11+, Node.js 20+ и Ollama.

#### Шаг 1. Python

Скачайте последнюю версию с официального сайта и убедитесь, что команда
`python3 --version` работает.

#### Шаг 2. Node.js

Node.js нужен для frontend (Vite dev-сервера). После установки проверьте
`node --version`.

#### Шаг 3. Ollama

Ollama предоставляет локальную модель эмбеддингов. Запустите сервис и
загрузите модель командой:

```bash
ollama pull nomic-embed-text
```

Убедитесь, что модель отвечает: откройте страницу «Настройки» и нажмите
«Проверить подключение».

## Индексация документов

### Создание коллекции

1. Перейдите на страницу «Документы» и загрузите файлы.
2. Откройте страницу «Индексация».
3. Выберите документы и стратегии разбиения.
4. Нажмите «Запустить индексацию».

### Параметры Fixed-size

- Размер чанка: количество символов в чанке.
- Overlap: перекрытие соседних чанков, сохраняющее контекст на границах.

Правило валидации: overlap всегда меньше размера чанка.

### Параметры Structural

- Максимальный размер: разделы больше этого значения делятся рекурсивно.
- Минимальный размер: меньшие разделы объединяются с соседними.

Структурный chunking учитывает заголовки Markdown, функции и классы кода,
страницы PDF. Если структуры нет — используется fallback по абзацам.

## Поиск

На странице «Поиск по индексу» выберите коллекцию и стратегию, введите запрос
и получите Top-K самых похожих чанков с метаданными и оценками сходства.

## Сравнение стратегий

Страница «Сравнение стратегий» строит метрики и графики по обеим стратегиям
на реальных данных коллекций: распределение размеров, время индексации,
число чанков по документам.

## Устранение неполадок

### Ollama недоступен

Проверьте, что сервис запущен (`ollama serve`) и адрес указан в настройках.

### Модель не установлена

Выполните `ollama pull nomic-embed-text`.

### Индекс несовместим с моделью

Сменив модель эмбеддингов, перестройте индекс: режим «Перестроить» на странице
«Индексация».
""",
}


def load_demo_documents() -> UploadResponse:
    """Загрузить демонстрационный корпус в приложение."""
    from ..repositories import documents_repo
    from ..schemas.documents import UploadErrorItem

    existing = {d["storage_name"] for d in documents_repo.list_documents()}
    response = UploadResponse()
    for name, content in DEMO_FILES.items():
        try:
            doc = loader.add_bytes(name, content.encode("utf-8"), existing_names=existing)
            existing.add(doc.storage_name)
            response.documents.append(loader.to_out(doc))
            response.uploaded += 1
        except Exception as e:  # noqa: BLE001
            response.errors.append(UploadErrorItem(filename=name, message=str(e)))
            response.failed += 1
    return response