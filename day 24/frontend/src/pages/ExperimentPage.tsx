/** Страница «Эксперимент»: сравнение режимов RAG-пайплайна по evaluation-датасету. */

import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, ReactNode } from "react";
import {
  BarChart3,
  CheckCircle2,
  Clock,
  Copy,
  Database,
  Download,
  Eye,
  FileJson,
  GitCompareArrows,
  History,
  Info,
  Layers,
  ListChecks,
  PenLine,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  SlidersHorizontal,
  Trash2,
  Upload,
  Wand2,
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
  Tabs,
  Textarea,
  ToggleSwitch,
} from "../components/ui";
import { ColumnChart, TimingLineChart } from "../components/charts/Charts";
import { useToast } from "../components/ui/toast";
import { formatDate, formatMs } from "../lib/utils";
import {
  ApiError,
  compareExperiments,
  createEvalDataset,
  deleteEvalDataset,
  deleteExperiment,
  getEvalDataset,
  getEvalRun,
  getExperiment,
  getSettings,
  listCollections,
  listEvalDatasets,
  listEvalRuns,
  listExperiments,
  ragRerankersStatus,
  ragSearch,
  runEvaluation,
  saveExperiment,
  seedDemoEvalDataset,
} from "../services/api";
import type {
  AppSettings,
  ChunkFinalStatus,
  Collection,
  EvalDataset,
  EvalItem,
  EvalRun,
  EvalRunRequest,
  ExperimentItem,
  ModeRunResult,
  RerankerKind,
  RerankersStatusResponse,
  RetrievalConfigFields,
  RagChunk,
  RagSearchResult,
  Strategy,
} from "../types/api";

// ---------------------------------------------------------------------------
// Константы страницы
// ---------------------------------------------------------------------------

const API_BASE = (import.meta.env?.VITE_API_BASE as string | undefined) || "/api";

const MODES: Array<{ id: string; label: string }> = [
  { id: "baseline", label: "Baseline" },
  { id: "filter", label: "Similarity Filter" },
  { id: "rerank", label: "Reranking" },
  { id: "rewrite", label: "Query Rewrite" },
  { id: "rewrite_rerank", label: "Rewrite + Rerank" },
  { id: "full", label: "Rewrite + Filter + Rerank" },
];

const DEFAULT_MODES: Record<string, boolean> = {
  baseline: true,
  filter: true,
  rerank: true,
  rewrite: true,
  rewrite_rerank: true,
  full: true,
};

const LATENCY_STAGES: Array<{ key: string; label: string; tKey: string }> = [
  { key: "query_rewrite_ms", label: "Query rewrite", tKey: "exp.stage_query_rewrite" },
  { key: "embedding_ms", label: "Embedding", tKey: "exp.stage_embedding" },
  { key: "retrieval_ms", label: "Retrieval", tKey: "exp.stage_retrieval" },
  { key: "filtering_ms", label: "Filtering", tKey: "exp.stage_filtering" },
  { key: "reranking_ms", label: "Reranking", tKey: "exp.stage_reranking" },
  { key: "total_ms", label: "Total", tKey: "exp.stage_total" },
];

const TECH_ROWS: Array<{ key: keyof ModeRunResult["technical"]; label: string; tKey: string }> = [
  { key: "avg_candidates", label: "Avg candidates", tKey: "exp.tech_candidates" },
  { key: "avg_filtered", label: "Avg filtered", tKey: "exp.tech_filtered" },
  { key: "avg_similarity", label: "Avg similarity", tKey: "exp.tech_similarity" },
  { key: "avg_reranker_score", label: "Avg reranker score", tKey: "exp.tech_reranker_score" },
];

const RUN_STATUS_VARIANT: Record<EvalRun["status"], "success" | "warning" | "error" | "secondary"> = {
  queued: "secondary",
  running: "warning",
  completed: "success",
  failed: "error",
};

// ---------------------------------------------------------------------------
// Вспомогательные функции
// ---------------------------------------------------------------------------

function apiDetail(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Неизвестная ошибка";
}

/** Копирование в буфер обмена: navigator.clipboard с fallback на document.execCommand. */
async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // fallback для небезопасного контекста
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

/** Русские подписи статусов чанка для диалога просмотра. */
const CHUNK_STATUS_LABELS: Record<ChunkFinalStatus, string> = {
  kept: t("exp.chunk.status_kept", "В финале"),
  filtered: t("exp.chunk.status_filtered", "Отфильтрован"),
  deduplicated: t("exp.chunk.status_dedup", "Дубликат"),
  mmr_removed: t("exp.chunk.status_mmr", "Исключён MMR"),
  outside_final_top_k: t("exp.chunk.status_outside", "Вне Top-K"),
};

/** Ячейка «название — значение» в диалоге просмотра чанка. */
function InfoCell({ label, value, mono, title }: {
  label: string;
  value: ReactNode;
  mono?: boolean;
  title?: string;
}) {
  return (
    <div className="min-w-0" title={title}>
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`truncate ${mono ? "font-mono " : ""}text-xs text-foreground`}>{value}</p>
    </div>
  );
}

function strategyLabel(s: Strategy): string {
  if (s === "fixed_size") return t("strategy.fixed_size", "Фиксированный размер");
  return t("strategy.structural", "Структурная");
}

function runStatusLabel(status: EvalRun["status"]): string {
  switch (status) {
    case "queued":
      return t("exp.status_queued", "В очереди");
    case "running":
      return t("exp.status_running", "Выполняется");
    case "completed":
      return t("exp.status_completed", "Завершён");
    case "failed":
      return t("exp.status_failed", "Ошибка");
    default:
      return status;
  }
}

/** Строка через запятую → список. */
function parseCommaList(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

/** Список → строка через запятую. */
function joinList(list: string[]): string {
  return list.join(", ");
}

/** Нормализация элемента JSON-импорта (допускает массивы или строку через запятую). */
function normalizeItem(raw: unknown): EvalItem | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const question = typeof r.question === "string" ? r.question.trim() : "";
  if (!question) return null;
  const toList = (v: unknown): string[] => {
    if (Array.isArray(v)) {
      return v
        .filter((x): x is string => typeof x === "string")
        .map((x) => x.trim())
        .filter(Boolean);
    }
    if (typeof v === "string") return parseCommaList(v);
    return [];
  };
  return {
    question,
    expected_sources: toList(r.expected_sources),
    expected_sections: toList(r.expected_sections),
    relevant_chunk_ids: toList(r.relevant_chunk_ids),
  };
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Скачивание файла по API-пути (JSON/CSV/текст). */
async function fetchDownload(path: string, filename: string): Promise<void> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const j = (await resp.json()) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      // тело не JSON — оставляем HTTP-статус
    }
    throw new Error(detail);
  }
  const blob = await resp.blob();
  triggerDownload(blob, filename);
}

/** Форматирование произвольного значения из метрик эксперимента. */
function fmtValue(v: unknown): string {
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "—";
    return v.toFixed(4);
  }
  if (v === null || v === undefined) return "—";
  return String(v);
}

/** Количество позиций, в которых два финальных списка отличаются. */
function countDiff(a: string[], b: string[]): number {
  const len = Math.min(a.length, b.length);
  let diff = 0;
  for (let i = 0; i < len; i += 1) {
    if (a[i] !== b[i]) diff += 1;
  }
  return diff;
}

// ---------------------------------------------------------------------------
// Под-компоненты (только в этом файле)
// ---------------------------------------------------------------------------

