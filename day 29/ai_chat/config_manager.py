"""Работа с локальным файлом конфигурации config.json.

Модуль отвечает за чтение, запись и маскирование настроек подключений
к OpenAI-совместимым API. Помимо legacy-полей (``api_url``, ``api_key``,
``default_model``) хранится список сохранённых подключений ``providers``
— каждое со своим названием, адресом, флагом авторизации, ключом
и моделью по умолчанию. Текущее (первое) подключение зеркалируется
в legacy-поля для обратной совместимости.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "api_url": "https://api.openai.com/v1",
    "api_key": "",
    "default_model": "gpt-4o-mini",
    "rag_url": "http://localhost:8000",
    "rag_collection": "",
    "rag_strategy": "",
    "providers": [],
}

_lock = threading.RLock()


def _ensure_file() -> None:
    """Создаёт config.json со значениями по умолчанию, если файла нет."""
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(DEFAULT_CONFIG, fh, ensure_ascii=False, indent=2)


def _read_config() -> Dict[str, Any]:
    """Читает конфиг с диска без захвата блокировки (для внутреннего использования)."""
    _ensure_file()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {**DEFAULT_CONFIG, **data}


def _normalize_providers(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Приводит список подключений к единому виду (с миграцией из legacy-полей).

    Если подключений ещё нет, но заданы legacy-поля ``api_url``/``api_key`` —
    создаётся первое подключение «Основное»; все недостающие поля записи
    заполняются значениями по умолчанию.
    """
    providers = data.get("providers")
    if not isinstance(providers, list) or not providers:
        providers = [
            {
                "id": str(uuid.uuid4()),
                "name": "Основное подключение",
                "api_url": str(data.get("api_url", "") or ""),
                "requires_auth": bool(data.get("api_key")),
                "api_key": str(data.get("api_key", "") or ""),
                "default_model": str(data.get("default_model", "") or ""),
            }
        ]
    result: List[Dict[str, Any]] = []
    for item in providers:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "id": str(item.get("id") or uuid.uuid4()),
                "name": str(item.get("name") or "Подключение"),
                "api_url": str(item.get("api_url", "") or ""),
                "requires_auth": bool(item.get("requires_auth", False)),
                "api_key": str(item.get("api_key", "") or ""),
                "default_model": str(item.get("default_model", "") or ""),
            }
        )
    return result


def _sync_legacy(data: Dict[str, Any], providers: List[Dict[str, Any]]) -> None:
    """Зеркалирует первое подключение в legacy-поля конфига."""
    first = providers[0] if providers else {}
    data["api_url"] = first.get("api_url", "")
    data["api_key"] = first.get("api_key", "")
    data["default_model"] = first.get("default_model", "")
    data["providers"] = providers


def _mask(api_key: str) -> str:
    """Маскирует ключ: первые 3 и последние 4 символа."""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "•" * len(api_key)
    return f"{api_key[:3]}...{api_key[-4:]}"


def _unmask(api_key: str, current: str) -> str:
    """Возвращает настоящий ключ: маска (…/•) не затирает сохранённый."""
    new_key = (api_key or "").strip()
    if not new_key or "..." in new_key or "•" in new_key:
        return current or ""
    return new_key


def _ensure_providers() -> None:
    """Мигрирует legacy-поля в первый провайдер и сохраняет его на диск.

    Вызывается перед операциями с подключениями: без этого каждый вызов
    ``_normalize_providers`` генерировал бы новый ``id`` для провайдера,
    который ещё не записан в ``config.json``.
    """
    data = _read_config()
    if isinstance(data.get("providers"), list) and data.get("providers"):
        return
    normalized = _normalize_providers(data)
    if not normalized:
        return
    _sync_legacy(data, normalized)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def list_providers() -> List[Dict[str, Any]]:
    """Возвращает список подключений для фронтенда (ключи — только маской)."""
    with _lock:
        _ensure_providers()
        data = _read_config()
        providers = _normalize_providers(data)
        return [
            {
                "id": provider["id"],
                "name": provider["name"],
                "api_url": provider["api_url"],
                "requires_auth": provider["requires_auth"],
                "api_key_masked": _mask(provider["api_key"]),
                "has_key": bool(provider["api_key"]),
                "default_model": provider["default_model"],
            }
            for provider in providers
        ]


def get_provider(provider_id: str) -> Optional[Dict[str, Any]]:
    """Возвращает подключение с настоящим ключом или ``None``."""
    with _lock:
        _ensure_providers()
        data = _read_config()
        for provider in _normalize_providers(data):
            if provider["id"] == provider_id:
                return provider
        return None


def first_provider() -> Optional[Dict[str, Any]]:
    """Возвращает первое подключение (с настоящим ключом) или ``None``."""
    with _lock:
        _ensure_providers()
        data = _read_config()
        providers = _normalize_providers(data)
        return providers[0] if providers else None


