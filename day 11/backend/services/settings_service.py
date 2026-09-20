"""Local settings storage (``data/config.json``).

The API key is stored on disk only and is never returned to the frontend in
clear text. The file is written atomically with ``0600`` permissions.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from backend.config import get_config
from backend.models.settings import SettingsPublic, SettingsUpdate
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_SETTINGS: Dict[str, Any] = {
    "api_base_url": "",
    "api_key": "",
}


def mask_api_key(api_key: str) -> str:
    """Return a masked representation of an API key."""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}{'*' * 8}{api_key[-4:]}"


class SettingsService:
    """Reads and writes user settings from a local JSON file."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else get_config().config_file
        self._cache: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ read
    def load(self, *, use_cache: bool = True) -> Dict[str, Any]:
        if use_cache and self._cache is not None:
            return dict(self._cache)

        data: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
                if isinstance(raw, dict):
                    data.update({k: v for k, v in raw.items() if v is not None})
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Не удалось прочитать %s: %s", self.path, exc)
        self._cache = data
        return dict(data)

    def get_api_base_url(self) -> str:
        return str(self.load().get("api_base_url") or "").strip()

    def get_api_key(self) -> str:
        return str(self.load().get("api_key") or "").strip()

    def is_configured(self) -> bool:
        return bool(self.get_api_base_url() and self.get_api_key())

    def to_public(self) -> SettingsPublic:
        data = self.load()
        api_key = str(data.get("api_key") or "")
        base_url = str(data.get("api_base_url") or "")
        return SettingsPublic(
            api_base_url=base_url,
            api_key_masked=mask_api_key(api_key),
            has_api_key=bool(api_key),
            is_configured=bool(base_url and api_key),
        )

    # ----------------------------------------------------------------- write
    def update(self, payload: SettingsUpdate) -> SettingsPublic:
        data = self.load()
        if payload.api_base_url is not None:
            data["api_base_url"] = payload.api_base_url
        # An empty string clears the key; ``None`` keeps the stored value.
        if payload.api_key is not None:
            data["api_key"] = payload.api_key
        self._write(data)
        return self.to_public()

    def save(self, api_base_url: str, api_key: str) -> SettingsPublic:
        return self.update(
            SettingsUpdate(api_base_url=api_base_url, api_key=api_key)
        )

    def _write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".config-", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=4)
                handle.write("\n")
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
        self._cache = dict(data)
        logger.info("Настройки сохранены в %s", self.path)

    def invalidate_cache(self) -> None:
        self._cache = None


_settings_service: Optional[SettingsService] = None


def get_settings_service() -> SettingsService:
    global _settings_service
    if _settings_service is None:
        _settings_service = SettingsService()
    return _settings_service


def set_settings_service(service: Optional[SettingsService]) -> None:
    global _settings_service
    _settings_service = service