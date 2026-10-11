/** Страница «Grounded RAG: Ответы» — генерация ответа с источниками и цитатами. */

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Bot,
  CheckCircle2,
  Copy,
  Quote,
  RefreshCw,
  Search,
  Sparkles,
  Wand2,
  XCircle,
} from "lucide-react";
import { t } from "../app/i18n";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Dialog,
  EmptyState,
  Input,
  Select,
  Slider,
  Spinner,
  Textarea,
  ToggleSwitch,
} from "../components/ui";
import { useToast } from "../components/ui/toast";
import { clamp, formatMs } from "../lib/utils";
import { ApiError, getSettings, listAnswers, listCollections, ragAnswer } from "../services/api";
import type { AnswerConfigFields, Collection, RagAnswerResult } from "../types/api";

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

export function GroundedAnswerPage() {
  const toast = useToast();
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionId, setCollectionId] = useState("");
  const [strategy, setStrategy] = useState("structural");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RagAnswerResult | null>(null);
  const [history, setHistory] = useState<RagAnswerResult[]>([]);

  const [cfg, setCfg] = useState<AnswerConfigFields>({
    query_rewrite: false,
    initial_top_k: 20,
    final_top_k: 5,
    enable_filter: true,
    similarity_threshold: 0.65,
    enable_reranker: true,
    reranker: "heuristic",
    answer_relevance_threshold: 0.65,
    grounding_threshold: 0.7,
    min_supporting_chunks: 1,
  });

  function loadCollections() {
    void listCollections()
      .then((cols) => {
        setCollections(cols);
        if (cols.length) setCollectionId((cur) => cur || cols[0].id);
      })
      .catch((e) => toast.error(t("ans.cols_err", "Не удалось загрузить коллекции"), apiDetail(e)));
  }

  async function loadHistory() {
    try {
      setHistory(await listAnswers(30));
    } catch {
      /* история не критична */
    }
  }

  useEffect(() => {
    loadCollections();
    void loadHistory();
    void getSettings()
      .then((s) =>
        setCfg((c) => ({
          ...c,
          answer_relevance_threshold: s.backend.default_relevance_threshold,
          grounding_threshold: s.backend.default_grounding_threshold,
          min_supporting_chunks: s.backend.default_min_supporting_chunks,
          initial_top_k: s.backend.default_initial_top_k,
          final_top_k: s.backend.default_final_top_k,
          similarity_threshold: s.backend.default_similarity_threshold,
        })),
      )
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function run(q: string) {
    if (!collectionId) {
      toast.error(t("ans.req_collection", "Выберите коллекцию"), "");
      return;
    }
    if (!q.trim()) {
      toast.error(t("ans.req_query", "Введите запрос"), "");
      return;
    }
    setLoading(true);
    void ragAnswer(collectionId, strategy, q.trim(), cfg)
      .then((res) => {
        setResult(res);
        void loadHistory();
      })
      .catch((e) => toast.error(t("ans.fail", "Не удалось получить ответ"), apiDetail(e)))
      .finally(() => setLoading(false));
  }

  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(t("ans.copied", "Скопировано"));
    } catch {
      toast.error(t("ans.copy_err", "Не удалось скопировать"));
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bot className="h-5 w-5" />
              {t("ans.title", "Ответ с источниками")}
            </CardTitle>
            <CardDescription>{t("ans.subtitle", "Retrieval → relevance gate → LLM → grounding → цитаты")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Select
              label={t("ans.collection", "Коллекция")}
              value={collectionId}
              onChange={(e) => setCollectionId(e.target.value)}
            >
              <option value="">{t("ans.collection_ph", "Выберите коллекцию")}</option>
              {collections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </Select>
            <Select
              label={t("ans.strategy", "Стратегия")}
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
            >
              <option value="structural">Структурная</option>
              <option value="fixed_size">Фиксированный размер</option>
            </Select>

            <div className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">{t("ans.relevance_th", "Порог релевантности")}</span>
                <span className="font-mono">{cfg.answer_relevance_threshold.toFixed(2)}</span>
              </div>
              <Slider
                label={t("ans.relevance_lbl", "Порог релевантности")}
                min={0}
                max={1}
                step={0.01}
                value={cfg.answer_relevance_threshold}
                onChange={(v) => setCfg({ ...cfg, answer_relevance_threshold: v })}
              />
              <p className="text-[10px] text-muted-foreground">
                {t("ans.relevance_hint", "Ниже порога — «не знаю», LLM не вызывается")}
              </p>
            </div>

            <div className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">{t("ans.grounding_th", "Порог grounded-ности")}</span>
                <span className="font-mono">{cfg.grounding_threshold.toFixed(2)}</span>
              </div>
              <Slider
                label={t("ans.grounding_lbl", "Порог grounded-ности")}
                min={0}
                max={1}
                step={0.01}
                value={cfg.grounding_threshold}
                onChange={(v) => setCfg({ ...cfg, grounding_threshold: v })}
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <Input
                type="number"
                label={t("ans.initial_k", "Initial Top-K")}
                value={String(cfg.initial_top_k)}
                onChange={(e) => setCfg({ ...cfg, initial_top_k: Math.min(500, Math.max(1, Number(e.target.value) || 1)) })}
              />
              <Input
                type="number"
                label={t("ans.final_k", "Final Top-K")}
                value={String(cfg.final_top_k)}
                onChange={(e) => setCfg({ ...cfg, final_top_k: Math.min(100, Math.max(1, Number(e.target.value) || 1)) })}
              />
            </div>

            <ToggleSwitch checked={cfg.query_rewrite} onChange={(v) => setCfg({ ...cfg, query_rewrite: v })} label={t("ans.rewrite", "Query rewrite")} />
            <ToggleSwitch checked={cfg.enable_filter} onChange={(v) => setCfg({ ...cfg, enable_filter: v })} label={t("ans.filter", "Similarity filter")} />
            <ToggleSwitch checked={cfg.enable_reranker} onChange={(v) => setCfg({ ...cfg, enable_reranker: v })} label={t("ans.reranker", "Рeranker")} />
          </CardContent>
        </Card>

        <div className="space-y-4 lg:col-span-2">
          <Card>
            <CardContent className="space-y-3 pt-5">
              <Textarea
                label={t("ans.query", "Запрос")}
                rows={3}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("ans.query_ph", "Например: для чего используется FAISS?")}
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button onClick={() => run(query)} loading={loading}>
                  <Sparkles className="h-4 w-4" />
                  {t("ans.run", "Сформировать ответ")}
                </Button>
                <Button variant="secondary" onClick={() => run(query)} loading={loading}>
                  <RefreshCw className="h-4 w-4" />
                  {t("ans.rerun", "Заново")}
                </Button>
                <div className="ml-auto" />
              </div>
            </CardContent>
          </Card>

          {loading ? (
            <Card>
              <CardContent className="py-10">
                <Spinner label={t("ans.working", "Retrieval → gate → LLM → grounding…")} />
              </CardContent>
            </Card>
          ) : result ? (
            <AnswerResult result={result} onCopy={copyText} onClarify={(q) => { setQuery(q); if (q) run(q); }} />
          ) : (
            <EmptyState
              icon={<Bot className="h-8 w-8" />}
              title={t("ans.empty_title", "Сформируйте ответ")}
              description={t("ans.empty_desc", "Введите вопрос и нажмите «Сформировать ответ».")}
            />
          )}

          {history.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">{t("ans.history", "Последние ответы")}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                {history.map((h) => (
                  <button
                    key={h.id}
                    type="button"
                    onClick={() => setQuery(h.original_query)}
                    className="flex w-full items-center gap-2 rounded-md border border-border px-3 py-2 text-left text-xs transition-colors hover:bg-accent"
                  >
                    <Badge variant={h.status === "answered" ? "success" : "warning"}>{h.status}</Badge>
                    <span className="min-w-0 flex-1 truncate">{h.original_query}</span>
                  </button>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function AnswerResult({
  result,
  onCopy,
  onClarify,
}: {
  result: RagAnswerResult;
  onCopy: (t: string) => void;
  onClarify: (q: string) => void;
}) {
  const [clarifyOpen, setClarifyOpen] = useState(false);
  const [clarifyText, setClarifyText] = useState("");
  const refused = result.status === "insufficient_context" || result.status === "grounding_failed";
  const relevance = (result.retrieval?.relevance_score as number) ?? 0;
  const g = result.grounding;

  return (
    <Card className="space-y-4">
      <CardContent className="space-y-4 pt-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={result.status === "answered" ? "success" : "warning"}>
            {STATUS_LABEL[result.status] ?? result.status}
          </Badge>
          <Badge variant="outline">Relevance: {relevance.toFixed(2)}</Badge>
          {result.status === "answered" ? (
            <Badge variant="outline">Grounding: {Math.round(g.grounding_score * 100)}%</Badge>
          ) : null}
          <Badge variant="outline">{t("ans.sources_count", "Источники")}: {result.sources.length}</Badge>
          <Badge variant="outline">{t("ans.citations_count", "Цитаты")}: {result.citations.length}</Badge>
          <span className="ml-auto text-xs text-muted-foreground">total: {formatMs(result.latency?.total_ms ?? 0)}</span>
        </div>

        {refused ? (
          <Alert variant="warning" className="border-warning/40 bg-warning/10">
            <AlertTriangle className="h-5 w-5 text-warning" />
            <div className="space-y-2">
              <p className="font-medium">{t("ans.refused_title", "Недостаточно информации")}</p>
              <p className="text-sm">{result.answer}</p>
              <p className="text-xs text-muted-foreground">
                {t("ans.refused_hint", "Это валидный результат RAG: модель не придумывает ответ без подтверждающих источников.")}
              </p>
              <Button variant="secondary" size="sm" onClick={() => setClarifyOpen(true)}>
                <Wand2 className="h-4 w-4" />
                {t("ans.clarify", "Уточнить вопрос")}
              </Button>
            </div>
          </Alert>
        ) : (
          <>
            <div>
              <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <Bot className="h-3.5 w-3.5" />
                {t("ans.answer_block", "Ответ")}
              </p>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{result.answer}</p>
            </div>

            <div>
              <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <BookOpen className="h-3.5 w-3.5" />
                {t("ans.sources_block", "Источники")}
              </p>
              <div className="space-y-1">
                {result.sources.map((s, i) => (
                  <div key={s.chunk_id} className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-xs">
                    <span className="font-mono text-muted-foreground">[{i + 1}]</span>
                    <span className="font-medium">{s.source}</span>
                    {s.section ? <span className="text-muted-foreground">· {s.section}</span> : null}
                    <Badge variant="outline" className="font-mono">{s.chunk_id}</Badge>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <Quote className="h-3.5 w-3.5" />
                {t("ans.citations_block", "Цитаты")}
              </p>
              <div className="space-y-2">
                {result.citations.map((c, i) => (
                  <div key={c.chunk_id} className="rounded-md border border-border p-3">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="font-mono">[{i + 1}]</span>
                      <span className="font-medium text-foreground">{c.source}</span>
                      {c.section ? <span>· {c.section}</span> : null}
                      <Badge variant="outline" className="font-mono">{c.chunk_id}</Badge>
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-xs italic">“{c.quote}”</p>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <p className="mb-2 text-xs font-medium text-muted-foreground">
                {t("ans.claims_block", "Утверждения (claims)")} — {g.claims_supported}/{g.claims_total}
              </p>
              <div className="space-y-1.5">
                {result.claims.map((c, i) => (
                  <div key={i} className="flex items-start gap-2 rounded-md border border-border px-3 py-2 text-xs">
                    {c.grounded ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                    ) : (
                      <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p>{c.text}</p>
                      <p className="font-mono text-[10px] text-muted-foreground">
                        {c.chunk_ids.join(", ")}
                        {c.grounded ? ` · grounding ${c.grounding_score.toFixed(2)}` : " · без подтверждения"}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {result.sources.length > 0 ? (
              <div className="rounded-lg border border-border p-3">
                <p className="mb-2 text-xs font-medium">{t("ans.context", "Итоговый контекст")}</p>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() =>
                    onCopy(
                      result.sources.map((s, i) => `[${i + 1}] source: ${s.source}\nsection: ${s.section ?? "—"}`).join("\n\n"),
                    )
                  }
                >
                  <Copy className="h-3.5 w-3.5" />
                  {t("ans.copy_context", "Копировать источники")}
                </Button>
              </div>
            ) : null}
          </>
        )}
      </CardContent>

      <Dialog open={clarifyOpen} onClose={() => setClarifyOpen(false)} title={t("ans.clarify_title", "Уточните вопрос")}>
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            {t("ans.clarify_desc", "Укажите, что именно вы хотите узнать — новый запрос пройдёт полный pipeline.")}
          </p>
          <Input
            value={clarifyText}
            onChange={(e) => setClarifyText(e.target.value)}
            placeholder={t("ans.clarify_ph", "Например: расскажите подробнее про эмбеддинги")}
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setClarifyOpen(false)}>
              {t("ans.cancel", "Отмена")}
            </Button>
            <Button
              onClick={() => {
                setClarifyOpen(false);
                onClarify(clarifyText.trim());
              }}
            >
              <Search className="h-4 w-4" />
              {t("ans.clarify_go", "Спросить")}
            </Button>
          </div>
        </div>
      </Dialog>
    </Card>
  );
}
