"""Пользовательский интерфейс: сайдбар агентов слева, чат справа, диалоги."""

from typing import Generator, Optional, Tuple

import gradio as gr

from agent import Agent
from agent_registry import AgentRegistry
from llm_client import LlmClient
from styles import BASE_CSS, DIALOG_CSS

TITLE = "Чат с LLM"
NEW_AGENT_BUTTON_LABEL = "＋ Новый"
SEND_BUTTON_LABEL = "Отправить"
MESSAGE_PLACEHOLDER = "Введите сообщение…"
DELETE_BUTTON_TITLE = "🗑"
DELETE_DIALOG_TITLE = "### Удаление агента"
DELETE_DIALOG_TEXT = "Вы точно хотите удалить агента?"
NEW_AGENT_DIALOG_TITLE = "### Создание нового агента"
CONFIRM_BUTTON_LABEL = "Да"
CANCEL_BUTTON_LABEL = "Нет"
CREATE_BUTTON_LABEL = "Создать"
AGENT_NAME_LABEL = "Имя агента"
AGENT_MODEL_LABEL = "Модель LLM"
AGENT_CONTEXT_LIMIT_LABEL = "Лимит контекста"
AGENT_RECENT_MESSAGES_LABEL = "Количество последних сообщений"
RECENT_MESSAGES_UNLIMITED = 0
RECENT_MESSAGES_UNLIMITED_HINT = "0 — без ограничения"
PARAMS_SUMMARY_TITLE = "### Сводка старых сообщений"
PARAMS_SUMMARY_UNSET = "Сводки пока нет: агент отправляет всю переписку."
PARAMS_RECENT_MESSAGES_LABEL = "**Количество последних сообщений:** {limit}"
PARAMS_RECENT_MESSAGES_UNSET = "**Количество последних сообщений:** без ограничения"
AGENT_NAME_WARNING = "Введите имя агента."
EMPTY_AGENTS_HTML = "<p class='empty-list'>Агентов пока нет. Создайте первого!</p>"
NO_AGENT_SELECTED_TEXT = (
    "Выберите агента слева или создайте нового, нажав кнопку «Новый»."
)
AGENT_PARAMS_TITLE = "### Параметры агента"
NO_AGENT_PARAMS_TEXT = "Агент не выбран."
PARAMS_MODEL_LABEL = "**Модель LLM:** {model}"
PARAMS_CONTEXT_LIMIT_LABEL = "**Лимит контекста:** {limit} токенов"
PARAMS_CONTEXT_LIMIT_UNSET = "**Лимит контекста:** без ограничения"
PARAMS_TOTAL_TOKENS_LABEL = "**Потрачено за весь диалог:** {total} токенов"


