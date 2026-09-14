"""CSS-стили интерфейса: сайдбар агентов, чат, диалоги."""

# Высота рабочей области: 100vh минус отступы контейнера Gradio (16+16)
# и футер с его отступом (21+16), иначе страница выходит за экран.
BASE_CSS = """
.app-row { height: calc(100vh - 69px); min-height: 0; }
#sidebar {
    height: 100%;
    overflow: hidden;
    flex-wrap: nowrap !important;
    border-right: 1px solid var(--border-color-primary);
    padding-right: 8px;
}
#new-agent-button { flex: 0 0 auto; }
.agents-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
    flex: 1 1 0;
    min-height: 0;
    overflow-y: auto;
}
.agent-row { padding: 0; gap: 4px; flex-wrap: nowrap !important; }
.agent-row > div { min-width: 0; }
.agent-name-button {
    flex: 1;
    justify-content: flex-start;
    text-align: left;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-weight: 600;
}
.agent-name-button.active {
    background: var(--color-accent-soft);
    border: 1px solid var(--color-accent);
    color: var(--color-accent) !important;
    box-shadow: 0 0 0 1px var(--color-accent) inset;
}
.agent-delete-button {
    flex-shrink: 0;
    max-width: 42px;
    min-width: 42px;
    width: 42px;
    opacity: 0.75;
}
.agent-delete-button:hover { opacity: 1; color: #ef4444; }
#chat-pane { height: 100%; min-height: 0; }
#chat-column { height: 100%; min-height: 0; }
#chat-column > div { min-height: 0; }
#chatbot { flex: 1; min-height: 0; }
.message-row { flex-wrap: nowrap; }
.empty-list { opacity: 0.6; }
#summary-pane {
    height: 100%;
    overflow: hidden;
    flex-wrap: nowrap !important;
    border-left: 1px solid var(--border-color-primary);
    padding: 8px 12px;
}
.params-box,
.summary-box {
    border: 1px solid var(--border-color-primary);
    border-radius: 8px;
    padding: 10px 12px;
    min-height: 0;
    overflow-x: hidden;
}
.params-box {
    flex: 0 0 auto;
    margin-top: 8px;
}
.summary-box {
    flex: 1 1 0;
    overflow-y: auto;
}
#summary-pane .prose {
    opacity: 0.9;
    max-width: 100%;
    overflow-wrap: anywhere;
    word-break: break-word;
}

"""

DIALOG_CSS = """
.dialog-overlay {
    position: fixed !important;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    z-index: 1000;
}
.dialog-panel {
    position: fixed !important;
    inset: 0;
    margin: auto;
    width: fit-content;
    height: fit-content;
    max-width: min(92vw, 520px);
    max-height: 90vh;
    overflow-y: auto;
    background: var(--background-fill-primary);
    border: 1px solid var(--border-color-primary);
    border-radius: 12px;
    padding: 20px 24px;
    min-width: 360px;
    z-index: 1001;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
}
.dialog-panel h3 { margin: 0 0 12px; }
"""
