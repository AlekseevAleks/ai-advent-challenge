"""Хранилище агентов: создание, поиск и удаление."""

from typing import Optional

from agent import Agent


class AgentRegistry:
    """Управляет жизненным циклом агентов приложения."""

    def __init__(self):
        self._agents: dict[str, Agent] = {}

    def create(self, name: str, model: str) -> Agent:
        agent = Agent(name=name, model=model)
        self._agents[agent.id] = agent
        return agent

    def get(self, agent_id: Optional[str]) -> Optional[Agent]:
        if not agent_id:
            return None
        return self._agents.get(agent_id)

    def delete(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)

    def snapshot(self) -> list[dict]:
        """Плоское представление агентов для отрисовки списка."""
        return [
            {"id": agent.id, "name": agent.name, "model": agent.model}
            for agent in self._agents.values()
        ]
