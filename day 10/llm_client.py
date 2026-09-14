"""Клиент LLM через OpenAI-совместимый API (endpoint /chat/completions)."""

from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

from config import LlmConfig

SYSTEM_PROMPT = "Ты полезный ассистент. Отвечай кратко и используй Markdown."
SUMMARY_SYSTEM_PROMPT = """Ты — суммаризатор диалога. Твоя задача — обновить накопительное резюме, добавив в него информацию из нового сообщения.

Сохраняй ОБЯЗАТЕЛЬНО:
- имена, роли, названия сущностей;
- числа, даты, бюджеты, ограничения, единицы измерения;
- предпочтения, аллергии, запреты, договорённости;
- открытые вопросы и незавершённые задачи.

Убирай:
- приветствия, вежливые формулы, шум;
- дублирующуюся информацию (не повторяй то, что уже есть).

Если новое сообщение ОТМЕНЯЕТ или ИСПРАВЛЯЕТ старый факт — замени старый факт новым, не храни оба.

Формат вывода: маркированный список фактов, каждый пункт — одно предложение. Никаких вступлений, никаких пояснений. Только список."""
FACTS_SYSTEM_PROMPT = """Ты — экстрактор фактов диалога. Твоя задача — обновить память диалога в формате ключ-значение, добавив информацию из нового сообщения.

Категории фактов: цель, ограничения, предпочтения, решения, договорённости, контекст.

Сохраняй ОБЯЗАТЕЛЬНО:
- имена, роли, названия сущностей;
- числа, даты, бюджеты, ограничения, единицы измерения;
- предпочтения, аллергии, запреты, договорённости;
- открытые вопросы и незавершённые задачи.

Убирай:
- приветствия, вежливые формулы, шум;
- дублирующуюся информацию (не повторяй то, что уже есть).

Если новое сообщение ОТМЕНЯЕТ или ИСПРАВЛЯЕТ старый факт — замени старый факт новым, не храни оба.

Формат вывода: только JSON-объект вида {"ключ": "значение", ...}. Никаких пояснений, никакого текста до или после JSON."""
FALLBACK_ANSWER = "Модель вернула пустой ответ."


@dataclass(frozen=True)
class LlmReply:
    """Ответ модели и расход токенов за этот запрос."""

    answer: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class LlmClient:
    def __init__(self, config: LlmConfig):
        self._client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout_seconds,
        )
        self._model = config.model
        self._model_records: Optional[list[dict]] = None

    def list_models(self) -> list[str]:
        """Возвращает модели, доступные по тому же api-адресу."""
        model_ids = sorted(record["id"] for record in self._load_model_records())
        return model_ids or [self._model]

    def model_context_limit(self, model_id: str) -> Optional[int]:
        """Лимит контекста модели из данных провайдера, если он известен."""
        record = self._find_model_record(model_id)
        return record["context_length"] if record else None

    def model_max_completion_tokens(self, model_id: str) -> Optional[int]:
        """Максимум токенов ответа для модели из данных провайдера."""
        record = self._find_model_record(model_id)
        return record["max_completion_tokens"] if record else None

    def pick_model(self, available_models: list[str]) -> str:
        """Выбирает модель по умолчанию: точное совпадение с конфигом или по суффиксу."""
        if self._model in available_models:
            return self._model
        suffix_matches = [m for m in available_models if m.endswith(self._model)]
        return suffix_matches[0] if suffix_matches else available_models[0]

    def send(
        self,
        model: str,
        history: list[dict],
        system_prompt: str = SYSTEM_PROMPT,
    ) -> LlmReply:
        """Отправляет переписку и возвращает ответ модели с расходом токенов.

        История передаётся в формате messages: [{"role", "content"}, ...].
        """
        if not history:
            raise ValueError("История сообщений пуста.")

        model_id = model or self._model
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages += [
            {"role": message["role"], "content": message["content"]}
            for message in history
        ]
        request_params: dict = {
            "model": model_id,
            "messages": messages,
        }
        response = self._client.chat.completions.create(**request_params)
        return self._to_reply(response)

    def _load_model_records(self) -> list[dict]:
        """Загружает описание моделей один раз и кеширует его."""
        if self._model_records is None:
            models = self._client.models.list()
            self._model_records = [
                {
                    "id": model.id,
                    "context_length": ((model.model_extra or {}).get("top_provider") or {}).get(
                        "context_length"
                    ),
                    "max_completion_tokens": ((model.model_extra or {}).get("top_provider") or {}).get(
                        "max_completion_tokens"
                    ),
                }
                for model in models.data
                if model.id
            ]
        return self._model_records

    def _find_model_record(self, model_id: str) -> Optional[dict]:
        """Ищет описание модели: точное совпадение, затем по суффиксу."""
        target = model_id or self._model
        records = self._load_model_records()
        exact = next((r for r in records if r["id"] == target), None)
        by_suffix = next(
            (r for r in records if r["id"].endswith(target)), None
        )
        return exact or by_suffix

    def _to_reply(self, response) -> LlmReply:
        usage = response.usage
        return LlmReply(
            answer=response.choices[0].message.content or FALLBACK_ANSWER,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
        )
