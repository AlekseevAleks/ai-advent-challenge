"""Точка входа: собирает конфиг, реестр агентов, клиент и интерфейс, запускает сервер."""

from agent_registry import AgentRegistry
from agent_store import AgentStore
from config import load_config
from llm_client import LlmClient
from ui import ChatUi


def main() -> None:
    config = load_config()
    llm_client = LlmClient(config)
    store = AgentStore()
    registry = AgentRegistry(store)
    demo = ChatUi(registry, llm_client).build()
    demo.launch(inbrowser=True)


if __name__ == "__main__":
    main()
