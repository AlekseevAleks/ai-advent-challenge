"""Settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_settings
from backend.models.settings import (
    ConnectionTestResult,
    SettingsPublic,
    SettingsUpdate,
)
from backend.services.ai_client import AIClient
from backend.services.settings_service import SettingsService
from backend.utils.errors import AppError
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsPublic)
async def read_settings(
    settings: SettingsService = Depends(get_settings),
) -> SettingsPublic:
    """Return the current settings with the API key masked."""
    return settings.to_public()


@router.put("", response_model=SettingsPublic)
async def update_settings(
    payload: SettingsUpdate,
    settings: SettingsService = Depends(get_settings),
) -> SettingsPublic:
    """Persist settings locally. The API key is never echoed back."""
    return settings.update(payload)


@router.post("/test", response_model=ConnectionTestResult)
async def test_settings(
    settings: SettingsService = Depends(get_settings),
) -> ConnectionTestResult:
    """Check that the configured API is reachable and returns models."""
    base_url = settings.get_api_base_url()
    api_key = settings.get_api_key()

    if not base_url:
        return ConnectionTestResult(
            ok=False,
            message="API Base URL не указан. Заполните поле и сохраните настройки.",
        )

    client = AIClient(base_url, api_key)
    try:
        result = await client.test_connection()
    except AppError as exc:
        logger.info("Проверка подключения не удалась: %s", exc.code)
        return ConnectionTestResult(ok=False, message=exc.message)
    except Exception as exc:  # noqa: BLE001 - never leak a traceback to the UI
        logger.exception("Неожиданная ошибка при проверке подключения")
        return ConnectionTestResult(
            ok=False,
            message="Не удалось подключиться к API. Проверьте настройки.",
        )

    return ConnectionTestResult(
        ok=True,
        message=f"Подключение успешно. Доступно моделей: {result['models_count']}.",
        models_count=result["models_count"],
        latency_ms=result["latency_ms"],
    )