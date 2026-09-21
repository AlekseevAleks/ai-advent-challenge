"""Shared pytest fixtures.

Each test gets an isolated data directory (SQLite file + config.json) and a
fake OpenAI-compatible API so no real network calls are made.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest
from fastapi.testclient import TestClient

from backend.config import AppConfig, reset_config_cache
from backend.database.database import Database, set_database
from backend.services.settings_service import SettingsService, set_settings_service


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "data"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@pytest.fixture()
def app_config(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AppConfig:
    monkeypatch.setenv("AICHAT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("AICHAT_OPEN_BROWSER", "false")
    reset_config_cache()
    config = AppConfig()
    config.ensure_data_dir()
    yield config
    reset_config_cache()


@pytest.fixture()
def database(app_config: AppConfig) -> Iterator[Database]:
    db = Database(app_config.database_file)
    set_database(db)
    yield db
    set_database(None)


@pytest.fixture()
def settings_service(app_config: AppConfig) -> Iterator[SettingsService]:
    service = SettingsService(app_config.config_file)
    set_settings_service(service)
    yield service
    set_settings_service(None)


@pytest.fixture()
def client(
    app_config: AppConfig, database: Database, settings_service: SettingsService
) -> Iterator[TestClient]:
    from backend.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------------------------- fake API
class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: Any = None,
        text: str = "",
        headers: Dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text or (json.dumps(json_data) if json_data is not None else "")
        self.headers = headers or {"content-type": "application/json"}

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeStreamResponse:
    """Minimal async context manager mimicking ``httpx`` streaming."""

    def __init__(
        self,
        status_code: int,
        lines: List[str],
        content_type: str,
        body: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self._lines = lines
        self.headers = {"content-type": content_type}
        self._body = body
        self.text = body.decode("utf-8", errors="replace")

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    async def aread(self) -> bytes:
        return self._body

    def json(self) -> Any:
        return json.loads(self._body.decode("utf-8"))

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def __aenter__(self) -> "FakeStreamResponse":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None


class FakeAsyncClient:
    """Stand-in for ``httpx.AsyncClient`` used by the AI client tests."""

    #: Every instance created during a test is registered here.
    instances: List["FakeAsyncClient"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.requests: List[Dict[str, Any]] = []
        FakeAsyncClient.instances.append(self)

    @classmethod
    def last_requests(cls) -> List[Dict[str, Any]]:
        """Requests recorded by the most recently created client."""
        return cls.instances[-1].requests if cls.instances else []

    @classmethod
    def all_requests(cls) -> List[Dict[str, Any]]:
        """Every request recorded during the test, in chronological order.

        The AI client opens a new ``httpx.AsyncClient`` per call, so a single
        exchange (chat completion + memory extraction) spans two instances.
        """
        collected: List[Dict[str, Any]] = []
        for instance in cls.instances:
            collected.extend(instance.requests)
        return collected

    #: System prompts that belong to background analysis, not to the chat.
    ANALYSIS_MARKERS = (
        "Memory Extractor",
        "Task State Extractor",
        "Invariant Conflict Detector",
    )

    @classmethod
    def chat_requests(cls) -> List[Dict[str, Any]]:
        """Only the chat completions, excluding background analysis calls."""
        return [
            request
            for request in cls.all_requests()
            if request["url"].endswith("/chat/completions")
            and not any(
                marker
                in (request.get("json") or {}).get("messages", [{}])[0].get(
                    "content", ""
                )
                for marker in cls.ANALYSIS_MARKERS
            )
        ]

    @classmethod
    def wait_for_analysis(cls, expected: int = 2, timeout: float = 3.0) -> None:
        """Block until at least ``expected`` analysis calls have been recorded.

        One exchange triggers two background calls: memory extraction and task
        step extraction. Both run asynchronously, so tests must give them a
        moment to reach the (fake) API before asserting on the result.
        """
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(cls.analysis_requests()) >= expected:
                return
            time.sleep(0.02)

    @classmethod
    def analysis_requests(cls) -> List[Dict[str, Any]]:
        """Only the background analysis calls (memory + task step)."""
        return [
            request
            for request in cls.all_requests()
            if request["url"].endswith("/chat/completions")
            and any(
                marker
                in (request.get("json") or {}).get("messages", [{}])[0].get(
                    "content", ""
                )
                for marker in cls.ANALYSIS_MARKERS
            )
        ]

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def get(self, url: str, headers=None, **kwargs) -> FakeResponse:
        self.requests.append({"method": "GET", "url": url, "headers": headers})
        return self._route("GET", url)

    async def post(self, url: str, headers=None, json=None, **kwargs) -> FakeResponse:
        self.requests.append(
            {"method": "POST", "url": url, "headers": headers, "json": json}
        )
        return self._route("POST", url, json)

    def stream(self, method: str, url: str, headers=None, json=None, **kwargs):
        self.requests.append(
            {"method": method, "url": url, "headers": headers, "json": json}
        )
        return self._route_stream(url, json)

    # Overridden by subclasses / monkeypatched instances.
    def _route(self, method: str, url: str, payload: Any = None) -> FakeResponse:
        raise NotImplementedError

    def _route_stream(self, url: str, payload: Any = None) -> FakeStreamResponse:
        raise NotImplementedError


@pytest.fixture()
def fake_api(monkeypatch: pytest.MonkeyPatch):
    """Patch ``httpx.AsyncClient`` with a configurable fake."""

    class ConfigurableFakeClient(FakeAsyncClient):
        models_response: FakeResponse = FakeResponse(
            200,
            {
                "object": "list",
                "data": [
                    {"id": "gpt-4o-mini", "object": "model"},
                    {"id": "gpt-4o", "object": "model"},
                ],
            },
        )
        completion_response: FakeResponse = FakeResponse(
            200,
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "Привет!"}}
                ]
            },
        )
        stream_lines: List[str] = [
            'data: {"choices":[{"delta":{"content":"При"}}]}',
            'data: {"choices":[{"delta":{"content":"вет"}}]}',
            "data: [DONE]",
        ]
        stream_status: int = 200
        stream_content_type: str = "text/event-stream"
        stream_body: bytes = b""

        #: When True, the extraction prompt is answered with a canned JSON
        #: payload; when False it returns unusable text so the rule-based
        #: fallback is exercised instead.
        extraction_returns_json: bool = True

        @staticmethod
        def _fake_extraction(user_text: str) -> str:
            """A tiny stand-in for a real model's memory classification."""
            import json as _json
            import re as _re

            working = None
            long_term = []

            task = _re.search(r"(?:разрабатываем|задача|делаем)\s+(.+)", user_text, _re.I)
            if task:
                working = {"task": task.group(1).strip().rstrip("."), "stack": []}

            step = _re.search(
                r"(?:давай\s+(?:теперь\s+)?сделаем|теперь\s+сделаем)\s+(.+)",
                user_text,
                _re.I,
            )
            if step:
                working = working or {}
                working["current_step"] = step.group(1).strip().rstrip(".")

            if _re.search(r"предпочитаю[^.]*python", user_text, _re.I):
                long_term.append(
                    {
                        "category": "preference",
                        "key": "preferred_language",
                        "value": "Python",
                        "confidence": 0.9,
                    }
                )
            if _re.search(r"предпочитаю[^.]*fastapi", user_text, _re.I):
                long_term.append(
                    {
                        "category": "preference",
                        "key": "preferred_framework",
                        "value": "FastAPI",
                        "confidence": 0.9,
                    }
                )
            if _re.search(r"отвечай\s+кратко", user_text, _re.I):
                long_term.append(
                    {
                        "category": "preference",
                        "key": "response_style",
                        "value": "concise",
                        "confidence": 0.9,
                    }
                )

            return _json.dumps(
                {
                    "short_term": True,
                    "working_memory": working,
                    "long_term_memory": long_term,
                    "summary": "fake extraction",
                },
                ensure_ascii=False,
            )

        #: Answer returned for the invariant conflict-detection prompt.
        #: Defaults to "no conflict"; tests override it to simulate a conflict.
        conflict_response: FakeResponse = FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                '{"has_conflict": false, "conflicts": [],'
                                ' "alternative": "", "explicit_change": false,'
                                ' "change_targets": []}'
                            ),
                        }
                    }
                ]
            },
        )

        #: Answer returned for the task state-extraction prompt. The stage is
        #: part of the same payload as the step.
        step_response: FakeResponse = FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                '{"stage": "execution",'
                                ' "current_step": "implement authentication",'
                                ' "expected_action": "create login endpoint",'
                                ' "confidence": 0.9}'
                            ),
                        }
                    }
                ]
            },
        )

        def _route(self, method: str, url: str, payload: Any = None) -> FakeResponse:
            if url.endswith("/models"):
                return self.models_response
            if url.endswith("/chat/completions"):
                # The memory extractor and the task step extractor use their own
                # system prompts; answer them separately so chat tests are not
                # affected by the background analysis calls.
                messages = (payload or {}).get("messages") or []
                system_text = " ".join(
                    m.get("content", "")
                    for m in messages
                    if isinstance(m, dict) and m.get("role") == "system"
                )
                if "Invariant Conflict Detector" in system_text:
                    return self.conflict_response
                if "Task State Extractor" in system_text:
                    return self.step_response
                if "Memory Extractor" in system_text:
                    if not self.extraction_returns_json:
                        return FakeResponse(
                            200,
                            {
                                "choices": [
                                    {
                                        "message": {
                                            "role": "assistant",
                                            "content": "не могу ответить",
                                        }
                                    }
                                ]
                            },
                        )
                    user_text = next(
                        (
                            m.get("content", "")
                            for m in reversed(messages)
                            if isinstance(m, dict) and m.get("role") == "user"
                        ),
                        "",
                    )
                    return FakeResponse(
                        200,
                        {
                            "choices": [
                                {
                                    "message": {
                                        "role": "assistant",
                                        "content": self._fake_extraction(user_text),
                                    }
                                }
                            ]
                        },
                    )
                return self.completion_response
            return FakeResponse(404, {"error": {"message": "not found"}})

        def _route_stream(self, url: str, payload: Any = None) -> FakeStreamResponse:
            return FakeStreamResponse(
                self.stream_status,
                self.stream_lines,
                self.stream_content_type,
                self.stream_body,
            )

    FakeAsyncClient.instances = []
    monkeypatch.setattr(
        "backend.services.ai_client.httpx.AsyncClient", ConfigurableFakeClient
    )
    return ConfigurableFakeClient