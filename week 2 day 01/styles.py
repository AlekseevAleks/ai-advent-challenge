"""CSS-стили интерфейса: сайдбар агентов, чат, диалоги."""

BASE_CSS = """
.app-row { height: calc(100vh - 40px); }
#sidebar {
    height: 100%;
    overflow-y: auto;
    border-right: 1px solid var(--border-color-primary);
    padding-right: 8px;
}
.agents-list { display: flex; flex-direction: column; gap: 4px; }
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
#chat-pane { height: 100%; }
#chat-column { height: 100%; }
#chatbot { flex: 1; }
.message-row { flex-wrap: nowrap; }
.empty-list { opacity: 0.6; }
#agent-params-pane {
    height: 100%;
    border-left: 1px solid var(--border-color-primary);
    padding-left: 12px;
}
#agent-params-pane .prose { opacity: 0.9; }
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
