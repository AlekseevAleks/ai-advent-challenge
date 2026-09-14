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
                recent_messages_limit=record.get("recent_messages_limit"),
                strategy=record.get("strategy"),
            )
            agent.restore_summary(
                record.get("summary"),
                record.get("summary_upto", 0),
                record.get("summary_tokens", 0),
            )
            agent.restore_facts(
                record.get("facts"),
                record.get("facts_tokens", 0),
            )
            agent.restore_branches(
                self._store.load_branches(record["id"]),
                record.get("active_branch_id"),
                record.get("branch_messages"),
            )
            self._agents[agent.id] = agent

    def create(
        self,
        name: str,
        model: str,
        context_limit: Optional[int] = None,
        recent_messages_limit: Optional[int] = None,
        strategy: Optional[str] = None,
    ) -> Agent:
        agent = Agent(
            name=name,
            model=model,
            store=self._store,
            context_limit=context_limit,
            recent_messages_limit=recent_messages_limit,
            strategy=strategy,
        )
        self._agents[agent.id] = agent
        self._store.save_agent(
            agent.id,
            agent.name,
            agent.model,
            agent.context_limit,
            agent.recent_messages_limit,
            agent.strategy,
        )
        return agent

    def branches(self, agent_id: Optional[str]) -> list[dict]:
        """Ветки агента для отрисовки в панели."""
        agent = self.get(agent_id)
        return agent.branches() if agent else []

    def create_branch(self, agent_id: Optional[str], upto: Optional[int]) -> dict:
        """Создаёт ветку от точки upto в истории агента."""
        agent = self.get(agent_id)
        if agent is None:
            return {}
        return agent.create_branch(upto=upto)

    def switch_branch(self, agent_id: Optional[str], branch_id: Optional[str]) -> None:
        """Переключает активную ветку агента."""
        agent = self.get(agent_id)
        if agent is not None:
            agent.switch_branch(branch_id)

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
                "recent_messages_limit": agent.recent_messages_limit,
                "strategy": agent.strategy,
            }
            for agent in self._agents.values()
        ]
