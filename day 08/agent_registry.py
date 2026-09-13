"""Хранилище агентов: создание, поиск и удаление."""

from typing import Optional

from agent import Agent
from agent_store import AgentStore


class AgentRegistry:
    """Управляет жизненным циклом агентов приложения."""

    def __init__(self, store: AgentStore):
        self._store = store
        self._agents: dict[str, Agent] = {}
        self._restore_agents()

    def _restore_agents(self) -> None:
        """Восстанавливает агентов и их переписку из базы при старте."""
        for record in self._store.load_agents():
            agent = Agent(
                name=record["name"],
                model=record["model"],
                agent_id=record["id"],
                history=record["history"],
                store=self._store,
                context_limit=record.get("context_limit"),
            )
            self._agents[agent.id] = agent

    def create(
        self, name: str, model: str, context_limit: Optional[int] = None
    ) -> Agent:
        agent = Agent(
            name=name, model=model, store=self._store, context_limit=context_limit
        )
        self._agents[agent.id] = agent
        self._store.save_agent(agent.id, agent.name, agent.model, agent.context_limit)
        return agent

    def get(self, agent_id: Optional[str]) -> Optional[Agent]:
        if not agent_id:
            return None
        return self._agents.get(agent_id)

    def delete(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)
        self._store.delete_agent(agent_id)

    def snapshot(self) -> list[dict]:
        """Плоское представление агентов для отрисовки списка."""
        return [
            {
                "id": agent.id,
                "name": agent.name,
                "model": agent.model,
                "context_limit": agent.context_limit,
            }
            for agent in self._agents.values()
        ]
