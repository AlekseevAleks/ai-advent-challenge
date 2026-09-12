"""Клиент LLM через OpenAI-совместимый API (endpoint /chat/completions)."""

from typing import Optional

from openai import OpenAI

from config import LlmConfig

SYSTEM_PROMPT = "Ты полезный ассистент. Отвечай кратко и используй Markdown."
FALLBACK_ANSWER = "Модель вернула пустой ответ."


class LlmClient:
    def __init__(self, config: LlmConfig):
        self._client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout_seconds,
        )
        self._model = config.model

    def list_models(self) -> list[str]:
        """Возвращает модели, доступные по тому же api-адресу."""
        models = self._client.models.list()
        model_ids = sorted(model.id for model in models.data if model.id)
        return model_ids or [self._model]

    def pick_model(self, available_models: list[str]) -> str:
        """Выбирает модель по умолчанию: точное совпадение с конфигом или по суффиксу."""
        if self._model in available_models:
            return self._model
        suffix_matches = [m for m in available_models if m.endswith(self._model)]
        return suffix_matches[0] if suffix_matches else available_models[0]

    def send(self, model: str, history: list[dict]) -> str:
        """Отправляет переписку и возвращает ответ модели.

        История передаётся в формате messages: [{"role", "content"}, ...].
        """
        if not history:
            raise ValueError("История сообщений пуста.")

        model_id = model or self._model
        response = self._client.chat.completions.create(
            model=model_id,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
        )
        return response.choices[0].message.content or FALLBACK_ANSWER
