"""Model listing endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_settings
from backend.models.message import ModelList
from backend.services.ai_client import AIClient
from backend.services.settings_service import SettingsService
from backend.utils.errors import SettingsNotConfiguredError

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=ModelList)
async def list_models(
    settings: SettingsService = Depends(get_settings),
) -> ModelList:
    """Fetch the model list from the configured OpenAI-compatible API."""
    base_url = settings.get_api_base_url()
    if not base_url:
        raise SettingsNotConfiguredError()

    client = AIClient(base_url, settings.get_api_key())
    models = await client.list_models()
    return ModelList(models=models)