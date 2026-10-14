#!/usr/bin/env python3
"""Запуск Uvicorn с HOST/PORT из локального .env."""

import argparse
import sys
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level="critical" if settings.log_level == "SILENT" else settings.log_level.lower(),
        access_log=True,
    )


if __name__ == "__main__":
    main()
