/** Страница «Чат» — история + Task Memory поверх существующего RAG pipeline. */

import { useEffect, useRef, useState } from "react";
import {
  Bot,
  Brain,
  CheckCircle2,
  MessageSquarePlus,
  Quote,
  Send,
  Sparkles,
  User,
  XCircle,
} from "lucide-react";
import { t } from "../app/i18n";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  Input,
  Select,
  Spinner,
  Textarea,
} from "../components/ui";
import { useToast } from "../components/ui/toast";
import {
  ApiError,
  chatConversations,
  chatGet,
  chatNew,
  chatSend,
  listCollections,
} from "../services/api";
import type { ChatConversation, ChatMessage, ChatResponse, ChatTaskState, Collection } from "../types/api";

export function apiDetail(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Неизвестная ошибка";
}

const STATUS_LABEL: Record<string, string> = {
  answered: "Ответ сформирован",
  insufficient_context: "Недостаточно контекста",
  grounding_failed: "Ответ не подтверждён",
};

interface LocalMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status?: string;
  sources?: ChatResponse["sources"];
  citations?: ChatResponse["citations"];
  grounding?: ChatResponse["grounding"];
  search_query?: string;
}

export function ChatPage() {
  const toast = useToast();
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionId, setCollectionId] = useState("");
  const [strategy, setStrategy] = useState("structural");
  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [taskState, setTaskState] = useState<ChatTaskState | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [conversations, setConversations] = useState<{ id: string; updated_at: string }[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void listCollections()
      .then((c) => {
        setCollections(c);
        if (c.length) setCollectionId((cur) => cur || c[0].id);
      })
      .catch((e) => toast.error(t("chat.cols_err", "Не удалось загрузить коллекции"), apiDetail(e)));
    void refreshConversations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function refreshConversations() {
    try {
      setConversations(await chatConversations());
    } catch {
      /* не критично */
    }
  }

  async function newChat() {
    try {
      const { conversation_id } = await chatNew();
      setConvId(conversation_id);
      setMessages([]);
      setTaskState(null);
      await refreshConversations();
    } catch (e) {
      toast.error(t("chat.new_err", "Не удалось создать беседу"), apiDetail(e));
    }
  }

  async function openConversation(id: string) {
    try {
      const c: ChatConversation = await chatGet(id);
      setConvId(c.conversation_id);
      setMessages(c.messages.map((m) => ({
        id: m.id, role: m.role, content: m.content, status: m.status,
        sources: m.sources, citations: m.citations, search_query: m.search_query ?? undefined,
      })));
      setTaskState(c.task_state);
    } catch (e) {
      toast.error(t("chat.load_err", "Не удалось загрузить беседу"), apiDetail(e));
    }
  }

  async function send(text?: string) {
    const message = (text ?? input).trim();
    if (!message || busy) return;
    setBusy(true);
    setInput("");
    setMessages((m) => [...m, { id: `local-${Date.now()}`, role: "user", content: message }]);
    try {
      const res: ChatResponse = await chatSend(message, convId, collectionId || undefined, strategy);
      setConvId(res.conversation_id);
      setMessages((m) => [
        ...m,
        {
          id: res.message_id ?? `msg-${Date.now()}`,
          role: "assistant",
          content: res.answer,
          status: res.status,
          sources: res.sources,
          citations: res.citations,
          grounding: res.grounding,
          search_query: res.search_query,
        },
      ]);
      setTaskState(res.task_state);
      await refreshConversations();
    } catch (e) {
      setMessages((m) => [...m, {
        id: `err-${Date.now()}`, role: "assistant", content: `⚠ ${apiDetail(e)}`, status: "error",
      }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {/* списки бесед */}
      <Card className="lg:col-span-1">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <MessageSquarePlus className="h-4 w-4" />
            {t("chat.conversations", "Беседы")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button variant="secondary" className="w-full" onClick={() => void newChat()}>
            <MessageSquarePlus className="h-4 w-4" />
            {t("chat.new", "+ New Chat")}
          </Button>
          <Select
            label={t("chat.collection", "Коллекция")}
            value={collectionId}
            onChange={(e) => setCollectionId(e.target.value)}
          >
            <option value="">—</option>
            {collections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
          <Select label={t("chat.strategy", "Стратегия")} value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            <option value="structural">Структурная</option>
            <option value="fixed_size">Фиксированный размер</option>
          </Select>
          <div className="space-y-1">
            {conversations.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => void openConversation(c.id)}
                className={[
                  "w-full truncate rounded-md border border-border px-3 py-1.5 text-left font-mono text-[11px] transition-colors hover:bg-accent",
                  convId === c.id ? "bg-accent" : "",
                ].join(" ")}
              >
                {c.id}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* чат */}
      <Card className="lg:col-span-2">
        <CardContent className="flex h-[70vh] flex-col space-y-3 pt-4">
          {messages.length === 0 && !busy ? (
            <EmptyState
              icon={<Bot className="h-8 w-8" />}
              title={t("chat.empty_title", "Начните диалог")}
              description={t("chat.empty_desc", "Каждый вопрос пройдёт через RAG pipeline: история → Task Memory → retrieval → reranker → relevance gate → LLM → grounding.")}
              action={<Button onClick={() => void newChat()}>{t("chat.start", "Новая беседа")}</Button>}
            />
          ) : (
            <div className="flex-1 space-y-3 overflow-y-auto pr-1">
              {messages.map((m) => (
                <Bubble key={m.id} m={m} />
              ))}
              {busy ? <Spinner label={t("chat.working", "RAG pipeline…")} /> : null}
              <div ref={bottomRef} />
            </div>
          )}

          <div className="flex gap-2">
            <Textarea
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={t("chat.input_ph", "Например: а какой лучше?")}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }}
            />
            <Button onClick={() => void send()} disabled={busy} className="h-auto">
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Task Memory */}
      <Card className="lg:col-span-1 lg:row-start-1 lg:col-start-3">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Brain className="h-4 w-4" />
            {t("chat.task_memory", "Task Memory")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-xs">
          {taskState ? (
            <>
              <div>
                <p className="text-[10px] uppercase text-muted-foreground">{t("chat.goal", "Goal")}</p>
                <p>{taskState.goal || "—"}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase text-muted-foreground">{t("chat.focus", "Current focus")}</p>
                <p>{taskState.current_focus || "—"}</p>
              </div>
              {taskState.constraints.length > 0 ? (
                <div>
                  <p className="text-[10px] uppercase text-muted-foreground">{t("chat.constraints", "Constraints")}</p>
                  <ul className="list-inside list-disc space-y-0.5">
                    {taskState.constraints.map((c) => <li key={c}>{c}</li>)}
                  </ul>
                </div>
              ) : null}
              {taskState.decisions.length > 0 ? (
                <div>
                  <p className="text-[10px] uppercase text-muted-foreground">{t("chat.decisions", "Decisions")}</p>
                  <ul className="space-y-0.5">
                    {taskState.decisions.map((d, i) => (
                      <li key={i} className={d.status === "active" ? "" : "line-through opacity-50"}>
                        {d.key}: {d.value}{d.status === "active" ? "" : " (superseded)"}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <p className="text-[10px] text-muted-foreground">{t("chat.version", "version")}: {taskState.version}</p>
            </>
          ) : (
            <p className="text-muted-foreground">{t("chat.task_empty", "Выберите или создайте беседу.")}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Bubble({ m }: { m: LocalMessage }) {
  const isUser = m.role === "user";
  const refused = m.status === "insufficient_context" || m.status === "grounding_failed";
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div className={[
        "max-w-[85%] rounded-lg border border-border p-3",
        isUser ? "bg-primary/10" : "bg-secondary DEFAULT/20",
      ].join(" ")}>
        <div className="mb-1 flex items-center gap-1.5 text-[10px] text-muted-foreground">
          {isUser ? <User className="h-3 w-3" /> : <Bot className="h-3 w-3" />}
          {isUser ? "Вы" : "Ассистент"}
          {!isUser && m.status ? <Badge variant={m.status === "answered" ? "success" : "warning"}>{STATUS_LABEL[m.status] ?? m.status}</Badge> : null}
        </div>
        <p className="whitespace-pre-wrap text-sm">{m.content}</p>

        {!isUser && m.search_query && m.search_query !== "" && (
          <p className="mt-1 text-[10px] text-muted-foreground">
            <Sparkles className="mr-1 inline h-3 w-3" />search: {m.search_query}
          </p>
        )}

        {!isUser && !refused && m.status !== "error" && m.citations && m.citations.length > 0 && (
          <div className="mt-2 space-y-1">
            {m.citations.map((c, i) => (
              <p key={i} className="rounded bg-muted px-2 py-1 text-[11px] italic text-muted-foreground">
                <Quote className="mr-1 inline h-3 w-3" />“{c.quote.slice(0, 140)}…” <span className="not-italic">[{c.source} · {c.chunk_id}]</span>
              </p>
            ))}
          </div>
        )}

        {!isUser && m.status === "answered" && m.grounding && (
          <p className="mt-1 text-[10px] text-muted-foreground">
            Grounding: {Math.round(m.grounding.grounding_score * 100)}% · claims {m.grounding.claims_supported}/{m.grounding.claims_total}
          </p>
        )}
      </div>
    </div>
  );
}
