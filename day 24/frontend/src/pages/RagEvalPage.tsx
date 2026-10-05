/** Страница «RAG Evaluation» — автоматическая оценка grounded-ответов по 10 вопросам. */

import { useEffect, useState } from "react";
import {
  BookOpen,
  CheckCircle2,
  ChevronDown,
  Download,
  Gauge,
  Quote,
  Sparkles,
  XCircle,
  Loader2,
} from "lucide-react";
import { t } from "../app/i18n";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  EmptyState,
  Select,
  Spinner,
  ToggleSwitch,
} from "../components/ui";
import { useToast } from "../components/ui/toast";
import {
  ApiError,
  getSettings,
  getGroundedEvalRun,
  listCollections,
  listGroundedEvalRuns,
  runGroundedEval,
  seedGroundedEvalDataset,
} from "../services/api";
import type {
  AnswerConfigFields,
  Collection,
  EvalDataset,
  GroundedEvalMetrics,
  GroundedEvalQuestionResult,
  GroundedEvalRun,
} from "../types/api";

export function apiDetail(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Неизвестная ошибка";
}

export function RagEvalPage() {
  const toast = useToast();
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionId, setCollectionId] = useState("");
  const [strategy, setStrategy] = useState("structural");
  const [dataset, setDataset] = useState<EvalDataset | null>(null);
  const [running, setRunning] = useState(false);
  const [run, setRun] = useState<GroundedEvalRun | null>(null);
  const [runs, setRuns] = useState<GroundedEvalRun[]>([]);

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

  useEffect(() => {
    void listCollections()
      .then((c) => {
        setCollections(c);
        if (c.length) setCollectionId((cur) => cur || c[0].id);
      })
      .catch((e) => toast.error(t("eval.cols_err", "Не удалось загрузить коллекции"), apiDetail(e)));
    void listGroundedEvalRuns().then(setRuns).catch(() => undefined);
    void getSettings()
      .then((s) =>
        setCfg((c) => ({
          ...c,
          answer_relevance_threshold: s.backend.default_relevance_threshold,
          grounding_threshold: s.backend.default_grounding_threshold,
          min_supporting_chunks: s.backend.default_min_supporting_chunks,
          initial_top_k: s.backend.default_initial_top_k,
          final_top_k: s.backend.default_final_top_k,
        })),
      )
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function seed() {
    try {
      const ds = await seedGroundedEvalDataset();
      setDataset(ds);
      toast.success(t("eval.seeded", "Датасет из 10 вопросов загружен"));
    } catch (e) {
      toast.error(t("eval.seed_err", "Не удалось создать датасет"), apiDetail(e));
    }
  }

  async function runEval() {
    if (!collectionId) {
      toast.error(t("eval.req_collection", "Выберите коллекцию"), "");
      return;
    }
    let dsId = dataset?.id;
    if (!dsId) {
      try {
        dsId = (await seedGroundedEvalDataset()).id;
      } catch (e) {
        toast.error(t("eval.seed_err", "Не удалось создать датасет"), apiDetail(e));
        return;
      }
    }
    setRunning(true);
    setRun(null);
    try {
      const res = await runGroundedEval({
        dataset_id: dsId,
        collection_id: collectionId,
        strategy,
        base_config: cfg,
        name: "Grounded оценка",
      });
      setRun(res);
      const list = await listGroundedEvalRuns();
      setRuns(list);
    } catch (e) {
      toast.error(t("eval.run_err", "Не удалось выполнить оценку"), apiDetail(e));
    } finally {
      setRunning(false);
    }
  }

  async function openRun(runId: string) {
    try {
      setRun(await getGroundedEvalRun(runId));
    } catch (e) {
      toast.error(t("eval.load_err", "Не удалось загрузить запуск"), apiDetail(e));
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Gauge className="h-5 w-5" />
              {t("eval.title", "RAG Evaluation")}
            </CardTitle>
            <CardDescription>{t("eval.subtitle", "Оценка grounded-ответов на 10 вопросах")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Select
              label={t("eval.collection", "Коллекция")}
              value={collectionId}
              onChange={(e) => setCollectionId(e.target.value)}
            >
              <option value="">{t("eval.collection_ph", "Выберите коллекцию")}</option>
              {collections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </Select>
            <Select
              label={t("eval.strategy", "Стратегия")}
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
            >
              <option value="structural">Структурная</option>
              <option value="fixed_size">Фиксированный размер</option>
            </Select>

            <ToggleSwitch
              checked={cfg.query_rewrite}
              onChange={(v) => setCfg({ ...cfg, query_rewrite: v })}
              label={t("eval.rewrite", "Query rewrite")}
            />
            <ToggleSwitch
              checked={cfg.enable_filter}
              onChange={(v) => setCfg({ ...cfg, enable_filter: v })}
              label={t("eval.filter", "Similarity filter")}
            />
            <ToggleSwitch
              checked={cfg.enable_reranker}
              onChange={(v) => setCfg({ ...cfg, enable_reranker: v })}
              label={t("eval.reranker", "Рeranker")}
            />

            <Button onClick={() => void seed()} variant="secondary" disabled={!!dataset}>
              <BookOpen className="h-4 w-4" />
              {dataset
                ? `${t("eval.dataset_ready", "Датасет загружен")} (${dataset.items.length})`
                : t("eval.dataset", "Загрузить датасет 10 вопросов")}
            </Button>
            <Button onClick={() => void runEval()} loading={running}>
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {t("eval.run", "Запустить оценку")}
            </Button>
          </CardContent>
        </Card>

        <div className="space-y-4 lg:col-span-2">
          {running ? (
            <Card>
              <CardContent className="py-10">
                <Spinner label={t("eval.working", "Прогон 10 вопросов через полный pipeline…")} />
              </CardContent>
            </Card>
          ) : run ? (
            <EvalResults run={run} onOpen={openRun} />
          ) : (
            <EmptyState
              icon={<Gauge className="h-8 w-8" />}
              title={t("eval.empty_title", "Запустите оценку")}
              description={t("eval.empty_desc", "Система прогонит 10 вопросов и посчитает метрики по фактическим результатам.")}
            />
          )}

          {runs.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">{t("eval.history", "История оценок")}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                {runs.map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => void openRun(r.id)}
                    className="flex w-full items-center gap-2 rounded-md border border-border px-3 py-2 text-left text-xs transition-colors hover:bg-accent"
                  >
                    <Badge variant={r.status === "completed" ? "success" : "warning"}>{r.status}</Badge>
                    <span className="font-mono opacity-70">{r.id}</span>
                    <span className="ml-auto opacity-70">{r.created_at}</span>
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

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card>
      <CardContent className="pt-4 text-center">
        <p className="text-2xl font-semibold">{value}</p>
        <p className="text-xs text-muted-foreground">{label}</p>
        {sub ? <p className="font-mono text-[10px] text-muted-foreground">{sub}</p> : null}
      </CardContent>
    </Card>
  );
}

function EvalResults({ run, onOpen }: { run: GroundedEvalRun; onOpen: (id: string) => void }) {
  const m: GroundedEvalMetrics | null = run.metrics;
  const rows: GroundedEvalQuestionResult[] = run.per_question ?? [];
  const [openRows, setOpenRows] = useState<Set<number>>(new Set());
  const [runs, setRuns] = useState<GroundedEvalRun[]>([]);

  useEffect(() => {
    void listGroundedEvalRuns().then(setRuns).catch(() => undefined);
  }, [run.id]);

  if (!m) return <EmptyState icon={<Gauge className="h-8 w-8" />} title={t("eval.no_metrics", "Нет метрик")} />;

  const fmt = (v?: number | null) => (typeof v === "number" ? `${v.toFixed(1)}%` : "—");

  const toggle = (i: number) =>
    setOpenRows((s) => {
      const n = new Set(s);
      if (n.has(i)) n.delete(i);
      else n.add(i);
      return n;
    });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Badge variant={run.status === "completed" ? "success" : "warning"}>{run.status}</Badge>
        <span className="font-mono text-xs opacity-70">{run.id}</span>
        {runs.length > 0 ? (
          <select className="ml-auto rounded-md border border-border bg-transparent text-xs" onChange={(e) => e.target.value && onOpen(e.target.value)}>
            <option value="">{t("eval.hist_sel", "Открыть из истории…")}</option>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>{r.id}</option>
            ))}
          </select>
        ) : null}
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-5">
        <MetricCard label={t("eval.q", "Вопросы")} value={String(m.questions)} />
        <MetricCard label={t("eval.answers", "Ответы")} value={String(m.answers_generated)} sub={`insufficient: ${m.insufficient_context}`} />
        <MetricCard label={t("eval.src_cov", "Source Coverage")} value={fmt(m.source_coverage)} sub={m.source_coverage_ratio} />
        <MetricCard label={t("eval.cite_cov", "Citation Coverage")} value={fmt(m.citation_coverage)} sub={m.citation_coverage_ratio} />
        <MetricCard label={t("eval.ground_acc", "Grounding Accuracy")} value={fmt(m.grounding_accuracy)} sub={m.grounding_ratio} />
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <MetricCard label={t("eval.cite_val", "Citation Validity")} value={fmt(m.citation_validity)} />
        <MetricCard label={t("eval.abstain", "Abstention Accuracy")} value={m.abstention_accuracy !== null ? fmt(m.abstention_accuracy) : "—"} sub={m.abstention_ratio ?? undefined} />
        <MetricCard label={t("eval.total_cites", "Всего цитат")} value={String(m.total_citations)} />
        <MetricCard label={t("eval.sources", "Ответов с источниками")} value={m.source_coverage_ratio} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t("eval.table", "Результаты по вопросам")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          {rows.map((r, i) => {
            const open = openRows.has(i);
            const res = r.results;
            return (
              <div key={i} className="rounded-md border border-border">
                <button
                  type="button"
                  onClick={() => toggle(i)}
                  className="grid w-full grid-cols-[auto_1fr_auto_auto_auto_auto] items-center gap-2 px-3 py-2 text-left text-xs"
                >
                  <span className="font-mono text-muted-foreground">{i + 1}</span>
                  <span className="min-w-0 truncate">{r.question}</span>
                  <span className={res?.sources_present ? "text-success" : "text-muted-foreground"}>S</span>
                  <span className={res?.citations_present ? "text-success" : "text-muted-foreground"}>C</span>
                  <span className={res?.answer_grounded ? "text-success" : "text-muted-foreground"}>G</span>
                  <Badge variant={r.result === "PASS" ? "success" : r.result === "INSUFFICIENT_CONTEXT" ? "secondary" : "warning"}>
                    {r.result}
                  </Badge>
                </button>
                {open ? (
                  <div className="space-y-2 border-t border-border px-3 py-2 text-xs">
                    <p className="text-muted-foreground">{t("eval.answer", "Ответ")}: {r.answer_excerpt || "—"}</p>
                    {r.error ? <p className="text-warning">{t("eval.error", "Ошибка")}: {r.error}</p> : null}
                    <p className="flex flex-wrap gap-3 text-muted-foreground">
                      <span>{t("eval.src", "Ист")}: {res?.sources_present ? "✓" : "✗"}</span>
                      <span>{t("eval.cite", "Цит")}: {res?.citations_present ? "✓" : "✗"}</span>
                      <span>{t("eval.valid", "Валидн")}: {res?.citation_valid ? "✓" : "✗"}</span>
                      <span>{t("eval.ground", "Grounded")}: {res?.answer_grounded ? "✓" : "✗"}</span>
                      <span>{t("eval.unsup", "Без подтверждения")}: {res?.unsupported_claims ?? 0}</span>
                      {r.relevance_score != null ? <span>Relevance: {r.relevance_score.toFixed(2)}</span> : null}
                    </p>
                    {r.sources.length ? (
                      <p className="text-muted-foreground">
                        {t("eval.sources", "Источники")}: {r.sources.map((s) => s.source).join(", ")}
                      </p>
                    ) : null}
                    {r.citations.map((c, j) => (
                      <p key={j} className="italic text-muted-foreground">
                        <Quote className="mr-1 inline h-3 w-3" />
                         “{c.quote.slice(0, 120)}…”
                      </p>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}