/** Таблица метрик качества запуска (строки — режимы). N/A без ground truth. */
function RunMetricsTable({ run }: { run: EvalRun }) {
  const metrics = run.metrics ?? {};
  const results = run.results ?? {};
  const order: string[] = [];
  for (const m of run.config?.modes ?? []) {
    if ((metrics[m] !== undefined || results[m] !== undefined) && !order.includes(m)) order.push(m);
  }
  for (const m of Object.keys(metrics)) {
    if (!order.includes(m)) order.push(m);
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="px-4 py-3 font-medium">{t("exp.col_mode", "Режим")}</th>
            <th className="px-4 py-3 font-medium">{t("exp.col_hit", "Hit@K")}</th>
            <th className="px-4 py-3 font-medium">{t("exp.col_precision", "Precision@K")}</th>
            <th className="px-4 py-3 font-medium">{t("exp.col_recall", "Recall@K")}</th>
            <th className="px-4 py-3 font-medium">{t("exp.col_mrr", "MRR")}</th>
            <th className="px-4 py-3 font-medium">{t("exp.col_latency", "Latency (ms)")}</th>
            <th className="px-4 py-3 font-medium">{t("exp.col_questions", "Вопросы")}</th>
            <th className="px-4 py-3 font-medium">{t("exp.col_errors", "Ошибки")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {order.map((mode) => {
            const m = metrics[mode];
            const label = results[mode]?.label ?? mode;
            if (!m) {
              return (
                <tr key={mode}>
                  <td className="px-4 py-3 font-medium">{label}</td>
                  <td className="px-4 py-3 text-muted-foreground" colSpan={7}>—</td>
                </tr>
              );
            }
            const gt = m.has_ground_truth;
            return (
              <tr key={mode} className="transition-colors hover:bg-accent DEFAULT/40">
                <td className="px-4 py-3 font-medium">{label}</td>
                <td className="px-4 py-3 tabular-nums">{gt ? m.hit_at_k.toFixed(4) : "N/A"}</td>
                <td className="px-4 py-3 tabular-nums">{gt ? m.precision_at_k.toFixed(4) : "N/A"}</td>
                <td className="px-4 py-3 tabular-nums">{gt ? m.recall_at_k.toFixed(4) : "N/A"}</td>
                <td className="px-4 py-3 tabular-nums">{gt ? m.mrr.toFixed(4) : "N/A"}</td>
                <td className="px-4 py-3 tabular-nums">{Math.round(m.latency_ms)}</td>
                <td className="px-4 py-3 tabular-nums">{m.questions}</td>
                <td className="px-4 py-3 tabular-nums">{m.errors}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Таблица технических показателей (без слова «качество»). */
function RunTechnicalTable({ run }: { run: EvalRun }) {
  const results = run.results ?? {};
  const order = Object.keys(results);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="px-4 py-3 font-medium">{t("exp.col_metric", "Показатель")}</th>
            {order.map((mode) => (
              <th key={mode} className="px-4 py-3 font-medium">
                {results[mode]?.label ?? mode}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {TECH_ROWS.map((row) => (
            <tr key={row.key}>
              <td className="px-4 py-3">{t(row.tKey, row.label)}</td>
              {order.map((mode) => {
                const v = results[mode]?.technical?.[row.key];
                return (
                  <td key={mode} className="px-4 py-3 tabular-nums">
                    {v === null || v === undefined ? "—" : v.toFixed(4)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Плоский список строк «метрика → значение» для сохранённого эксперимента. */
function ExperimentMetricRows(exp: ExperimentItem): Array<{ label: string; value: string }> {
  const rows: Array<{ label: string; value: string }> = [];
  rows.push({ label: t("exp.exp_query", "Запрос"), value: exp.query });
  rows.push({ label: t("exp.exp_strategy", "Стратегия"), value: exp.strategy ?? "—" });
  const metrics = exp.metrics && typeof exp.metrics === "object" ? exp.metrics : null;
  const tech =
    metrics && typeof (metrics as Record<string, unknown>).technical === "object"
      ? ((metrics as Record<string, unknown>).technical as Record<string, unknown>)
      : null;
  if (tech) {
    const labels: Record<string, string> = {
      candidates: t("exp.tech_candidates", "Candidates"),
      filtered: t("exp.tech_filtered", "Filtered"),
      passed: t("exp.tech_passed", "Passed"),
      avg_similarity: t("exp.tech_similarity", "Avg similarity"),
      avg_reranker_score: t("exp.tech_reranker_score", "Avg reranker score"),
    };
    for (const [k, v] of Object.entries(tech)) {
      rows.push({ label: labels[k] ?? k, value: fmtValue(v) });
    }
  }
  if (exp.latency) {
    for (const [k, v] of Object.entries(exp.latency)) {
      rows.push({ label: k, value: formatMs(v) });
    }
  }
  rows.push({ label: t("exp.exp_final", "Финальных результатов"), value: String(exp.result.final?.count ?? 0) });
  return rows;
}

/** Одна колонка сравнения экспериментов (метрики слева, значения справа). */
function ExperimentColumn({ exp }: { exp: ExperimentItem }) {
  const rows = ExperimentMetricRows(exp);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="break-words">{exp.name}</CardTitle>
        <CardDescription>{formatDate(exp.created_at)}</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="space-y-2 text-sm">
          {rows.map((row) => (
            <div
              key={`${row.label}-${row.value}`}
              className="flex items-baseline justify-between gap-3 border-b border-border/50 pb-1.5"
            >
              <dt className="text-muted-foreground">{row.label}</dt>
              <dd className="text-right font-mono text-xs">{row.value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Страница
// ---------------------------------------------------------------------------

export function ExperimentPage() {
  const toast = useToast();

  // --- Коллекции и настройки -------------------------------------------------
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionsLoading, setCollectionsLoading] = useState(true);
  const [collectionsError, setCollectionsError] = useState<string | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [rerankersStatus, setRerankersStatus] = useState<RerankersStatusResponse | null>(null);

  const [collectionId, setCollectionId] = useState("");
  const [strategy, setStrategy] = useState<"" | Strategy>("");

  // --- Базовые параметры конфигурации ---------------------------------------
  const [initialTopK, setInitialTopK] = useState(20);
  const [finalTopK, setFinalTopK] = useState(5);
  const [threshold, setThreshold] = useState(0.65);
  const [rewriteModel, setRewriteModel] = useState("");
  const [reranker, setReranker] = useState<RerankerKind>("heuristic");
  const [rerankerModel, setRerankerModel] = useState("");
  const [runName, setRunName] = useState("");

  // --- Режимы сравнения ------------------------------------------------------
  const [enabledModes, setEnabledModes] = useState<Record<string, boolean>>(DEFAULT_MODES);

  // --- Evaluation-датасеты ---------------------------------------------------
  const [datasets, setDatasets] = useState<EvalDataset[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(true);
  const [datasetId, setDatasetId] = useState("");
  const [dataset, setDataset] = useState<EvalDataset | null>(null);
  const [items, setItems] = useState<EvalItem[]>([]);
  const [newDatasetName, setNewDatasetName] = useState("");
  const [newDatasetDescription, setNewDatasetDescription] = useState("");
  const [savingDataset, setSavingDataset] = useState(false);
  const importInputRef = useRef<HTMLInputElement>(null);

  // --- Запуски сравнения -----------------------------------------------------
  const [runningComparison, setRunningComparison] = useState(false);
  const [currentRun, setCurrentRun] = useState<EvalRun | null>(null);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(true);
  const [resultsTab, setResultsTab] = useState("metrics");
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [runDetail, setRunDetail] = useState<EvalRun | null>(null);
  const [runDetailLoading, setRunDetailLoading] = useState(false);

  // --- Сохранённые эксперименты ---------------------------------------------
  const [experiments, setExperiments] = useState<ExperimentItem[]>([]);
  const [experimentsLoading, setExperimentsLoading] = useState(true);
  const [singleQuery, setSingleQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [singleResult, setSingleResult] = useState<RagSearchResult | null>(null);
  const [singleDialogOpen, setSingleDialogOpen] = useState(false);
  /** Чанк, выбранный в списке результатов одиночного поиска (для просмотра текста). */
  const [selectedChunk, setSelectedChunk] = useState<RagChunk | null>(null);
  const [experimentName, setExperimentName] = useState("");
  const [savingExperiment, setSavingExperiment] = useState(false);
  const [currentExperimentId, setCurrentExperimentId] = useState("");
  const [comparingId, setComparingId] = useState<string | null>(null);
  const [compareData, setCompareData] = useState<{ current: ExperimentItem; compared: ExperimentItem; note: string } | null>(null);
  const [openExperiment, setOpenExperiment] = useState<ExperimentItem | null>(null);
  const [openExperimentLoading, setOpenExperimentLoading] = useState(false);

  // --- Первичная загрузка ----------------------------------------------------

  useEffect(() => {
    let cancelled = false;
    setCollectionsLoading(true);
    Promise.all([listCollections(), getSettings(), ragRerankersStatus()])
      .then(([cols, st, rrs]) => {
        if (cancelled) return;
        setCollections(cols);
        setSettings(st);
        setRerankersStatus(rrs);
        setInitialTopK(st.backend.default_initial_top_k);
        setFinalTopK(st.backend.default_final_top_k);
        setThreshold(st.backend.default_similarity_threshold);
        setRewriteModel(st.backend.query_rewrite_model ?? "");
        const rt = st.backend.reranker_type;
        setReranker(rt === "heuristic" || rt === "cross_encoder" || rt === "similarity" ? rt : "heuristic");
        setRerankerModel(st.backend.reranker_model ?? "");
        setCollectionsError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setCollectionsError(apiDetail(err));
      })
      .finally(() => {
        if (!cancelled) setCollectionsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listEvalDatasets(), listEvalRuns(50), listExperiments(200)])
      .then(([ds, rs, exps]) => {
        if (cancelled) return;
        setDatasets(ds);
        setRuns(rs);
        setExperiments(exps);
        setCurrentExperimentId((prev) => prev || (exps.length ? exps[0].id : ""));
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          toast.error(t("exp.load_failed", "Не удалось загрузить данные"), apiDetail(err));
        }
      })
      .finally(() => {
        if (cancelled) return;
        setDatasetsLoading(false);
        setRunsLoading(false);
        setExperimentsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedCollection = collections.find((c) => c.id === collectionId);
  const strategyOptions: Strategy[] = selectedCollection ? selectedCollection.strategies : [];

  // --- Конфигурация ----------------------------------------------------------

  function buildBaseConfig(): RetrievalConfigFields {
    const finalK = Math.max(1, finalTopK);
    const initialK = Math.max(1, initialTopK, finalK);
    return {
      query_rewrite: false,
      query_rewrite_model: rewriteModel.trim() ? rewriteModel.trim() : undefined,
      initial_top_k: initialK,
      final_top_k: finalK,
      enable_filter: true,
      similarity_threshold: threshold,
      enable_reranker: true,
      reranker,
      reranker_model: reranker === "cross_encoder" && rerankerModel.trim() ? rerankerModel.trim() : undefined,
      reranker_query: "original",
      deduplicate: false,
      dedup_threshold: 0.97,
      mmr: false,
      mmr_lambda: 0.7,
    };
  }

  function toggleMode(id: string) {
    setEnabledModes((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  // --- Работа с датасетами ----------------------------------------------------

  function applyDataset(ds: EvalDataset | null) {
    setDataset(ds);
    setItems(ds ? ds.items.map((it) => ({ ...it })) : []);
    setNewDatasetName(ds ? ds.name : "");
    setNewDatasetDescription(ds ? ds.description : "");
  }

  function handleDatasetChange(value: string) {
    setDatasetId(value);
    const ds = datasets.find((d) => d.id === value);
    applyDataset(ds ?? null);
    if (!value) return;
    getEvalDataset(value)
      .then((fresh) => {
        setDataset(fresh);
        setItems(fresh.items.map((it) => ({ ...it })));
      })
      .catch((err: unknown) => {
        toast.error(t("exp.dataset_load_failed", "Не удалось загрузить датасет"), apiDetail(err));
      });
  }

  async function refreshDatasets() {
    try {
      const ds = await listEvalDatasets();
      setDatasets(ds);
      if (datasetId) {
        const found = ds.find((d) => d.id === datasetId);
        if (found) {
          setDataset(found);
          setItems(found.items.map((it) => ({ ...it })));
        } else {
          setDatasetId("");
          applyDataset(null);
        }
      }
    } catch (err: unknown) {
      toast.error(t("exp.datasets_failed", "Не удалось загрузить датасеты"), apiDetail(err));
    }
  }

  async function handleSeedDemo() {
    try {
      const ds = await seedDemoEvalDataset();
      setDatasets((prev) => [ds, ...prev.filter((d) => d.id !== ds.id)]);
      setDatasetId(ds.id);
      applyDataset(ds);
      toast.success(t("exp.demo_ok", "Демо-датасет загружен"));
    } catch (err: unknown) {
      toast.error(t("exp.demo_failed", "Не удалось загрузить демо-датасет"), apiDetail(err));
    }
  }

  async function handleDeleteDataset() {
    if (!datasetId) return;
    try {
      await deleteEvalDataset(datasetId);
      setDatasets((prev) => prev.filter((d) => d.id !== datasetId));
      setDatasetId("");
      applyDataset(null);
      toast.success(t("exp.dataset_deleted", "Датасет удалён"));
    } catch (err: unknown) {
      toast.error(t("exp.dataset_delete_failed", "Не удалось удалить датасет"), apiDetail(err));
    }
  }

  async function handleSaveDatasetAsNew() {
    const name = newDatasetName.trim();
    const validItems = items
      .map((it) => ({ ...it, question: it.question.trim() }))
      .filter((it) => it.question !== "");
    if (!name) {
      toast.error(t("exp.need_dataset_name", "Укажите название датасета"));
      return;
    }
    if (!validItems.length) {
      toast.error(t("exp.need_items", "Добавьте хотя бы один вопрос"));
      return;
    }
    setSavingDataset(true);
    try {
      const ds = await createEvalDataset(name, newDatasetDescription.trim(), validItems);
      setDatasets((prev) => [ds, ...prev]);
      setDatasetId(ds.id);
      applyDataset(ds);
      toast.success(t("exp.dataset_saved", "Датасет сохранён"));
    } catch (err: unknown) {
      toast.error(t("exp.dataset_save_failed", "Не удалось сохранить датасет"), apiDetail(err));
    } finally {
      setSavingDataset(false);
    }
  }

  function addQuestion() {
    setItems((prev) => [
      ...prev,
      { question: "", expected_sources: [], expected_sections: [], relevant_chunk_ids: [] },
    ]);
  }

  function updateItem(idx: number, patch: Partial<EvalItem>) {
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  }

  function removeItem(idx: number) {
    setItems((prev) => prev.filter((_, i) => i !== idx));
  }

  async function handleImportFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const text = await file.text();
      const parsed: unknown = JSON.parse(text);
      let rawArray: unknown[] = [];
      if (Array.isArray(parsed)) {
        rawArray = parsed;
      } else if (parsed && typeof parsed === "object" && Array.isArray((parsed as { items?: unknown }).items)) {
        rawArray = (parsed as { items: unknown[] }).items;
      }
      const normalized = rawArray.map(normalizeItem).filter((x): x is EvalItem => x !== null);
      if (!normalized.length) {
        toast.error(t("exp.import_invalid", "Импорт не удался"), t("exp.import_invalid_desc", "В JSON нет валидных вопросов (обязательно поле question)."));
        return;
      }
      setItems(normalized);
      toast.success(t("exp.import_ok", "Импортировано"), `${normalized.length} ${t("exp.questions", "вопросов")}`);
    } catch {
      toast.error(t("exp.import_parse_failed", "Не удалось разобрать JSON"));
    }
  }

  function handleExportItemsJson() {
    const blob = new Blob([JSON.stringify(items, null, 2)], { type: "application/json" });
    triggerDownload(blob, "evaluation-dataset.json");
  }

  // --- Запуск сравнения режимов ----------------------------------------------

  async function handleRunComparison() {
    if (!datasetId) {
      toast.error(t("exp.validation", "Не заполнены параметры"), t("exp.need_dataset", "Выберите evaluation-датасет."));
      return;
    }
    if (!collectionId) {
      toast.error(t("exp.validation", "Не заполнены параметры"), t("exp.need_collection", "Выберите коллекцию."));
      return;
    }
    if (!strategy) {
      toast.error(t("exp.validation", "Не заполнены параметры"), t("exp.need_strategy", "Выберите стратегию."));
      return;
    }
    const modes = MODES.filter((m) => enabledModes[m.id]).map((m) => m.id);
    if (!modes.length) {
      toast.error(t("exp.validation", "Не заполнены параметры"), t("exp.need_mode", "Выберите хотя бы один режим."));
      return;
    }
    setRunningComparison(true);
    try {
      const req: EvalRunRequest = {
        collection_id: collectionId,
        strategy,
        modes,
        base_config: buildBaseConfig(),
      };
      if (runName.trim()) req.name = runName.trim();
      const res = await runEvaluation(datasetId, req);
      setCurrentRun(res);
      if (res.status === "failed") {
        toast.error(t("exp.run_failed", "Сравнение завершилось с ошибкой"), res.message ?? undefined);
      } else {
        toast.success(t("exp.run_done", "Сравнение завершено"));
      }
      void refreshRuns();
    } catch (err: unknown) {
      toast.error(t("exp.run_failed", "Не удалось запустить сравнение"), apiDetail(err));
    } finally {
      setRunningComparison(false);
    }
  }

  async function refreshRuns() {
    try {
      setRuns(await listEvalRuns(50));
    } catch (err: unknown) {
      toast.error(t("exp.runs_failed", "Не удалось загрузить историю запусков"), apiDetail(err));
    }
  }

  async function handleOpenRun(id: string) {
    setRunDialogOpen(true);
    setRunDetail(null);
    setRunDetailLoading(true);
    try {
      setRunDetail(await getEvalRun(id));
    } catch (err: unknown) {
      setRunDialogOpen(false);
      toast.error(t("exp.run_load_failed", "Не удалось загрузить запуск"), apiDetail(err));
    } finally {
      setRunDetailLoading(false);
    }
  }

  // --- Результаты (производные) ----------------------------------------------

  const runResults = useMemo<Record<string, ModeRunResult>>(() => currentRun?.results ?? {}, [currentRun]);
  const runMetrics = useMemo(() => currentRun?.metrics ?? {}, [currentRun]);
  const runLatency = useMemo(() => currentRun?.latency ?? {}, [currentRun]);

  const resultModes = useMemo(() => {
    if (!currentRun) return [];
    const order: string[] = [];
    for (const m of currentRun.config?.modes ?? []) {
      if ((runResults[m] !== undefined || runMetrics[m] !== undefined) && !order.includes(m)) order.push(m);
    }
    for (const m of Object.keys(runResults)) if (!order.includes(m)) order.push(m);
    for (const m of Object.keys(runMetrics)) if (!order.includes(m)) order.push(m);
    return order;
  }, [currentRun, runResults, runMetrics]);

  const labelFor = (mode: string): string => runResults[mode]?.label ?? mode;

  const anyGroundTruth = useMemo(
    () => Object.values(runMetrics).some((m) => m.has_ground_truth),
    [runMetrics],
  );

  /** Лучший режим по hit@k (только при наличии ground truth). */
  const bestMode = useMemo(() => {
    let best: { mode: string; hit: number } | null = null;
    for (const mode of resultModes) {
      const m = runMetrics[mode];
      if (m && m.has_ground_truth && (!best || m.hit_at_k > best.hit)) {
        best = { mode, hit: m.hit_at_k };
      }
    }
    return best;
  }, [resultModes, runMetrics]);

  /** Сравнение до/после reranking: средние по вопросам, без выдуманных данных. */
  const rerankVsBase = useMemo(() => {
    if (!currentRun || !runResults.rerank || !runResults.baseline) return null;
    const rerankRes = runResults.rerank;
    const baselineRes = runResults.baseline;
    const avgLen = (res: ModeRunResult): number => {
      const lens = res.per_question.map((p) => p.predicted_chunks.length);
      return lens.length ? lens.reduce((a, b) => a + b, 0) / lens.length : 0;
    };
    let diffTotal = 0;
    let diffCount = 0;
    const n = Math.min(baselineRes.per_question.length, rerankRes.per_question.length);
    for (let i = 0; i < n; i += 1) {
      const a = baselineRes.per_question[i].predicted_chunks;
      const b = rerankRes.per_question[i].predicted_chunks;
      if (a.length === 0 && b.length === 0) continue;
      diffTotal += countDiff(a, b);
      diffCount += 1;
    }
    // P — среднее число отсечённых фильтром кандидатов в режиме, где фильтрация включена
    const filterMode = runResults.full ? "full" : runResults.filter ? "filter" : "rerank";
    return {
      candidates: rerankRes.technical.avg_candidates,
      baselineFinal: avgLen(baselineRes),
      rerankedFinal: avgLen(rerankRes),
      changedPositions: diffCount ? diffTotal / diffCount : 0,
      filtered: runResults[filterMode].technical.avg_filtered,
      filterMode,
    };
  }, [currentRun, runResults]);

  /** Строки «original → rewritten» из per_question всех режимов. */
  const rewrittenRows = useMemo(() => {
    const out: Array<{ mode: string; label: string; question: string; rewritten: string }> = [];
    for (const mode of resultModes) {
      const res = runResults[mode];
      if (!res) continue;
      for (const pq of res.per_question) {
        if (pq.rewritten_query) {
          out.push({ mode, label: res.label ?? mode, question: pq.question, rewritten: pq.rewritten_query });
        }
      }
    }
    return out;
  }, [resultModes, runResults]);

  const rewriteGroups = useMemo(() => {
    const groups = new Map<string, typeof rewrittenRows>();
    for (const row of rewrittenRows) {
      const arr = groups.get(row.mode) ?? [];
      arr.push(row);
      groups.set(row.mode, arr);
    }
    return Array.from(groups.entries());
  }, [rewrittenRows]);

  // --- Одиночный поиск и сохранение экспериментов -----------------------------

  async function handleSingleSearch() {
    if (!collectionId) {
      toast.error(t("exp.validation", "Не заполнены параметры"), t("exp.need_collection", "Выберите коллекцию."));
      return;
    }
    if (!strategy) {
      toast.error(t("exp.validation", "Не заполнены параметры"), t("exp.need_strategy", "Выберите стратегию."));
      return;
    }
    if (!singleQuery.trim()) {
      toast.error(t("exp.validation", "Не заполнены параметры"), t("exp.need_query", "Введите текст запроса."));
      return;
    }
    setSearching(true);
    try {
      const res = await ragSearch(collectionId, strategy, singleQuery.trim(), buildBaseConfig());
      setSingleResult(res);
      setExperimentName(t("exp.new_experiment", "Эксперимент"));
      setSingleDialogOpen(true);
    } catch (err: unknown) {
      toast.error(t("exp.single_failed", "Не удалось выполнить поиск"), apiDetail(err));
    } finally {
      setSearching(false);
    }
  }

  async function handleSaveExperiment() {
    if (!singleResult) return;
    const name = experimentName.trim() || singleResult.original_query.slice(0, 80);
    setSavingExperiment(true);
    try {
      const exp = await saveExperiment({
        name,
        query: singleResult.original_query,
        config: singleResult.config,
        collection_id: collectionId || undefined,
        strategy: strategy || undefined,
        result: singleResult,
      });
      setExperiments((prev) => [exp, ...prev]);
      setCurrentExperimentId(exp.id);
      setSingleDialogOpen(false);
      toast.success(t("exp.experiment_saved", "Эксперимент сохранён"));
    } catch (err: unknown) {
      toast.error(t("exp.experiment_save_failed", "Не удалось сохранить эксперимент"), apiDetail(err));
    } finally {
      setSavingExperiment(false);
    }
  }

  async function handleOpenExperiment(id: string) {
    setOpenExperimentLoading(true);
    try {
      const exp = await getExperiment(id);
      setOpenExperiment(exp);
    } catch (err: unknown) {
      toast.error(t("exp.experiment_load_failed", "Не удалось загрузить эксперимент"), apiDetail(err));
    } finally {
      setOpenExperimentLoading(false);
    }
  }

  async function handleDeleteExperiment(id: string) {
    try {
      await deleteExperiment(id);
      setExperiments((prev) => {
        const next = prev.filter((e) => e.id !== id);
        setCurrentExperimentId((cur) => (cur === id ? (next.length ? next[0].id : "") : cur));
        return next;
      });
      toast.success(t("exp.experiment_deleted", "Эксперимент удалён"));
    } catch (err: unknown) {
      toast.error(t("exp.experiment_delete_failed", "Не удалось удалить эксперимент"), apiDetail(err));
    }
  }

  async function handleCompare(exp: ExperimentItem) {
    if (!currentExperimentId) {
      toast.error(t("exp.need_current", "Нет текущего эксперимента для сравнения"));
      return;
    }
    if (currentExperimentId === exp.id) return;
    setComparingId(exp.id);
    try {
      const data = await compareExperiments(currentExperimentId, exp.id);
      setCompareData(data);
    } catch (err: unknown) {
      toast.error(t("exp.compare_failed", "Не удалось сравнить эксперименты"), apiDetail(err));
    } finally {
      setComparingId(null);
    }
  }

  async function handleExportRun(id: string, format: "json" | "csv") {
    try {
      await fetchDownload(`/evaluation/runs/${id}/export?format=${format}`, `run-${id}.${format}`);
    } catch (err: unknown) {
      toast.error(t("exp.export_failed", "Не удалось экспортировать"), apiDetail(err));
    }
  }

  async function handleExportExperiment(id: string, format: "json" | "csv") {
    try {
      await fetchDownload(`/experiments/${id}/export?format=${format}`, `experiment-${id}.${format}`);
    } catch (err: unknown) {
      toast.error(t("exp.export_failed", "Не удалось экспортировать"), apiDetail(err));
    }
  }

  const rerankerStatus = rerankersStatus ? rerankersStatus[reranker] : null;

  // ---------------------------------------------------------------------------
  // JSX
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* 1. Конфигурация поиска */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4" />
            {t("exp.config_title", "Конфигурация поиска")}
          </CardTitle>
          <CardDescription>
            {t("exp.config_description", "Коллекция, стратегия и базовые параметры, применяемые ко всем режимам")}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {collectionsError ? (
            <Alert variant="error">
              {t("exp.collections_error", "Не удалось загрузить коллекции")}: {collectionsError}
            </Alert>
          ) : null}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Select
              label={t("exp.collection", "Коллекция")}
              value={collectionId}
              disabled={collectionsLoading}
              onChange={(e) => {
                setCollectionId(e.target.value);
                setStrategy("");
                setCurrentRun(null);
              }}
              hint={
                collectionsLoading
                  ? t("exp.collections_loading", "Загрузка коллекций…")
                  : selectedCollection
                    ? `${t("exp.collection_strategies", "Стратегии")}: ${selectedCollection.strategies.join(", ")}`
                    : undefined
              }
            >
              <option value="">{t("exp.collection_placeholder", "Выберите коллекцию")}</option>
              {collections.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
            <Select
              label={t("exp.strategy", "Стратегия")}
              value={strategy}
              disabled={!selectedCollection}
              onChange={(e) => setStrategy(e.target.value === "" ? "" : (e.target.value as Strategy))}
              hint={!selectedCollection ? t("exp.strategy_needs_collection", "Сначала выберите коллекцию") : undefined}
            >
              <option value="">{t("exp.strategy_placeholder", "Выберите стратегию")}</option>
              {strategyOptions.map((s) => (
                <option key={s} value={s}>
                  {strategyLabel(s)}
                </option>
              ))}
            </Select>
            <Input
              label={t("exp.initial_top_k", "Initial Top-K")}
              type="number"
              min={1}
              max={500}
              value={String(initialTopK)}
              onChange={(e) => setInitialTopK(Number(e.target.value))}
            />
            <Input
              label={t("exp.final_top_k", "Final Top-K")}
              type="number"
              min={1}
              max={100}
              value={String(finalTopK)}
              onChange={(e) => setFinalTopK(Number(e.target.value))}
            />
            <div className="sm:col-span-2">
              <Slider
                label={t("exp.threshold", "Similarity threshold")}
                value={threshold}
                min={0}
                max={1}
                step={0.01}
                onChange={setThreshold}
              />
            </div>
            <Input
              label={t("exp.rewrite_model", "Query rewrite model")}
              value={rewriteModel}
              onChange={(e) => setRewriteModel(e.target.value)}
              placeholder={settings?.backend.query_rewrite_model ?? "llama3.1"}
            />
            <Select
              label={t("exp.reranker", "Reranker")}
              value={reranker}
              onChange={(e) => setReranker(e.target.value as RerankerKind)}
              hint={
                rerankerStatus
                  ? `${rerankerStatus.available ? t("exp.reranker_available", "Доступен") : t("exp.reranker_unavailable", "Недоступен")}${rerankerStatus.reason ? ` — ${rerankerStatus.reason}` : ""}`
                  : undefined
              }
            >
              <option value="heuristic">{t("exp.reranker_heuristic", "Heuristic")}</option>
              <option value="cross_encoder">{t("exp.reranker_cross_encoder", "Cross-encoder")}</option>
              <option value="similarity">{t("exp.reranker_similarity", "Similarity")}</option>
            </Select>
            {reranker === "cross_encoder" ? (
              <Input
                label={t("exp.reranker_model", "Reranker model")}
                value={rerankerModel}
                onChange={(e) => setRerankerModel(e.target.value)}
                placeholder={rerankersStatus?.default_model ?? "rerank-model"}
              />
            ) : null}
          </div>
        </CardContent>
      </Card>

      {/* 2. Evaluation-датасет + 3. Режимы сравнения */}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-4 w-4" />
              {t("exp.dataset_title", "Evaluation Dataset")}
            </CardTitle>
            <CardDescription>
              {t("exp.dataset_description", "Вопросы и ground truth для оценки режимов поиска")}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[240px] flex-1">
                <Select
                  label={t("exp.dataset", "Датасет")}
                  value={datasetId}
                  disabled={datasetsLoading}
                  onChange={(e) => handleDatasetChange(e.target.value)}
                  hint={datasetsLoading ? t("exp.datasets_loading", "Загрузка датасетов…") : undefined}
                >
                  <option value="">{t("exp.dataset_placeholder", "Выберите датасет")}</option>
                  {datasets.map((ds) => (
                    <option key={ds.id} value={ds.id}>
                      {ds.name} ({ds.items.length})
                    </option>
                  ))}
                </Select>
              </div>
              <Button variant="secondary" onClick={() => void handleSeedDemo()}>
                <Wand2 className="h-4 w-4" />
                {t("exp.demo_dataset", "Загрузить демо-датасет")}
              </Button>
              <Button variant="outline" disabled={!datasetId} onClick={() => void handleDeleteDataset()}>
                <Trash2 className="h-4 w-4" />
                {t("exp.delete_dataset", "Удалить")}
              </Button>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                label={t("exp.new_dataset_name", "Название нового датасета")}
                value={newDatasetName}
                onChange={(e) => setNewDatasetName(e.target.value)}
                placeholder={t("exp.new_dataset_name_placeholder", "Например: FAQ по RAG")}
              />
              <Input
                label={t("exp.new_dataset_desc", "Описание")}
                value={newDatasetDescription}
                onChange={(e) => setNewDatasetDescription(e.target.value)}
              />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" onClick={addQuestion}>
                <Plus className="h-4 w-4" />
                {t("exp.add_question", "Добавить вопрос")}
              </Button>
              <Button variant="outline" size="sm" onClick={() => importInputRef.current?.click()}>
                <Upload className="h-4 w-4" />
                {t("exp.import_json", "Импорт JSON")}
              </Button>
              <input
                ref={importInputRef}
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={(e) => void handleImportFile(e)}
              />
              <Button variant="outline" size="sm" onClick={handleExportItemsJson}>
                <Download className="h-4 w-4" />
                {t("exp.export_json", "Экспорт JSON")}
              </Button>
              <span className="ml-auto">
                <Button size="sm" onClick={() => void handleSaveDatasetAsNew()} loading={savingDataset}>
                  <Save className="h-4 w-4" />
                  {t("exp.save_as_new", "Сохранить как новый датасет")}
                </Button>
              </span>
            </div>

            {items.length === 0 ? (
              <EmptyState
                icon={<ListChecks className="h-6 w-6" />}
                title={t("exp.items_empty_title", "Вопросов пока нет")}
                description={t("exp.items_empty_description", "Выберите датасет, загрузите демо-датасет или добавьте вопросы вручную.")}
              />
            ) : (
              <div className="space-y-3">
                {items.map((item, idx) => (
                  <div key={idx} className="space-y-3 rounded-lg border border-border p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {t("exp.item_label", "Вопрос")} {idx + 1}
                      </span>
                      <Button variant="ghost" size="icon" onClick={() => removeItem(idx)} title={t("exp.delete_question", "Удалить вопрос")}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                    <Textarea
                      rows={2}
                      value={item.question}
                      onChange={(e) => updateItem(idx, { question: e.target.value })}
                      placeholder={t("exp.question_placeholder", "Текст вопроса")}
                    />
                    <div className="grid gap-3 sm:grid-cols-3">
                      <Input
                        label={t("exp.expected_sources", "Expected sources")}
                        value={joinList(item.expected_sources)}
                        onChange={(e) => updateItem(idx, { expected_sources: parseCommaList(e.target.value) })}
                        placeholder="source1.md, source2.md"
                      />
                      <Input
                        label={t("exp.expected_sections", "Expected sections")}
                        value={joinList(item.expected_sections)}
                        onChange={(e) => updateItem(idx, { expected_sections: parseCommaList(e.target.value) })}
                        placeholder="Раздел 1, Раздел 2"
                      />
                      <Input
                        label={t("exp.relevant_chunk_ids", "Relevant chunk ids")}
                        value={joinList(item.relevant_chunk_ids)}
                        onChange={(e) => updateItem(idx, { relevant_chunk_ids: parseCommaList(e.target.value) })}
                        placeholder="chunk_1, chunk_2"
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Layers className="h-4 w-4" />
              {t("exp.modes_title", "Режимы сравнения")}
            </CardTitle>
            <CardDescription>
              {t("exp.modes_description", "Каждый режим включает или отключает этапы пайплайна")}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2.5">
              {MODES.map((m) => (
                <ToggleSwitch
                  key={m.id}
                  checked={enabledModes[m.id] ?? false}
                  onChange={() => toggleMode(m.id)}
                  label={m.label}
                />
              ))}
            </div>
            <Input
              label={t("exp.run_name", "Название сравнения")}
              value={runName}
              onChange={(e) => setRunName(e.target.value)}
              placeholder={t("exp.run_name_placeholder", "Необязательно")}
            />
            <Button className="w-full" onClick={() => void handleRunComparison()} loading={runningComparison}>
              <Play className="h-4 w-4" />
              {t("exp.run", "Запустить сравнение")}
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* 4. Результаты сравнения */}
      {!currentRun ? (
        <EmptyState
          icon={<BarChart3 className="h-6 w-6" />}
          title={t("exp.no_run_title", "Запустите сравнение")}
          description={t("exp.no_run_description", "Выберите коллекцию, стратегию и датасет, затем запустите сравнение режимов — результаты появятся здесь.")}
          action={
            <Button onClick={() => void handleRunComparison()} loading={runningComparison}>
              <Play className="h-4 w-4" />
              {t("exp.run", "Запустить сравнение")}
            </Button>
          }
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              {t("exp.results_title", "Результаты сравнения")}
            </CardTitle>
            <CardDescription>
              {currentRun.id}
              {currentRun.config?.modes?.length ? ` · ${currentRun.config.modes.join(", ")}` : ""}
              {currentRun.created_at ? ` · ${formatDate(currentRun.created_at)}` : ""}
              {currentRun.name ? ` · ${currentRun.name}` : ""}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {currentRun.status === "failed" && currentRun.message ? (
              <Alert variant="error">{currentRun.message}</Alert>
            ) : null}

            {currentRun.status === "completed" && (resultModes.length > 0 || Object.keys(runMetrics).length > 0) ? (
              <>
                <Tabs
                  tabs={[
                    { id: "metrics", label: t("exp.tab_metrics", "Метрики") },
                    { id: "technical", label: t("exp.tab_technical", "Технические") },
                    { id: "latency", label: t("exp.tab_latency", "Latency") },
                    { id: "insights", label: t("exp.tab_insights", "Trade-offs") },
                  ]}
                  active={resultsTab}
                  onChange={setResultsTab}
                />

                {resultsTab === "metrics" ? (
                  <div className="space-y-4">
                    <p className="flex items-center gap-2 text-sm text-muted-foreground">
                      <ListChecks className="h-4 w-4" />
                      {t("exp.metrics_subtitle", "Метрики качества по режимам (требуется ground truth)")}
                    </p>
                    <RunMetricsTable run={currentRun} />
                    {!anyGroundTruth ? (
                      <Alert variant="info">
                        {t(
                          "exp.no_ground_truth",
                          "Evaluation dataset not configured. Add expected relevant chunks to calculate retrieval quality.",
                        )}
                      </Alert>
                    ) : null}
                  </div>
                ) : null}

                {resultsTab === "technical" ? (
                  <div className="space-y-4">
                    <p className="text-sm text-muted-foreground">
                      {t("exp.technical_subtitle", "Технические показатели пайплайна (средние по вопросам)")}
                    </p>
                    <RunTechnicalTable run={currentRun} />
                  </div>
                ) : null}

                {resultsTab === "latency" ? (
                  <div className="space-y-4">
                    <p className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Clock className="h-4 w-4" />
                      {t("exp.latency_subtitle", "Средняя латентность этапов на вопрос (run.latency)")}
                    </p>
                    <div className="overflow-x-auto rounded-md border border-border p-3">
                      <ColumnChart
                        data={resultModes.map((mode) => ({
                          name: labelFor(mode),
                          total: runLatency[mode]?.total_ms ?? 0,
                        }))}
                        keys={[{ key: "total", name: t("exp.latency_total", "Total, ms") }]}
                      />
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      {resultModes.map((mode) => (
                        <Card key={mode}>
                          <CardHeader>
                            <CardTitle className="text-sm">{labelFor(mode)}</CardTitle>
                          </CardHeader>
                          <CardContent>
                            <TimingLineChart
                              data={LATENCY_STAGES.map((stage) => ({
                                name: t(stage.tKey, stage.label),
                                value: runLatency[mode]?.[stage.key] ?? 0,
                              }))}
                              height={220}
                            />
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  </div>
                ) : null}

                {resultsTab === "insights" ? (
                  <div className="space-y-4">
                    <Alert variant="info" icon={<Info className="h-4 w-4" />}>
                      <p className="mb-1 font-medium">{t("exp.tradeoffs_title", "Trade-offs режимов")}</p>
                      <ul className="list-disc space-y-1 pl-5">
                        <li>
                          {t(
                            "exp.tradeoff_baseline",
                            "Baseline: быстро, просто и минимум вычислений; similarity ≠ релевантность.",
                          )}
                        </li>
                        <li>
                          {t(
                            "exp.tradeoff_filter",
                            "Filtering: уменьшает шум, но неверный порог удаляет полезные чанки.",
                          )}
                        </li>
                        <li>
                          {t(
                            "exp.tradeoff_rerank",
                            "Reranking: точнее оценивает пару query-document, но добавляет латентность.",
                          )}
                        </li>
                        <li>
                          {t(
                            "exp.tradeoff_rewrite",
                            "Query Rewrite: уточняет запрос, но может изменить его смысл и добавляет латентность.",
                          )}
                        </li>
                      </ul>
                    </Alert>

                    {bestMode ? (
                      <Alert variant="success" icon={<CheckCircle2 className="h-4 w-4" />}>
                        {t("exp.best_mode", "На данном evaluation dataset и при данных параметрах режим")}{" "}
                        <span className="font-medium">«{labelFor(bestMode.mode)}»</span>{" "}
                        {t("exp.best_mode_metrics", "показал лучшие результаты по метрике Hit@K:")}{" "}
                        <span className="font-mono">{bestMode.hit.toFixed(4)}</span>
                      </Alert>
                    ) : (
                      <Alert variant="info" icon={<Info className="h-4 w-4" />}>
                        {t("exp.best_mode_unknown", "Недостаточно данных для вывода")}
                      </Alert>
                    )}

                    {rerankVsBase ? (
                      <Card>
                        <CardHeader>
                          <CardTitle className="flex items-center gap-2 text-sm">
                            <GitCompareArrows className="h-4 w-4" />
                            {t("exp.rerank_compare", "Сравнение до/после reranking")}
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          <p className="font-mono text-sm">
                            {t("exp.rerank_compare_n", "Initial candidates: ")}
                            {Math.round(rerankVsBase.candidates)}
                            {"; "}
                            {t("exp.rerank_compare_base", "Baseline final: ")}
                            {Math.round(rerankVsBase.baselineFinal)}
                            {"; "}
                            {t("exp.rerank_compare_reranked", "Reranked final: ")}
                            {Math.round(rerankVsBase.rerankedFinal)}
                            {"; "}
                            {t("exp.rerank_compare_changed", "Changed positions: ")}
                            {Math.round(rerankVsBase.changedPositions)}
                            {"; "}
                            {t("exp.rerank_compare_filtered", "Filtered: ")}
                            {Math.round(rerankVsBase.filtered)}
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {t("exp.rerank_compare_note", "Средние значения по вопросам из per_question. «Filtered» — среднее число отсечённых фильтром чанков (режим «")}
                            {rerankVsBase.filterMode}
                            {t("exp.rerank_compare_note2", "»); если фильтрация в режиме отключена, значение равно 0.")}
                          </p>
                        </CardContent>
                      </Card>
                    ) : null}

                    {rewriteGroups.length ? (
                      <Card>
                        <CardHeader>
                          <CardTitle className="flex items-center gap-2 text-sm">
                            <PenLine className="h-4 w-4" />
                            {t("exp.rewrite_compare", "Query rewrite")}
                          </CardTitle>
                          <CardDescription>
                            {t("exp.rewrite_compare_desc", "Оригинальные и переписанные запросы к вопросам")}
                          </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                          {rewriteGroups.map(([mode, rows]) => (
                            <div key={mode}>
                              <p className="mb-2 text-sm font-medium">{rows[0].label}</p>
                              <div className="overflow-x-auto rounded-md border border-border">
                                <table className="w-full text-sm">
                                  <thead>
                                    <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                                      <th className="px-3 py-2 font-medium">#</th>
                                      <th className="px-3 py-2 font-medium">{t("exp.original", "Оригинал")}</th>
                                      <th className="px-3 py-2 font-medium">{t("exp.rewritten", "Переписанный")}</th>
                                    </tr>
                                  </thead>
                                  <tbody className="divide-y divide-border">
                                    {rows.map((row, i) => (
                                      <tr key={`${mode}-${i}`}>
                                        <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{i + 1}</td>
                                        <td className="px-3 py-2">{row.question}</td>
                                        <td className="px-3 py-2 text-muted-foreground">{row.rewritten}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            </div>
                          ))}
                        </CardContent>
                      </Card>
                    ) : null}

                  </div>
                ) : null}
              </>
            ) : null}
          </CardContent>
        </Card>
      )}

      {/* 5. История запусков */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="h-4 w-4" />
            {t("exp.runs_title", "История запусков")}
          </CardTitle>
          <CardDescription>
            {t("exp.runs_description", "Последние запуски сравнения режимов")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {runsLoading ? (
            <Spinner label={t("exp.runs_loading", "Загрузка запусков…")} />
          ) : runs.length === 0 ? (
            <EmptyState
              icon={<History className="h-6 w-6" />}
              title={t("exp.runs_empty", "Запусков пока нет")}
              description={t("exp.runs_empty_desc", "Запустите сравнение — результат появится в истории.")}
            />
          ) : (
            <div className="space-y-3">
              <div className="flex justify-end">
                <Button variant="ghost" size="sm" onClick={() => void refreshRuns()}>
                  <RefreshCw className="h-4 w-4" />
                  {t("exp.refresh", "Обновить")}
                </Button>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="px-5 py-3 font-medium">ID</th>
                      <th className="px-4 py-3 font-medium">{t("exp.col_status", "Статус")}</th>
                      <th className="px-4 py-3 font-medium">{t("exp.col_name", "Название")}</th>
                      <th className="px-4 py-3 font-medium">{t("exp.col_created", "Создан")}</th>
                      <th className="px-4 py-3 text-right font-medium" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {runs.map((run) => (
                      <tr key={run.id} className="transition-colors hover:bg-accent DEFAULT/40">
                        <td className="px-5 py-3 font-mono text-xs">{run.id}</td>
                        <td className="px-4 py-3">
                          <Badge variant={RUN_STATUS_VARIANT[run.status]}>
                            {run.status === "completed" ? <CheckCircle2 className="h-3.5 w-3.5" /> : null}
                            {runStatusLabel(run.status)}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">{run.name || "—"}</td>
                        <td className="px-4 py-3 text-muted-foreground">{formatDate(run.created_at)}</td>
                        <td className="px-4 py-3 text-right">
                          <Button variant="outline" size="sm" onClick={() => void handleOpenRun(run.id)}>
                            <Eye className="h-3.5 w-3.5" />
                            {t("exp.details", "Подробнее")}
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 6. Эксперименты */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Save className="h-4 w-4" />
            {t("exp.experiments_title", "Сохранённые эксперименты")}
          </CardTitle>
          <CardDescription>
            {t("exp.experiments_description", "Отдельные поиски с полной конфигурацией и результатами")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-6 lg:grid-cols-3">
            {/* Слева — список сохранённых экспериментов */}
            <div className="space-y-3 lg:col-span-1">
              <Select
                label={t("exp.current_for_compare", "Текущий для сравнения")}
                value={currentExperimentId}
                onChange={(e) => setCurrentExperimentId(e.target.value)}
                disabled={experiments.length === 0}
              >
                <option value="">{t("exp.current_placeholder", "Не выбран")}</option>
                {experiments.map((exp) => (
                  <option key={exp.id} value={exp.id}>
                    {exp.name}
                  </option>
                ))}
              </Select>
              {experimentsLoading ? (
                <Spinner label={t("exp.experiments_loading", "Загрузка экспериментов…")} />
              ) : experiments.length === 0 ? (
                <EmptyState
                  icon={<Save className="h-6 w-6" />}
                  title={t("exp.experiments_empty", "Экспериментов нет")}
                  description={t("exp.experiments_empty_desc", "Запустите одиночный поиск и сохраните его как эксперимент.")}
                />
              ) : (
                <div className="space-y-3">
                  {experiments.map((exp) => (
                    <Card key={exp.id}>
                      <CardContent className="space-y-2">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold">{exp.name}</p>
                            <p className="truncate text-xs text-muted-foreground">{exp.query}</p>
                          </div>
                          <span className="shrink-0 text-[11px] text-muted-foreground">{formatDate(exp.created_at)}</span>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Button size="sm" variant="outline" onClick={() => void handleOpenExperiment(exp.id)}>
                            <Eye className="h-3.5 w-3.5" />
                            {t("exp.open", "Открыть")}
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={!currentExperimentId || currentExperimentId === exp.id}
                            loading={comparingId === exp.id}
                            onClick={() => void handleCompare(exp)}
                          >
                            <GitCompareArrows className="h-3.5 w-3.5" />
                            {t("exp.compare_with_current", "Сравнить с текущим")}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => void handleExportExperiment(exp.id, "json")}>
                            <FileJson className="h-3.5 w-3.5" />
                            {t("exp.export_json", "JSON")}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => void handleExportExperiment(exp.id, "csv")}>
                            <Download className="h-3.5 w-3.5" />
                            {t("exp.export_csv", "CSV")}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => void handleDeleteExperiment(exp.id)}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </div>

            {/* Справа — одиночный поиск */}
            <div className="space-y-3 lg:col-span-2">
              <Textarea
                label={t("exp.single_query", "Запрос для одиночного поиска")}
                rows={4}
                value={singleQuery}
                onChange={(e) => setSingleQuery(e.target.value)}
                placeholder={t("exp.single_query_placeholder", "Например: как работает реранкинг в RAG?")}
              />
              <Button onClick={() => void handleSingleSearch()} loading={searching}>
                <Search className="h-4 w-4" />
                {t("exp.single_search", "Запустить одиночный поиск")}
              </Button>
              <Alert variant="info" icon={<Info className="h-4 w-4" />}>
                {t(
                  "exp.single_note",
                  "Одиночный поиск выполняется с текущими параметрами конфигурации; ground truth для него не требуется.",
                )}
              </Alert>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Диалог деталей запуска */}
      <Dialog
        wide
        open={runDialogOpen}
        onClose={() => setRunDialogOpen(false)}
        title={runDetail ? runDetail.name || t("exp.run_title", "Запуск") : t("exp.run_title", "Запуск")}
        description={
          runDetail
            ? `${t("exp.run_id", "ID")}: ${runDetail.id} · ${t("exp.col_created", "Создан")}: ${formatDate(runDetail.created_at)}`
            : undefined
        }
      >
        {runDetailLoading ? (
          <Spinner label={t("exp.run_loading", "Загрузка деталей запуска…")} />
        ) : runDetail ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={RUN_STATUS_VARIANT[runDetail.status]}>{runStatusLabel(runDetail.status)}</Badge>
              {runDetail.name ? <Badge variant="outline">{runDetail.name}</Badge> : null}
              {runDetail.dataset_id ? <Badge variant="outline">{runDetail.dataset_id}</Badge> : null}
            </div>
            {runDetail.message ? <Alert variant="error">{runDetail.message}</Alert> : null}
            {runDetail.status === "completed" && runDetail.metrics ? (
              <>
                <div>
                  <p className="mb-2 text-sm font-medium">{t("exp.dialog_metrics", "Метрики по режимам")}</p>
                  <RunMetricsTable run={runDetail} />
                </div>
                <div>
                  <p className="mb-2 text-sm font-medium">{t("exp.dialog_technical", "Технические показатели")}</p>
                  <RunTechnicalTable run={runDetail} />
                </div>
                {runDetail.latency ? (
                  <div>
                    <p className="mb-2 text-sm font-medium">{t("exp.dialog_latency", "Средняя латентность (total)")}</p>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(runDetail.latency).map(([mode, l]) => (
                        <span key={mode} className="rounded-full border border-border px-2 py-0.5 font-mono text-xs">
                          {runDetail.results?.[mode]?.label ?? mode}: {formatMs(l.total_ms ?? 0)}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
              </>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => void handleExportRun(runDetail.id, "json")}>
                <FileJson className="h-4 w-4" />
                {t("exp.export_json", "Экспорт JSON")}
              </Button>
              <Button variant="outline" size="sm" onClick={() => void handleExportRun(runDetail.id, "csv")}>
                <Download className="h-4 w-4" />
                {t("exp.export_csv", "Экспорт CSV")}
              </Button>
            </div>
          </div>
        ) : null}
      </Dialog>

      {/* Диалог результата одиночного поиска */}
      <Dialog
        wide
        open={singleDialogOpen}
        onClose={() => setSingleDialogOpen(false)}
        title={t("exp.single_title", "Результат одиночного поиска")}
        description={singleResult?.original_query ?? undefined}
      >
        {singleResult ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">{strategyLabel(singleResult.retrieval.strategy as Strategy)}</Badge>
              <Badge variant="outline">
                {t("exp.candidates", "Candidates")}: {singleResult.retrieval.candidates}
              </Badge>
              <Badge variant="outline">
                {t("exp.final_count", "Final")}: {singleResult.final.count}
              </Badge>
              <Badge variant="outline">total: {formatMs(singleResult.latency.total_ms)}</Badge>
            </div>
            {singleResult.rewritten_query ? (
              <Alert variant="info">
                <span className="font-medium">{t("exp.rewritten", "Переписанный запрос")}: </span>
                {singleResult.rewritten_query}
              </Alert>
            ) : null}
            {singleResult.note ? <Alert variant="info">{singleResult.note}</Alert> : null}
            <div>
              <p className="mb-2 text-sm font-medium">{t("exp.final_results", "Финальные результаты")}</p>
              <div className="space-y-2">
                {singleResult.final.results.map((it) => (
                  <button
                    key={it.chunk_id}
                    type="button"
                    onClick={() => setSelectedChunk(it)}
                    className="flex w-full items-start gap-3 rounded-md border border-border p-2 text-left transition-colors hover:bg-accent DEFAULT/45"
                    title={t("exp.chunk.open", "Открыть текст чанка")}
                  >
                    <span className="mt-0.5 font-mono text-xs text-muted-foreground">{it.final_rank ?? "—"}</span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{it.title || it.source}</p>
                      {it.section ? <p className="truncate text-xs text-muted-foreground">{it.section}</p> : null}
                      <p className="truncate font-mono text-[10px] text-muted-foreground">{it.chunk_id}</p>
                    </div>
                    <span className="shrink-0 font-mono text-xs text-muted-foreground">
                      {it.reranker_score !== null && it.reranker_score !== undefined
                        ? `rerank ${it.reranker_score.toFixed(3)}`
                        : `sim ${it.retrieval_score.toFixed(3)}`}
                    </span>
                  </button>
                ))}
              </div>
            </div>
            <div className="rounded-lg border border-border p-3">
              <p className="mb-2 text-sm font-medium">{t("exp.save_experiment_title", "Сохранить эксперимент")}</p>
              <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-[220px] flex-1">
                  <Input
                    label={t("exp.experiment_name", "Название")}
                    value={experimentName}
                    onChange={(e) => setExperimentName(e.target.value)}
                    placeholder={t("exp.experiment_name_placeholder", "Например: тест threshold 0.7")}
                  />
                </div>
                <Button onClick={() => void handleSaveExperiment()} loading={savingExperiment}>
                  <Save className="h-4 w-4" />
                  {t("exp.save_experiment", "Сохранить эксперимент")}
                </Button>
              </div>
            </div>
          </div>
        ) : null}
      </Dialog>

      {/* Диалог просмотра чанка (клик по чанку в результатах одиночного поиска) */}
      <Dialog
        wide
        open={selectedChunk !== null}
        onClose={() => setSelectedChunk(null)}
        title={selectedChunk ? selectedChunk.title || selectedChunk.source : ""}
        description={selectedChunk ? selectedChunk.chunk_id : undefined}
      >
        {selectedChunk ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3">
              <InfoCell label={t("exp.chunk.source", "Файл")} value={selectedChunk.source} />
              <InfoCell label={t("exp.chunk.document", "Документ")} value={selectedChunk.document_id} mono />
              <InfoCell label={t("exp.chunk.section", "Раздел")} value={selectedChunk.section ?? "—"} />
              <InfoCell label={t("exp.chunk.strategy", "Стратегия")} value={String(selectedChunk.chunking_strategy ?? "—")} />
              <InfoCell
                label={t("exp.chunk.offsets", "Смещения")}
                value={`${selectedChunk.start_offset}–${selectedChunk.end_offset}`}
                mono
              />
              <InfoCell
                label={t("exp.chunk.pages", "Страницы")}
                value={
                  selectedChunk.page_start && selectedChunk.page_end
                    ? `${selectedChunk.page_start}–${selectedChunk.page_end}`
                    : "—"
                }
                mono
              />
              <InfoCell label={t("exp.chunk.chars", "Символы")} value={String(selectedChunk.char_count)} mono />
              <InfoCell
                label={t("exp.chunk.similarity", "Similarity")}
                value={selectedChunk.retrieval_score.toFixed(3)}
                title={t("exp.chunk.similarity_tip", "Близость embedding'ов query и чанка")}
                mono
              />
              <InfoCell
                label={t("exp.chunk.reranker", "Reranker score")}
                value={selectedChunk.reranker_score !== null ? selectedChunk.reranker_score.toFixed(3) : "—"}
                title={t("exp.chunk.reranker_tip", "Релевантность пары query+chunk отдельной моделью — не сопоставима напрямую с similarity")}
                mono
              />
              <InfoCell
                label={t("exp.chunk.ranks", "Ранги (FAISS/реранкер/final)")}
                value={`${selectedChunk.retrieval_rank} / ${selectedChunk.reranker_rank ?? "—"} / ${selectedChunk.final_rank ?? "—"}`}
                mono
              />
              <InfoCell
                label={t("exp.chunk.status", "Статус")}
                value={
                  <Badge variant={selectedChunk.status === "kept" ? "success" : "outline"}>
                    {CHUNK_STATUS_LABELS[selectedChunk.status]}
                  </Badge>
                }
              />
            </div>
            <div>
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium text-muted-foreground">
                  {t("exp.chunk.text", "Текст чанка")}
                </p>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => void copyToClipboard(selectedChunk.text).then((ok) =>
                    toast[ok ? "success" : "error"](
                      ok ? t("exp.chunk.copied", "Текст скопирован") : t("exp.chunk.copy_failed", "Не удалось скопировать"),
                    ),
                  )}
                >
                  <Copy className="h-3.5 w-3.5" />
                  {t("exp.chunk.copy", "Копировать")}
                </Button>
              </div>
              <pre className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-secondary DEFAULT/20 px-3 py-2 text-xs">
                {selectedChunk.text}
              </pre>
            </div>
          </div>
        ) : null}
      </Dialog>

      {/* Диалог открытого эксперимента */}
      <Dialog
        wide
        open={openExperiment !== null}
        onClose={() => setOpenExperiment(null)}
        title={openExperiment?.name ?? t("exp.experiment_title", "Эксперимент")}
        description={openExperiment ? `${openExperiment.id} · ${formatDate(openExperiment.created_at)}` : undefined}
      >
        {openExperimentLoading ? (
          <Spinner label={t("exp.experiment_loading", "Загрузка эксперимента…")} />
        ) : openExperiment ? (
          <ExperimentColumn exp={openExperiment} />
        ) : null}
      </Dialog>

      {/* Диалог сравнения экспериментов */}
      <Dialog
        wide
        open={compareData !== null}
        onClose={() => setCompareData(null)}
        title={t("exp.compare_title", "Сравнение экспериментов")}
        description={compareData?.note}
      >
        {compareData ? (
          <div className="grid gap-4 lg:grid-cols-2">
            <ExperimentColumn exp={compareData.current} />
            <ExperimentColumn exp={compareData.compared} />
          </div>
        ) : null}
      </Dialog>
    </div>
  );
}