class ChatUi:
    """Собирает интерфейс и связывает его с реестром агентов и LLM-клиентом."""

    def __init__(self, registry: AgentRegistry, llm_client: LlmClient):
        self._registry = registry
        self._llm_client = llm_client
        self._models = llm_client.list_models()

    def build(self) -> gr.Blocks:
        with gr.Blocks(title=TITLE, css=self._css()) as demo:
            agents_state = gr.State(self._registry.snapshot())
            selected_agent_id = gr.State(None)
            pending_delete_id = gr.State(None)

            self._build_dialogs()
            self._wire_model_dropdown()

            with gr.Row(elem_classes=["app-row"]):
                with gr.Column(scale=1, min_width=270, elem_id="sidebar"):
                    self._build_sidebar(
                        agents_state, selected_agent_id, pending_delete_id
                    )
                    self._build_agent_params()
                with gr.Column(scale=3, elem_id="chat-pane"):
                    self._build_chat_area()
                with gr.Column(scale=1, min_width=230, elem_id="summary-pane"):
                    self._build_summary_box()

            self._wire_selection_side_effects(selected_agent_id)
            self._wire_chat_events(selected_agent_id)
            self._wire_dialog_actions(
                agents_state, selected_agent_id, pending_delete_id
            )

        return demo

    def _css(self) -> str:
        return BASE_CSS + DIALOG_CSS

    def _build_dialogs(self) -> None:
        self._new_agent_dialog = gr.Column(
            visible=False, elem_classes=["dialog-overlay"]
        )
        with self._new_agent_dialog:
            with gr.Column(elem_classes=["dialog-panel"]):
                gr.Markdown(NEW_AGENT_DIALOG_TITLE)
                self._agent_name_input = gr.Textbox(label=AGENT_NAME_LABEL)
                self._agent_model_dropdown = gr.Dropdown(
                    label=AGENT_MODEL_LABEL,
                    choices=self._models,
                    value=self._llm_client.pick_model(self._models),
                    filterable=True,
                )
                self._agent_context_limit_input = gr.Number(
                    label=AGENT_CONTEXT_LIMIT_LABEL,
                    value=self._llm_client.model_context_limit(
                        self._llm_client.pick_model(self._models)
                    ),
                    precision=0,
                    minimum=1,
                )
                self._agent_recent_messages_input = gr.Number(
                    label=AGENT_RECENT_MESSAGES_LABEL,
                    value=RECENT_MESSAGES_UNLIMITED,
                    precision=0,
                    minimum=0,
                    info=RECENT_MESSAGES_UNLIMITED_HINT,
                )
                with gr.Row():
                    self._create_agent_button = gr.Button(
                        CREATE_BUTTON_LABEL, variant="primary"
                    )
                    self._cancel_create_button = gr.Button(CANCEL_BUTTON_LABEL)

        self._delete_dialog = gr.Column(
            visible=False, elem_classes=["dialog-overlay"]
        )
        with self._delete_dialog:
            with gr.Column(elem_classes=["dialog-panel"]):
                gr.Markdown(DELETE_DIALOG_TITLE)
                gr.Markdown(DELETE_DIALOG_TEXT)
                with gr.Row():
                    self._confirm_delete_button = gr.Button(
                        CONFIRM_BUTTON_LABEL, variant="stop"
                    )
                    self._cancel_delete_button = gr.Button(CANCEL_BUTTON_LABEL)

    def _build_sidebar(
        self,
        agents_state: gr.State,
        selected_agent_id: gr.State,
        pending_delete_id: gr.State,
    ) -> None:
        new_agent_button = gr.Button(
            NEW_AGENT_BUTTON_LABEL, variant="primary", elem_id="new-agent-button"
        )
        new_agent_button.click(
            fn=lambda: gr.update(visible=True),
            inputs=None,
            outputs=self._new_agent_dialog,
        )

        @gr.render(inputs=[agents_state, selected_agent_id])
        def render_agents(agents: list[dict], active_id: Optional[str]) -> None:
            with gr.Column(elem_classes=["agents-list"]):
                if not agents:
                    gr.HTML(EMPTY_AGENTS_HTML)
                for agent in agents:
                    self._build_agent_row(agent, active_id, selected_agent_id, pending_delete_id)

    def _build_agent_row(
        self,
        agent: dict,
        active_id: Optional[str],
        selected_agent_id: gr.State,
        pending_delete_id: gr.State,
    ) -> None:
        is_active = agent["id"] == active_id
        with gr.Row(equal_height=True, elem_classes=["agent-row"]):
            name_button = gr.Button(
                agent["name"],
                elem_classes=["agent-name-button", "active" if is_active else "inactive"],
            )
            delete_button = gr.Button(
                DELETE_BUTTON_TITLE,
                elem_classes=["agent-delete-button"],
                size="sm",
            )

        name_button.click(
            fn=lambda agent_id=agent["id"]: agent_id,
            inputs=None,
            outputs=selected_agent_id,
        )
        delete_button.click(
            fn=lambda agent_id=agent["id"]: (agent_id, gr.update(visible=True)),
            inputs=None,
            outputs=[pending_delete_id, self._delete_dialog],
        )

    def _build_agent_params(self) -> None:
        """Блок параметров внизу сайдбара: высота по содержимому, без прокрутки."""
        with gr.Column(elem_classes=["params-box"]):
            gr.Markdown(AGENT_PARAMS_TITLE)
            self._agent_params = gr.Markdown(NO_AGENT_PARAMS_TEXT)

    def _build_summary_box(self) -> None:
        """Правая панель: сводка старых сообщений на всю высоту экрана."""
        with gr.Column(elem_classes=["summary-box"]):
            gr.Markdown(PARAMS_SUMMARY_TITLE)
            self._agent_summary = gr.Markdown(PARAMS_SUMMARY_UNSET)

    def _wire_model_dropdown(self) -> None:
        """При смене модели подставляет её лимит контекста."""

        def fill_context_limit(model_id: Optional[str]) -> Optional[int]:
            return self._llm_client.model_context_limit(model_id)

        self._agent_model_dropdown.change(
            fn=fill_context_limit,
            inputs=self._agent_model_dropdown,
            outputs=self._agent_context_limit_input,
        )

    def _build_chat_area(self) -> None:
        self._empty_chat_placeholder = gr.Markdown(
            NO_AGENT_SELECTED_TEXT, elem_id="empty-chat"
        )
        self._chat_column = gr.Column(visible=False, elem_id="chat-column")

        with self._chat_column:
            self._chatbot = gr.Chatbot(
                type="messages",
                show_label=False,
                render_markdown=True,
                elem_id="chatbot",
            )
            with gr.Row(equal_height=True, elem_classes=["message-row"]):
                self._message_input = gr.Textbox(
                    placeholder=MESSAGE_PLACEHOLDER,
                    show_label=False,
                    container=False,
                    scale=10,
                )
                self._send_button = gr.Button(
                    SEND_BUTTON_LABEL, variant="primary", scale=1
                )

    def _format_params(self, agent: Agent) -> str:
        """Правая панель: модель, лимиты и расход токенов за диалог."""
        lines = [PARAMS_MODEL_LABEL.format(model=agent.model)]
        if agent.context_limit:
            readable_limit = f"{agent.context_limit:,}".replace(",", " ")
            lines.append(PARAMS_CONTEXT_LIMIT_LABEL.format(limit=readable_limit))
        else:
            lines.append(PARAMS_CONTEXT_LIMIT_UNSET)
        if agent.recent_messages_limit:
            lines.append(
                PARAMS_RECENT_MESSAGES_LABEL.format(limit=agent.recent_messages_limit)
            )
        else:
            lines.append(PARAMS_RECENT_MESSAGES_UNSET)
        lines.append(PARAMS_TOTAL_TOKENS_LABEL.format(total=agent.total_tokens()))
        return "\n\n".join(lines)

    def _format_summary(self, agent: Agent) -> str:
        """Сводка старых сообщений или текст-заглушка."""
        summary = agent.summary_text()
        return summary if summary else PARAMS_SUMMARY_UNSET

    def _wire_selection_side_effects(self, selected_agent_id: gr.State) -> None:
        """При смене выбранного агента показывает его чат или заглушку."""

        def show_agent_chat(agent_id: Optional[str]) -> Tuple:
            agent = self._registry.get(agent_id)
            if agent is None:
                return (
                    [],
                    gr.update(visible=False),
                    gr.update(visible=True),
                    NO_AGENT_PARAMS_TEXT,
                    PARAMS_SUMMARY_UNSET,
                )
            return (
                agent.chat_messages,
                gr.update(visible=True),
                gr.update(visible=False),
                self._format_params(agent),
                self._format_summary(agent),
            )

        selected_agent_id.change(
            fn=show_agent_chat,
            inputs=selected_agent_id,
            outputs=[
                self._chatbot,
                self._chat_column,
                self._empty_chat_placeholder,
                self._agent_params,
                self._agent_summary,
            ],
        )

    def _wire_chat_events(self, selected_agent_id: gr.State) -> None:
        def send_message(
            text: str, agent_id: Optional[str]
        ) -> Generator[Tuple[list[dict], str, str, str], None, None]:
            agent = self._registry.get(agent_id)
            if agent is None:
                raise gr.Error("Сначала выберите агента.")
            clean_text = text.strip()
            if not clean_text:
                yield (
                    agent.chat_messages,
                    "",
                    self._format_params(agent),
                    self._format_summary(agent),
                )
                return

            agent.add_user_message(clean_text)
            yield (
                agent.chat_messages,
                "",
                self._format_params(agent),
                self._format_summary(agent),
            )
            agent.reply(self._llm_client)
            yield (
                agent.chat_messages,
                "",
                self._format_params(agent),
                self._format_summary(agent),
            )

        self._send_button.click(
            fn=send_message,
            inputs=[self._message_input, selected_agent_id],
            outputs=[
                self._chatbot,
                self._message_input,
                self._agent_params,
                self._agent_summary,
            ],
        )
        self._message_input.submit(
            fn=send_message,
            inputs=[self._message_input, selected_agent_id],
            outputs=[
                self._chatbot,
                self._message_input,
                self._agent_params,
                self._agent_summary,
            ],
        )

    def _wire_dialog_actions(
        self,
        agents_state: gr.State,
        selected_agent_id: gr.State,
        pending_delete_id: gr.State,
    ) -> None:
        self._wire_new_agent_dialog(agents_state, selected_agent_id)
        self._wire_delete_dialog(agents_state, selected_agent_id, pending_delete_id)

    def _wire_new_agent_dialog(
        self, agents_state: gr.State, selected_agent_id: gr.State
    ) -> None:
        def create_agent(
            name: str,
            model: str,
            context_limit: Optional[int],
            recent_messages_limit: Optional[int],
            current_selected: Optional[str],
        ) -> Tuple:
            clean_name = name.strip()
            if not clean_name:
                gr.Warning(AGENT_NAME_WARNING)
                return (
                    gr.update(visible=True),
                    self._registry.snapshot(),
                    current_selected,
                    name,
                    recent_messages_limit,
                )

            agent = self._registry.create(
                name=clean_name,
                model=model,
                context_limit=int(context_limit) if context_limit else None,
                recent_messages_limit=(
                    int(recent_messages_limit) if recent_messages_limit else None
                ),
            )
            return (
                gr.update(visible=False),
                self._registry.snapshot(),
                agent.id,
                "",
                RECENT_MESSAGES_UNLIMITED,
            )

        self._create_agent_button.click(
            fn=create_agent,
            inputs=[
                self._agent_name_input,
                self._agent_model_dropdown,
                self._agent_context_limit_input,
                self._agent_recent_messages_input,
                selected_agent_id,
            ],
            outputs=[
                self._new_agent_dialog,
                agents_state,
                selected_agent_id,
                self._agent_name_input,
                self._agent_recent_messages_input,
            ],
        )
        self._cancel_create_button.click(
            fn=lambda: gr.update(visible=False),
            inputs=None,
            outputs=self._new_agent_dialog,
        )

    def _wire_delete_dialog(
        self,
        agents_state: gr.State,
        selected_agent_id: gr.State,
        pending_delete_id: gr.State,
    ) -> None:
        def confirm_delete(
            agent_id_to_delete: Optional[str], current_selected: Optional[str]
        ) -> Tuple:
            if agent_id_to_delete:
                self._registry.delete(agent_id_to_delete)
            new_selected = (
                current_selected if current_selected != agent_id_to_delete else None
            )
            return (
                self._registry.snapshot(),
                new_selected,
                gr.update(visible=False),
                None,
            )

        self._confirm_delete_button.click(
            fn=confirm_delete,
            inputs=[pending_delete_id, selected_agent_id],
            outputs=[
                agents_state,
                selected_agent_id,
                self._delete_dialog,
                pending_delete_id,
            ],
        )
        self._cancel_delete_button.click(
            fn=lambda: gr.update(visible=False),
            inputs=None,
            outputs=self._delete_dialog,
        )
