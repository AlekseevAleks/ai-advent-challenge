#!/usr/bin/env python3
"""Start the local AI Chat application.

Usage:
    python run.py                 # start and open the browser
    python run.py --no-browser    # start without opening the browser
    python run.py --port 9000     # use a custom port
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local AI Chat")
    parser.add_argument("--host", default=None, help="Bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (default 8005)")
    parser.add_argument(
        "--no-browser", action="store_true", help="Do not open the browser"
    )
    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload (development)"
    )
    parser.add_argument("--log-level", default=None, help="Log level (default INFO)")
    return parser.parse_args()


def open_browser_later(url: str, delay: float = 1.2) -> None:
    def _open() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:  # pragma: no cover - depends on the environment
            pass

    threading.Thread(target=_open, daemon=True).start()


def main() -> int:
    args = parse_args()

    try:
        import uvicorn
    except ImportError:
        print(
            "Не найдены зависимости. Установите их командой:\n"
            "    pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    from backend.config import get_config

    config = get_config()
    host = args.host or config.host
    port = args.port or config.port
    log_level = (args.log_level or config.log_level).lower()

    config.ensure_data_dir()

    url = f"http://{host}:{port}"
    print("AI Chat started")
    print(f"Open {url}")
    print(f"Data directory: {config.data_dir}")
    print("Press Ctrl+C to stop.\n")

    if not args.no_browser and config.open_browser:
        open_browser_later(url)

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level=log_level,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())