def provider_credentials(provider_id: Optional[str]) -> Dict[str, str]:
    """Возвращает (api_url, api_key, default_model) для указанного подключения.

    Если подключение не найдено — берётся первое, затем legacy-поля.
    Используется при создании чата и отправке сообщений.
    """
    with _lock:
        _ensure_providers()
        data = _read_config()
        providers = _normalize_providers(data)
        if provider_id:
            for provider in providers:
                if provider["id"] == provider_id:
                    return {
                        "api_url": provider["api_url"],
                        "api_key": provider["api_key"],
                        "default_model": provider["default_model"],
                    }
        if providers:
            return {
                "api_url": providers[0]["api_url"],
                "api_key": providers[0]["api_key"],
                "default_model": providers[0]["default_model"],
            }
        return {
            "api_url": data.get("api_url", ""),
            "api_key": data.get("api_key", ""),
            "default_model": data.get("default_model", ""),
        }


def save_provider(
    name: str,
    api_url: str,
    requires_auth: bool,
    api_key: str = "",
    default_model: str = "",
    provider_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Создаёт или обновляет подключение и синхронизирует legacy-поля.

    Возвращает сохранённое подключение (с настоящим ключом).
    """
    with _lock:
        _ensure_providers()
        data = _read_config()
        providers = _normalize_providers(data)
        if provider_id:
            provider = next((p for p in providers if p["id"] == provider_id), None)
            if provider is None:
                raise ValueError("Подключение не найдено.")
        else:
            provider = {
                "id": str(uuid.uuid4()),
                "name": "",
                "api_url": "",
                "requires_auth": False,
                "api_key": "",
                "default_model": "",
            }
            providers.append(provider)
        provider["name"] = (name or "Подключение").strip()
        provider["api_url"] = (api_url or "").strip().rstrip("/")
        provider["requires_auth"] = bool(requires_auth)
        provider["api_key"] = _unmask(api_key, provider.get("api_key", ""))
        provider["default_model"] = (default_model or "").strip()
        _sync_legacy(data, providers)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        return dict(provider)


def delete_provider(provider_id: str) -> bool:
    """Удаляет подключение. Возвращает ``True``, если оно было удалено.    """
    with _lock:
        _ensure_providers()
        data = _read_config()
        providers = _normalize_providers(data)
        before = len(providers)
        providers = [p for p in providers if p["id"] != provider_id]
        if len(providers) == before:
            return False
        _sync_legacy(data, providers)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        return True


def load_config() -> Dict[str, Any]:
    """Читает конфиг с диска, дополняя отсутствующие поля значениями по умолчанию."""
    with _lock:
        return _read_config()


def save_config(
    api_url: str,
    api_key: str,
    default_model: str,
    rag_url: str = "",
) -> Dict[str, Any]:
    """Сохраняет конфиг на диск.

    Пустой ``api_key`` не затирает уже сохранённый ключ — это позволяет
    фронтенду отправлять маскированное значение без потери секрета.
    RAG-настройки при сохранении основной формы не затрагиваются: пустой
    ``rag_url`` оставляет сохранённое значение без изменений.
    """
    with _lock:
        current = _read_config()
        new_key = api_key.strip() if api_key else ""
        # Маскированный ключ (например, "sk-...abcd" или "pza...u_W3")
        # не должен затирать настоящий: фронт отправляет маску при
        # сохранении настроек без изменения ключа.
        if not new_key or "..." in new_key or "•" in new_key:
            new_key = current.get("api_key", "")

        config = {
            "api_url": (api_url or DEFAULT_CONFIG["api_url"]).strip().rstrip("/"),
            "api_key": new_key,
            "default_model": (default_model or DEFAULT_CONFIG["default_model"]).strip(),
            "rag_url": (
                (rag_url or current.get("rag_url", DEFAULT_CONFIG["rag_url"])).strip().rstrip("/")
            ),
            "rag_collection": current.get("rag_collection", ""),
            "rag_strategy": current.get("rag_strategy", ""),
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(config, fh, ensure_ascii=False, indent=2)
        return config


def save_rag_config(rag_url: str, rag_collection: str = "", rag_strategy: str = "") -> Dict[str, Any]:
    """Обновляет только RAG-настройки, не трогая остальной конфиг.

    Используется кнопкой «Сохранить» в секции RAG: сохраняются адрес
    сервера, выбранная коллекция и стратегия chunking, остальные поля
    (API-ключ и т. п.) остаются без изменений. Значения переживают
    перезапуск агента.
    """
    with _lock:
        current = _read_config()
        current["rag_url"] = (rag_url or DEFAULT_CONFIG["rag_url"]).strip().rstrip("/")
        current["rag_collection"] = (rag_collection or "").strip()
        current["rag_strategy"] = (rag_strategy or "").strip()
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(current, fh, ensure_ascii=False, indent=2)
        return current


def mask_key(api_key: str) -> str:
    """Возвращает маскированный вид ключа, например ``sk-...abcd``."""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "•" * len(api_key)
    return f"{api_key[:3]}...{api_key[-4:]}"


def public_config() -> Dict[str, Any]:
    """Конфиг для отдачи на фронтенд: ключ только в маскированном виде."""
    config = load_config()
    providers = list_providers()
    return {
        "api_url": config.get("api_url", ""),
        "api_key_masked": _mask(config.get("api_key", "")),
        "has_key": bool(config.get("api_key")),
        "default_model": config.get("default_model", ""),
        "rag_url": config.get("rag_url", ""),
        "rag_collection": config.get("rag_collection", ""),
        "rag_strategy": config.get("rag_strategy", ""),
        "providers": providers,
    }