"""Тесты backend для RAG Document Indexing Lab.

Обычные тесты работают БЕЗ запущенного Ollama: клиент эмбеддингов подменяется
на FakedEmbeddingsClient из tests/fake_embeddings.py. Фейковые эмбеддинги
существуют исключительно в тестах и явно отделены от рабочего режима.

Запуск:  cd backend && .venv/bin/pytest

Тест с реальным Ollama: pytest -m real_ollama (см. README).
"""