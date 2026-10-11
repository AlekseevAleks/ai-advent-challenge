/** Страница «Reranking & Filtering»: полный RAG-pipeline
 * (query rewrite → FAISS retrieval → similarity filter → reranker → final top-k)
 * с визуализацией этапов, таблицей кандидатов и сохранением/экспортом экспериментов.
 */

import { Fragment, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowDown,
  ArrowDownUp,
  ArrowRight,
  ArrowUp,
  CheckCircle2,
  ChevronDown,
  Copy,
  FileJson,
  FileSpreadsheet,
  Filter,
  Layers,
  Save,
  Search,
  SlidersHorizontal,
  Sparkles,
  TextCursorInput,
  TriangleAlert,
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
  Input,
  Progress,
  Select,
  Slider,
  Spinner,
  Textarea,
  ToggleSwitch,
} from "../components/ui";
import { useToast } from "../components/ui/toast";
import { clamp, formatMs } from "../lib/utils";
import {
  ApiError,
  getSettings,
  listCollections,
  ragRerankersStatus,
  ragSearch,
  saveExperiment,
} from "../services/api";
import type {
  AppSettings,
  ChunkFinalStatus,
  Collection,
  ExperimentItem,
  RagChunk,
  RagSearchResult,
  RerankerKind,
  RerankersStatusResponse,
  RetrievalConfigFields,
  Strategy,
} from "../types/api";

/** Базовый URL API (совпадает с services/api.ts). */
const API_BASE = (import.meta.env?.VITE_API_BASE as string | undefined) || "/api";

/** Варианты Badge (совпадают с components/ui). */
type BadgeVariant = "default" | "secondary" | "success" | "warning" | "error" | "outline";

/** Идентификаторы этапов визуального pipeline. */
type StageId = "query" | "rewrite" | "retrieval" | "filter" | "reranker" | "final";

interface StageDef {
  id: StageId;
  label: string;
  icon: ReactNode;
  summary: ReactNode;
}

/** Русская подпись стратегии чанкинга. */
function strategyLabel(s: Strategy): string {
  if (s === "fixed_size") return t("rr.strategy.fixed_size", "Фиксированный размер");
  return t("rr.strategy.structural", "Структурная");
}

/** Нормализация значения reranker из настроек (может быть любой строкой). */
function asRerankerKind(v: string): RerankerKind {
  if (v === "cross_encoder" || v === "similarity") return v;
  return "heuristic";
}

/** Извлечение detail из ошибки API (ApiError / Error / неизвестное). */
function apiDetail(err: unknown): string {
  if (err instanceof ApiError) {
    return err.status
      ? `${t("rr.http_error", "Ошибка")} ${err.status}: ${err.message}`
      : err.message;
  }
  if (err instanceof Error) return err.message;
  return t("rr.unknown_error", "Неизвестная ошибка");
}

/** Копирование в буфер обмена: navigator.clipboard с fallback на document.execCommand. */
async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback для небезопасного контекста / старых браузеров.
  }
  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(textarea);
    return ok;
  } catch {
    return false;
  }
}

/** Badge финального статуса кандидата. */
function statusInfo(status: ChunkFinalStatus): { variant: BadgeVariant; label: string; icon: ReactNode } {
  switch (status) {
    case "kept":
      return { variant: "success", label: t("rr.status.kept", "В финале"), icon: <CheckCircle2 className="h-3 w-3" /> };
    case "filtered":
      return {
        variant: "secondary",
        label: t("rr.status.filtered", "Отфильтрован (score < threshold)"),
        icon: <XCircle className="h-3 w-3" />,
      };
    case "deduplicated":
      return { variant: "warning", label: t("rr.status.deduplicated", "Дубликат"), icon: <XCircle className="h-3 w-3" /> };
    case "mmr_removed":
      return { variant: "secondary", label: t("rr.status.mmr", "MMR"), icon: <XCircle className="h-3 w-3" /> };
    case "outside_final_top_k":
      return {
        variant: "outline",
        label: t("rr.status.outside", "Вне Top-K"),
        icon: <ArrowRight className="h-3 w-3" />,
      };
  }
}

/** Сравнение retrieval_rank и reranker_rank: реальная дельта определяет движение. */
function movementInfo(item: RagChunk): { icon: ReactNode; label: string; variant: BadgeVariant } | null {
  if (item.reranker_rank === null) return null;
  const delta = item.reranker_rank - item.retrieval_rank;
  if (delta < 0) {
    return {
      icon: <ArrowUp className="h-3 w-3" />,
      label: `${t("rr.movement.up", "поднялся")} на ${-delta}`,
      variant: "success",
    };
  }
  if (delta > 0) {
    return {
      icon: <ArrowDown className="h-3 w-3" />,
      label: `${t("rr.movement.down", "опустился")} на ${delta}`,
      variant: "warning",
    };
  }
  return { icon: <ArrowRight className="h-3 w-3" />, label: t("rr.movement.same", "без изменений"), variant: "outline" };
}

/** Стрелка движения ранга для блока Rank Movement. */
function rankArrow(item: RagChunk): { icon: ReactNode; className: string; title: string } {
  const delta = item.reranker_rank! - item.retrieval_rank;
  if (delta < 0) {
    return { icon: <ArrowUp className="h-3.5 w-3.5" />, className: "text-emerald-500", title: t("rr.rank.up_title", "Улучшился") };
  }
  if (delta > 0) {
    return { icon: <ArrowDown className="h-3.5 w-3.5" />, className: "text-amber-500", title: t("rr.rank.down_title", "Ухудшился") };
  }
  return { icon: <ArrowRight className="h-3.5 w-3.5" />, className: "text-muted-foreground", title: t("rr.rank.same_title", "Без изменений") };
}

/** Русские подписи статусов чанка для диалога просмотра. */
const CHUNK_STATUS_LABELS: Record<ChunkFinalStatus, string> = {
  kept: t("rr.status.kept", "В финале"),
  filtered: t("rr.status.filtered", "Отфильтрован"),
  deduplicated: t("rr.status.deduplicated", "Дубликат"),
  mmr_removed: t("rr.status.mmr", "Исключён MMR"),
  outside_final_top_k: t("rr.status.outside", "Вне Top-K"),
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

/** Строка-чип с одним кандидатом для раскрытого этапа pipeline. */
function ChunkRow({ item, leading, right, sub, onClick }: {
  item: RagChunk;
  leading?: ReactNode;
  right?: ReactNode;
  sub?: ReactNode;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 rounded-md border border-border bg-card px-3 py-1.5 text-left text-xs transition-colors ${
        onClick ? "cursor-pointer hover:bg-accent DEFAULT/45 hover:text-accent-foreground" : "cursor-default"
      }`}
    >
      <span className="w-6 shrink-0 text-right font-mono tabular-nums text-muted-foreground">{leading ?? item.retrieval_rank}</span>
      <div className="min-w-0 flex-1 truncate" title={item.source}>
        {item.source}
        {sub ? <span className="block truncate text-[10px] text-muted-foreground">{sub}</span> : null}
      </div>
      {item.section ? <Badge variant="outline" className="shrink-0">{item.section}</Badge> : null}
      {right ? <span className="shrink-0 font-mono tabular-nums">{right}</span> : null}
    </button>
  );
}

/** Содержимое раскрытого этапа pipeline. */
function StageBody({ stage, result, onChunkClick }: {
  stage: StageId;
  result: RagSearchResult;
  onChunkClick: (it: RagChunk) => void;
}) {
  switch (stage) {
    case "query":
      return (
        <div className="space-y-2">
          <p className="text-sm font-medium">{t("rr.stage.original_query", "Исходный запрос")}</p>
          <p className="whitespace-pre-wrap rounded-md border border-border bg-card px-3 py-2 text-sm">{result.original_query}</p>
          {result.rewrite.enabled && result.rewritten_query ? (
            <>
              <p className="text-sm font-medium">{t("rr.stage.rewritten_query", "Переписанный запрос")}</p>
              <p className="whitespace-pre-wrap rounded-md border border-border bg-card px-3 py-2 text-sm">{result.rewritten_query}</p>
            </>
          ) : null}
        </div>
      );
    case "rewrite":
      return (
        <div className="space-y-2">
          <div>
            <p className="text-xs text-muted-foreground">{t("rr.stage.rewrite_original", "Original:")}</p>
            <p className="whitespace-pre-wrap text-sm">{result.original_query}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">{t("rr.stage.rewrite_result", "Rewritten:")}</p>
            <p className="whitespace-pre-wrap text-sm">{result.rewritten_query ?? "—"}</p>
          </div>
          <p className="font-mono text-xs text-muted-foreground">
            {result.rewrite.model ?? "—"} · {formatMs(result.rewrite.latency_ms)}
          </p>
        </div>
      );
    case "retrieval":
      return (
        <div className="space-y-1">
          {result.items.map((it) => (
            <ChunkRow
              key={it.chunk_id}
              item={it}
              sub={it.chunk_id}
              right={it.retrieval_score.toFixed(3)}
              onClick={() => onChunkClick(it)}
            />
          ))}
          {result.items.length === 0 ? (
            <p className="text-xs text-muted-foreground">{t("rr.stage.empty", "Нет данных")}</p>
          ) : null}
        </div>
      );
    case "filter":
      return (
        <div className="space-y-1.5">
          <p className="text-xs text-muted-foreground">
            {t("rr.stage.filter_rule", "Правило")}: score ≥ {result.filtering.threshold.toFixed(3)} →
            {t("rr.stage.filter_kept", "оставлен")}; score &lt; {result.filtering.threshold.toFixed(3)} →
            {t("rr.stage.filter_dropped", "отброшен")}
          </p>
          <div className="space-y-1">
            {result.items.map((it) => (
              <ChunkRow
                key={it.chunk_id}
                item={it}
                leading={
                  it.passed_filter ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5 text-red-500" />
                  )
                }
                right={it.retrieval_score.toFixed(3)}
                sub={`${it.passed_filter ? t("rr.stage.passed", "прошёл") : t("rr.stage.filtered_out", "отфильтрован")} · ${it.chunk_id}`}
                onClick={() => onChunkClick(it)}
              />
            ))}
          </div>
        </div>
      );
    case "reranker": {
      const reranked = result.items
        .filter((it) => it.reranker_rank !== null)
        .sort((a, b) => (a.reranker_rank ?? 0) - (b.reranker_rank ?? 0));
      return (
        <div className="space-y-1">
          {reranked.map((it) => (
            <ChunkRow
              key={it.chunk_id}
              item={it}
              leading={`${it.reranker_rank}.`}
              right={`${it.reranker_score !== null ? it.reranker_score.toFixed(3) : "—"} · FAISS ${it.retrieval_rank}`}
              sub={it.chunk_id}
              onClick={() => onChunkClick(it)}
            />
          ))}
          {reranked.length === 0 ? (
            <p className="text-xs text-muted-foreground">{t("rr.stage.empty", "Нет данных")}</p>
          ) : null}
        </div>
      );
    }
    case "final":
      return (
        <div className="space-y-1">
          {result.final.results
            .slice()
            .sort((a, b) => (a.final_rank ?? 0) - (b.final_rank ?? 0))
            .map((it) => (
              <ChunkRow
                key={it.chunk_id}
                item={it}
                leading={`${it.final_rank}.`}
                right={it.reranker_score !== null ? it.reranker_score.toFixed(3) : it.retrieval_score.toFixed(3)}
                sub={clamp(it.text, 140)}
                onClick={() => onChunkClick(it)}
              />
            ))}
          {result.final.results.length === 0 ? (
            <p className="text-xs text-muted-foreground">{t("rr.stage.empty", "Нет данных")}</p>
          ) : null}
        </div>
      );
  }
}

export function RerankingPage() {
  const toast = useToast();

  // --- Коллекции и выбор ---
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionsLoading, setCollectionsLoading] = useState(true);
  const [collectionsError, setCollectionsError] = useState<string | null>(null);
  const [collectionId, setCollectionId] = useState("");
  const [strategy, setStrategy] = useState<Strategy>("structural");

  // --- Запрос ---
  const [query, setQuery] = useState("");

  // --- Настройки pipeline ---
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [qrEnabled, setQrEnabled] = useState(false);
  const [qrModel, setQrModel] = useState("");
  const [initialTopK, setInitialTopK] = useState(20);
  const [finalTopK, setFinalTopK] = useState(5);
  const [filterEnabled, setFilterEnabled] = useState(true);
  const [filterThreshold, setFilterThreshold] = useState(0.65);
  const [rerankEnabled, setRerankEnabled] = useState(true);
  const [reranker, setReranker] = useState<RerankerKind>("heuristic");
  const [rerankerModel, setRerankerModel] = useState("");
  const [dedupEnabled, setDedupEnabled] = useState(false);
  const [mmrEnabled, setMmrEnabled] = useState(false);
  const [mmrLambda, setMmrLambda] = useState(0.7);

  const [rerankersStatus, setRerankersStatus] = useState<RerankersStatusResponse | null>(null);
  const [rerankersStatusError, setRerankersStatusError] = useState<string | null>(null);

  // --- Поиск и результат ---
  const [searching, setSearching] = useState(false);
  const [result, setResult] = useState<RagSearchResult | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [activeStage, setActiveStage] = useState<StageId | null>(null);
  /** Чанк, выбранный в списке pipeline (для просмотра текста и метаданных). */
  const [selectedChunk, setSelectedChunk] = useState<RagChunk | null>(null);

  // --- Сохранение / экспорт эксперимента ---
  const [saveOpen, setSaveOpen] = useState(false);
  const [expName, setExpName] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedExperiment, setSavedExperiment] = useState<ExperimentItem | null>(null);

  // Загрузка коллекций.
  useEffect(() => {
    let cancelled = false;
    setCollectionsLoading(true);
    listCollections()
      .then((cols) => {
        if (cancelled) return;
        setCollections(cols);
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

  // Дефолтные значения из настроек backend.
  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((s) => {
        if (cancelled) return;
        setSettings(s);
        setQrModel(s.backend.query_rewrite_model);
        setInitialTopK(s.backend.default_initial_top_k);
        setFinalTopK(s.backend.default_final_top_k);
        setFilterThreshold(s.backend.default_similarity_threshold);
        setReranker(asRerankerKind(s.backend.reranker_type));
        setRerankerModel(s.backend.reranker_model);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        toast.error(t("rr.settings.load_error", "Не удалось загрузить настройки"), apiDetail(err));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- только при монтировании
  }, []);

  // Статусы реранкеров.
  useEffect(() => {
    let cancelled = false;
    ragRerankersStatus()
      .then((st) => {
        if (cancelled) return;
        setRerankersStatus(st);
        setRerankersStatusError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setRerankersStatusError(apiDetail(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedCollection = collections.find((c) => c.id === collectionId);

  function handleCollectionChange(value: string) {
    setCollectionId(value);
    setResult(null);
    setSearchError(null);
    setActiveStage(null);
    const col = collections.find((c) => c.id === value);
    if (col) {
      setStrategy(col.strategies.includes("structural") ? "structural" : (col.strategies[0] ?? "structural"));
    } else {
      setStrategy("structural");
    }
  }

  /** Текущая конфигурация pipeline из UI-состояния. */
  function buildConfig(): RetrievalConfigFields {
    return {
      query_rewrite: qrEnabled,
      query_rewrite_model: qrModel.trim() || undefined,
      initial_top_k: initialTopK,
      final_top_k: finalTopK,
      enable_filter: filterEnabled,
      similarity_threshold: filterThreshold,
      enable_reranker: rerankEnabled,
      reranker,
      reranker_model: reranker === "cross_encoder" && rerankerModel.trim() ? rerankerModel.trim() : undefined,
      deduplicate: dedupEnabled,
      dedup_threshold: 0.97,
      mmr: mmrEnabled,
      mmr_lambda: mmrLambda,
    };
  }

  async function handleSearch() {
    if (!collectionId) {
      toast.error(
        t("rr.validation", "Форма не заполнена"),
        t("rr.need_collection", "Выберите коллекцию."),
      );
      return;
    }
    if (!query.trim()) {
      toast.error(
        t("rr.validation", "Форма не заполнена"),
        t("rr.need_query", "Введите текст запроса."),
      );
      return;
    }
    if (initialTopK < finalTopK) {
      toast.error(
        t("rr.validation", "Ошибка конфигурации"),
        t("rr.topk_invalid", "Initial Top-K должен быть не меньше Final Top-K."),
      );
      return;
    }
    setSearching(true);
    setSearchError(null);
    setActiveStage(null);
    try {
      const res = await ragSearch(collectionId, strategy, query.trim(), buildConfig());
      setResult(res);
      setRerankersStatusError(null);
    } catch (err: unknown) {
      setResult(null);
      setSearchError(apiDetail(err));
    } finally {
      setSearching(false);
    }
  }

  async function handleCopyContext() {
    if (!result) return;
    const text = result.final.results
      .map((chunk, i) => `[${i + 1}] source: ${chunk.source} section: ${chunk.section ?? ""}\n\n${chunk.text}`)
      .join("\n\n");
    const ok = await copyToClipboard(text);
    if (ok) {
      toast.success(t("rr.copied", "Контекст скопирован"));
    } else {
      toast.error(t("rr.copy_failed", "Не удалось скопировать"));
    }
  }

  async function handleSaveExperiment() {
    if (!result) return;
    const name = expName.trim();
    if (!name) {
      toast.error(t("rr.save.no_name", "Укажите название"), t("rr.save.no_name_hint", "Эксперимент не сохранён."));
      return;
    }
    setSaving(true);
    try {
      const saved = await saveExperiment({
        name,
        query: result.original_query,
        config: result.config,
        collection_id: result.retrieval.collection_id,
        strategy: result.retrieval.strategy,
        result,
      });
      setSavedExperiment(saved);
      setSaveOpen(false);
      setExpName("");
      toast.success(t("rr.save.ok", "Эксперимент сохранён"), saved.id);
    } catch (err: unknown) {
      toast.error(t("rr.save.fail", "Не удалось сохранить эксперимент"), apiDetail(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleExport(format: "json" | "csv") {
    if (!savedExperiment) return;
    try {
      const resp = await fetch(`${API_BASE}/experiments/${savedExperiment.id}/export?format=${format}`);
      if (!resp.ok) {
        let detail = `${t("rr.http_error", "Ошибка")} HTTP ${resp.status}`;
        try {
          const data = (await resp.json()) as { detail?: unknown } | null;
          if (typeof data?.detail === "string") detail = data.detail;
        } catch {
          // Ответ не JSON — оставляем текст статуса.
        }
        throw new Error(detail);
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `experiment-${savedExperiment.id}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(t("rr.export_ok", "Файл экспортирован"));
    } catch (err: unknown) {
      toast.error(t("rr.export_fail", "Не удалось экспортировать"), apiDetail(err));
    }
  }

  /** Этапы визуального pipeline из реального результата. */
  const stages = useMemo<StageDef[]>(() => {
    if (!result) return [];
    const list: StageDef[] = [];
    list.push({
      id: "query",
      label: t("rr.pipeline.query", "QUERY"),
      icon: <TextCursorInput className="h-4 w-4" />,
      summary: clamp(result.original_query, 96),
    });
    if (result.rewrite.enabled) {
      list.push({
        id: "rewrite",
        label: t("rr.pipeline.rewrite", "QUERY REWRITE"),
        icon: <Sparkles className="h-4 w-4" />,
        summary: result.rewritten_query ? clamp(result.rewritten_query, 96) : (result.rewrite.model ?? "—"),
      });
    }
    list.push({
      id: "retrieval",
      label: t("rr.pipeline.retrieval", "FAISS RETRIEVAL"),
      icon: <Layers className="h-4 w-4" />,
      summary: `${result.retrieval.candidates} ${t("rr.stage.candidates", "кандидатов")} (initial_top_k=${result.retrieval.initial_top_k})`,
    });
    list.push({
      id: "filter",
      label: t("rr.pipeline.filter", "SIMILARITY FILTER"),
      icon: <Filter className="h-4 w-4" />,
      summary: result.filtering.enabled
        ? `${result.filtering.passed} ${t("rr.stage.passed", "прошло")} / ${result.filtering.filtered} ${t("rr.stage.filtered_count", "отфильтровано")}`
        : t("rr.stage.disabled", "выключен"),
    });
    list.push({
      id: "reranker",
      label: t("rr.pipeline.reranker", "RERANKER"),
      icon: <ArrowDownUp className="h-4 w-4" />,
      summary: result.reranking.enabled
        ? `${result.reranking.n_reranked} → ${t("rr.stage.reordered", "переупорядочено")}`
        : t("rr.stage.disabled", "выключен"),
    });
    list.push({
      id: "final",
      label: t("rr.pipeline.final", "FINAL TOP-K"),
      icon: <CheckCircle2 className="h-4 w-4" />,
      summary: `${result.final.count} / ${result.final.top_k} ${t("rr.stage.chunks", "чанков")}`,
    });
    return list;
  }, [result]);

  /** Строки латентности из result.latency. */
  const latencyRows = useMemo(() => {
    if (!result) return [];
    return [
      { key: "query_rewrite_ms", label: t("rr.latency.rewrite", "Query rewrite"), ms: result.latency.query_rewrite_ms },
      { key: "embedding_ms", label: t("rr.latency.embedding", "Embedding запроса"), ms: result.latency.embedding_ms },
      { key: "retrieval_ms", label: t("rr.latency.retrieval", "FAISS retrieval"), ms: result.latency.retrieval_ms },
      { key: "filtering_ms", label: t("rr.latency.filter", "Similarity filter"), ms: result.latency.filtering_ms },
      { key: "reranking_ms", label: t("rr.latency.reranking", "Reranking"), ms: result.latency.reranking_ms },
      { key: "deduplication_ms", label: t("rr.latency.dedup", "Deduplication"), ms: result.latency.deduplication_ms },
      { key: "mmr_ms", label: t("rr.latency.mmr", "MMR"), ms: result.latency.mmr_ms },
    ];
  }, [result]);

  return (
    <div className="space-y-6">
      {/* ------------------------------------------------------------------ */}
      {/* Верхняя панель: коллекция, стратегия, запрос */}
      {/* ------------------------------------------------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle>{t("rr.title", "Reranking & Filtering")}</CardTitle>
          <CardDescription>
            {t("rr.description", "Полный RAG-pipeline: query rewrite → retrieval → filtering → reranking")}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {collectionsError ? (
            <Alert variant="error">
              {t("rr.collections_error", "Не удалось загрузить коллекции")}: {collectionsError}
            </Alert>
          ) : null}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Select
              label={t("rr.collection", "Коллекция")}
              value={collectionId}
              disabled={collectionsLoading}
              onChange={(e) => handleCollectionChange(e.target.value)}
              hint={
                collectionsLoading
                  ? t("rr.collections_loading", "Загрузка коллекций…")
                  : selectedCollection
                    ? `${t("rr.collection_indexes", "Индексов")}: ${selectedCollection.indexes.length}`
                    : undefined
              }
            >
              <option value="">{t("rr.collection_placeholder", "Выберите коллекцию")}</option>
              {collections.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} — {c.strategies.map((s) => strategyLabel(s)).join(" / ")}
                </option>
              ))}
            </Select>
            <Select
              label={t("rr.strategy", "Стратегия")}
              value={strategy}
              disabled={!selectedCollection}
              onChange={(e) => setStrategy(e.target.value as Strategy)}
              hint={!selectedCollection ? t("rr.strategy_needs_collection", "Сначала выберите коллекцию") : undefined}
            >
              {selectedCollection
                ? selectedCollection.strategies.map((s) => (
                    <option key={s} value={s}>
                      {strategyLabel(s)}
                    </option>
                  ))
                : null}
            </Select>
          </div>
          <Textarea
            label={t("rr.query", "Запрос")}
            rows={3}
            value={query}
            placeholder={t("rr.query_placeholder", "Например: что такое структурное чанкирование и зачем оно нужно?")}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="flex items-center justify-between gap-3">
            <Button onClick={() => void handleSearch()} loading={searching}>
              <Search className="h-4 w-4" />
              {t("rr.search", "Найти")}
            </Button>
            {searching ? <Spinner label={t("rr.searching", "Поиск…")} /> : null}
          </div>
        </CardContent>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Настройки */}
      {/* ------------------------------------------------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4" />
            {t("rr.settings.title", "Настройки")}
          </CardTitle>
          <CardDescription>
            {t("rr.settings.description", "Конфигурация отправляется в /rag/search как есть")}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* Query Rewrite */}
          <div className="space-y-3 rounded-lg border border-border p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium">{t("rr.qr.title", "Query Rewrite")}</p>
                <p className="text-xs text-muted-foreground">{t("rr.qr.hint", "Переписывание запроса локальной LLM перед поиском")}</p>
              </div>
              <ToggleSwitch checked={qrEnabled} onChange={setQrEnabled} />
            </div>
            {qrEnabled ? (
              <Input
                label={t("rr.qr.model", "Модель")}
                value={qrModel}
                onChange={(e) => setQrModel(e.target.value)}
                placeholder={settings?.backend.query_rewrite_model ?? ""}
                hint={t("rr.qr.model_hint", "По умолчанию — query_rewrite_model из настроек")}
              />
            ) : null}
            {result ? (
              result.rewrite.enabled && result.rewritten_query ? (
                <div className="space-y-1.5 rounded-md bg-secondary DEFAULT/30 p-3 text-xs">
                  <p>
                    <span className="font-medium">{t("rr.qr.original", "Original:")} </span>
                    <span className="whitespace-pre-wrap">{result.original_query}</span>
                  </p>
                  <p>
                    <span className="font-medium">{t("rr.qr.rewritten", "Rewritten:")} </span>
                    <span className="whitespace-pre-wrap">{result.rewritten_query}</span>
                  </p>
                  <p className="font-mono text-muted-foreground">
                    {result.rewrite.model ?? "—"} · {formatMs(result.rewrite.latency_ms)}
                  </p>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">{t("rr.qr.disabled", "Query rewrite: disabled")}</p>
              )
            ) : null}
          </div>

          {/* Retrieval */}
          <div className="space-y-3 rounded-lg border border-border p-4">
            <p className="text-sm font-medium">{t("rr.retrieval.title", "Retrieval")}</p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Input
                type="number"
                min={1}
                max={500}
                label={t("rr.retrieval.initial_top_k", "Initial Top-K")}
                value={String(initialTopK)}
                onChange={(e) => setInitialTopK(Number(e.target.value))}
                hint={t("rr.retrieval.initial_hint", "Сколько кандидатов вернёт FAISS")}
              />
              <Input
                type="number"
                min={1}
                max={100}
                label={t("rr.retrieval.final_top_k", "Final Top-K")}
                value={String(finalTopK)}
                onChange={(e) => setFinalTopK(Number(e.target.value))}
                hint={t("rr.retrieval.final_hint", "Сколько чанков попадёт в финальный контекст (≤ Initial)")}
              />
            </div>
          </div>

          {/* Filtering */}
          <div className="space-y-3 rounded-lg border border-border p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium">{t("rr.filter.title", "Filtering по similarity")}</p>
                <p className="text-xs text-muted-foreground">{t("rr.filter.hint_title", "Отсеивает кандидатов ниже порога")}</p>
              </div>
              <ToggleSwitch checked={filterEnabled} onChange={setFilterEnabled} />
            </div>
            {filterEnabled ? (
              <Slider
                label={t("rr.filter.threshold", "Порог similarity")}
                value={filterThreshold}
                min={0}
                max={1}
                step={0.01}
                onChange={setFilterThreshold}
                hint={t(
                  "rr.filter.hint",
                  "Higher threshold → fewer but potentially more relevant results; lower → more candidates but more noise",
                )}
              />
            ) : null}
          </div>

          {/* Reranking */}
          <div className="space-y-3 rounded-lg border border-border p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium">{t("rr.reranker.title", "Reranking")}</p>
                <p className="text-xs text-muted-foreground">{t("rr.reranker.hint_title", "Дополнительное переупорядочивание кандидатов")}</p>
              </div>
              <ToggleSwitch checked={rerankEnabled} onChange={setRerankEnabled} />
            </div>
            {rerankEnabled ? (
              <>
                <Select
                  label={t("rr.reranker.select", "Реранкер")}
                  value={reranker}
                  onChange={(e) => setReranker(e.target.value as RerankerKind)}
                >
                  <option value="heuristic">{t("rr.reranker.kind.heuristic", "Heuristic (по similarity)")}</option>
                  <option value="cross_encoder">{t("rr.reranker.kind.cross_encoder", "Cross-encoder")}</option>
                  <option value="similarity">{t("rr.reranker.kind.similarity", "Similarity (по FAISS score)")}</option>
                </Select>
                {reranker === "cross_encoder" ? (
                  <div className="space-y-2">
                    <Input
                      label={t("rr.reranker.model", "Модель")}
                      value={rerankerModel}
                      onChange={(e) => setRerankerModel(e.target.value)}
                      placeholder={rerankersStatus?.default_model ?? ""}
                      hint={t("rr.reranker.model_hint", "По умолчанию — reranker_model из настроек")}
                    />
                    {rerankersStatus ? (
                      rerankersStatus.cross_encoder.available ? (
                        <Badge variant="success">
                          <CheckCircle2 className="h-3 w-3" />
                          {t("rr.reranker.available", "Доступна")}
                        </Badge>
                      ) : (
                        <>
                          <Badge variant="error">
                            <XCircle className="h-3 w-3" />
                            {t("rr.reranker.unavailable", "Не установлена")}
                          </Badge>
                          <Alert variant="warning" icon={<TriangleAlert className="h-4 w-4" />}>
                            <div className="space-y-1">
                              {rerankersStatus.cross_encoder.reason ? <p>{rerankersStatus.cross_encoder.reason}</p> : null}
                              {rerankersStatus.cross_encoder.install_hint ? (
                                <p className="font-mono text-xs">{rerankersStatus.cross_encoder.install_hint}</p>
                              ) : null}
                            </div>
                          </Alert>
                        </>
                      )
                    ) : rerankersStatusError ? (
                      <Alert variant="warning" icon={<TriangleAlert className="h-4 w-4" />} className="text-xs">
                        {t("rr.reranker.status_error", "Не удалось получить статус реранкеров")}: {rerankersStatusError}
                      </Alert>
                    ) : (
                      <Spinner label={t("rr.reranker.status_loading", "Загрузка статуса…")} />
                    )}
                  </div>
                ) : null}
              </>
            ) : null}
            {/* Доступность реранкеров */}
            {rerankersStatus ? (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted-foreground">{t("rr.reranker.availability", "Доступность:")}</span>
                <Badge
                  variant={rerankersStatus.heuristic.available ? "success" : "error"}
                  title={rerankersStatus.heuristic.reason ?? undefined}
                >
                  Heuristic: {rerankersStatus.heuristic.available ? t("rr.reranker.status_ok", "доступен") : t("rr.reranker.status_no", "недоступен")}
                </Badge>
                <Badge
                  variant={rerankersStatus.cross_encoder.available ? "success" : "error"}
                  title={rerankersStatus.cross_encoder.reason ?? undefined}
                >
                  Cross-encoder: {rerankersStatus.cross_encoder.available ? t("rr.reranker.status_ok", "доступна") : t("rr.reranker.status_no", "не установлена")}
                </Badge>
                <Badge
                  variant={rerankersStatus.similarity.available ? "success" : "error"}
                  title={rerankersStatus.similarity.reason ?? undefined}
                >
                  Similarity: {rerankersStatus.similarity.available ? t("rr.reranker.status_ok", "доступен") : t("rr.reranker.status_no", "недоступен")}
                </Badge>
              </div>
            ) : rerankersStatusError ? (
              <p className="text-xs text-muted-foreground">
                {t("rr.reranker.status_error", "Не удалось получить статус реранкеров")}: {rerankersStatusError}
              </p>
            ) : (
              <Spinner label={t("rr.reranker.status_loading", "Загрузка статуса…")} />
            )}
          </div>

          {/* Дополнительно */}
          <div className="space-y-3 rounded-lg border border-border p-4">
            <p className="text-sm font-medium">{t("rr.extra.title", "Дополнительно")}</p>
            <div className="flex flex-wrap gap-x-8 gap-y-3">
              <ToggleSwitch
                checked={dedupEnabled}
                onChange={setDedupEnabled}
                label={t("rr.extra.dedup", "Удалять почти-дубликаты")}
                description={t("rr.extra.dedup_threshold", "порог 0.97")}
              />
              <ToggleSwitch
                checked={mmrEnabled}
                onChange={setMmrEnabled}
                label={t("rr.extra.mmr", "MMR")}
                description={t("rr.extra.mmr_default", "lambda 0.7")}
              />
            </div>
            {mmrEnabled ? (
              <Slider
                label={t("rr.extra.mmr_lambda", "MMR lambda")}
                value={mmrLambda}
                min={0}
                max={1}
                step={0.01}
                onChange={setMmrLambda}
                hint={t("rr.extra.mmr_hint", "λ → релевантность, 1−λ → разнообразие")}
              />
            ) : null}
          </div>
        </CardContent>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Состояния и результат */}
      {/* ------------------------------------------------------------------ */}
      {!result && !searchError && !searching ? (
        <Alert variant="info">
          {t("rr.hint", "Сформулируйте запрос, настройте pipeline и нажмите «Найти». Результаты — реальный ответ /rag/search, без мок-данных.")}
        </Alert>
      ) : null}

      {searching ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-6">
            <Spinner label={t("rr.searching", "Выполняется поиск…")} />
          </CardContent>
        </Card>
      ) : null}

      {searchError ? (
        <Alert variant="error" icon={<TriangleAlert className="h-4 w-4" />}>
          {searchError}
        </Alert>
      ) : null}

      {result && !searching ? (
        <div className="space-y-6">
          {result.note ? <Alert variant="info">{result.note}</Alert> : null}

          {/* Визуальный pipeline */}
          <Card>
            <CardHeader>
              <CardTitle>{t("rr.pipeline.title", "Pipeline")}</CardTitle>
              <CardDescription>{t("rr.pipeline.description", "Кликните по этапу, чтобы увидеть его результат, и по чанку — чтобы открыть его текст")}</CardDescription>
            </CardHeader>
            <CardContent>
              <div>
                {stages.map((stage, i) => (
                  <Fragment key={stage.id}>
                    <div>
                      <button
                        type="button"
                        onClick={() => setActiveStage(activeStage === stage.id ? null : stage.id)}
                        className="flex w-full items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 text-left transition-colors hover:bg-accent DEFAULT/40"
                      >
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--primary)/0.12)] text-primary">
                          {stage.icon}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-semibold">{stage.label}</span>
                          <span className="block truncate text-xs text-muted-foreground">{stage.summary}</span>
                        </span>
                        <ChevronDown
                          className={
                            activeStage === stage.id
                              ? "h-4 w-4 shrink-0 rotate-180 text-muted-foreground transition-transform"
                              : "h-4 w-4 shrink-0 text-muted-foreground transition-transform"
                          }
                        />
                      </button>
                      {activeStage === stage.id ? (
                        <div className="mt-2 rounded-lg border border-border/70 bg-secondary DEFAULT/20 p-3">
                          <StageBody stage={stage.id} result={result} onChunkClick={setSelectedChunk} />
                        </div>
                      ) : null}
                    </div>
                    {i < stages.length - 1 ? (
                      <div className="flex justify-center py-0.5 text-muted-foreground">
                        <ArrowDown className="h-4 w-4" />
                      </div>
                    ) : null}
                  </Fragment>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Таблица кандидатов */}
          <Card>
            <CardHeader>
              <CardTitle>{t("rr.table.title", "Кандидаты")}</CardTitle>
              <CardDescription>
                {result.items.length} {t("rr.table.count", "кандидатов")} · {t("rr.table.description", "все этапы pipeline видны в одной таблице")}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs text-muted-foreground">
                      <th className="whitespace-nowrap px-2 py-2 font-medium">{t("rr.table.rank", "Rank (retrieval)")}</th>
                      <th className="whitespace-nowrap px-2 py-2 font-medium">{t("rr.table.file", "File")}</th>
                      <th className="whitespace-nowrap px-2 py-2 font-medium">{t("rr.table.section", "Section")}</th>
                      <th className="whitespace-nowrap px-2 py-2 font-medium">{t("rr.table.similarity", "Similarity")}</th>
                      <th className="whitespace-nowrap px-2 py-2 font-medium">{t("rr.table.reranker", "Reranker")}</th>
                      <th className="whitespace-nowrap px-2 py-2 font-medium">{t("rr.table.final", "Final")}</th>
                      <th className="whitespace-nowrap px-2 py-2 font-medium">{t("rr.table.status", "Status")}</th>
                      <th className="whitespace-nowrap px-2 py-2 font-medium">{t("rr.table.movement", "Движение")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.items.map((item) => {
                      const st = statusInfo(item.status);
                      const mv = movementInfo(item);
                      return (
                        <tr key={item.chunk_id} className="border-b border-border/60 last:border-0 hover:bg-accent DEFAULT/30">
                          <td className="px-2 py-2 font-mono tabular-nums">{item.retrieval_rank}</td>
                          <td className="px-2 py-2">
                            <p className="max-w-[220px] truncate font-medium" title={item.source}>{item.source}</p>
                            <p className="max-w-[220px] truncate text-[11px] text-muted-foreground" title={item.title}>{item.title}</p>
                          </td>
                          <td className="max-w-[160px] truncate px-2 py-2">{item.section ?? "—"}</td>
                          <td className="px-2 py-2">
                            <span className="font-mono tabular-nums" title={t("rr.table.similarity_tip", "Similarity — близость embedding'ов query и чанка")}>
                              {item.retrieval_score.toFixed(3)}
                            </span>
                            <Progress value={item.retrieval_score * 100} className="mt-1 h-1 w-16" />
                          </td>
                          <td className="px-2 py-2">
                            {item.reranker_score !== null ? (
                              <span className="font-mono tabular-nums" title={t("rr.table.reranker_tip", "Reranker score — релевантность пары query+chunk отдельной моделью")}>
                                {item.reranker_score.toFixed(3)}
                              </span>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </td>
                          <td className="px-2 py-2 font-mono tabular-nums">{item.final_rank ?? "—"}</td>
                          <td className="px-2 py-2">
                            <Badge variant={st.variant}>
                              {st.icon}
                              {st.label}
                            </Badge>
                          </td>
                          <td className="px-2 py-2">
                            {mv ? (
                              <Badge variant={mv.variant} title={`retrieval_rank=${item.retrieval_rank} → reranker_rank=${item.reranker_rank}`}>
                                {mv.icon}
                                {mv.label}
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                    {result.items.length === 0 ? (
                      <tr>
                        <td colSpan={8} className="px-2 py-4 text-center text-xs text-muted-foreground">
                          {t("rr.stage.empty", "Нет данных")}
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {/* Rank Movement */}
          <Card>
            <CardHeader>
              <CardTitle>{t("rr.rank.title", "Rank Movement")}</CardTitle>
              <CardDescription>{t("rr.rank.description", "Сравнение позиций до и после реранкера")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1"><ArrowUp className="h-3 w-3 text-emerald-500" />{t("rr.rank.legend.up", "improved")}</span>
                <span className="inline-flex items-center gap-1"><ArrowDown className="h-3 w-3 text-amber-500" />{t("rr.rank.legend.down", "decreased")}</span>
                <span className="inline-flex items-center gap-1"><ArrowRight className="h-3 w-3" />{t("rr.rank.legend.same", "unchanged")}</span>
                <span className="inline-flex items-center gap-1"><XCircle className="h-3 w-3" />{t("rr.rank.legend.filtered", "filtered")}</span>
              </div>
              <div className="space-y-1">
                {result.items.map((item) => (
                  <div key={item.chunk_id} className="flex items-center gap-2 text-xs" title={item.source}>
                    {item.reranker_rank !== null ? (
                      <span className={`shrink-0 ${rankArrow(item).className}`}>{rankArrow(item).icon}</span>
                    ) : (
                      <XCircle className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    )}
                    <span className="min-w-0 flex-1 truncate font-mono">
                      {item.chunk_id}
                      {item.reranker_rank !== null ? (
                        <span className="text-muted-foreground">
                          {" "}— {t("rr.rank.faiss", "FAISS rank")} {item.retrieval_rank} → {t("rr.rank.reranker", "Reranker rank")} {item.reranker_rank}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">
                          {" "}— {t("rr.rank.faiss", "FAISS rank")} {item.retrieval_rank} → ✕ {t("rr.rank.filtered", "filtered")}
                        </span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Latency */}
          <Card>
            <CardHeader>
              <CardTitle>{t("rr.latency.title", "Latency")}</CardTitle>
              <CardDescription>{t("rr.latency.description", "Время каждого этапа и общее время запроса")}</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-1.5">
                {latencyRows.map((row) => (
                  <div key={row.key} className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">{row.label}</span>
                    <span className="font-mono tabular-nums">{formatMs(row.ms)}</span>
                  </div>
                ))}
                <div className="mt-2 flex items-center justify-between border-t border-border pt-2 text-sm font-semibold">
                  <span>{t("rr.latency.total", "Итого")}</span>
                  <span className="font-mono tabular-nums">{formatMs(result.latency.total_ms)}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Действия */}
          <Card>
            <CardHeader>
              <CardTitle>{t("rr.actions.title", "Действия с результатом")}</CardTitle>
              <CardDescription>{t("rr.actions.description", "Контекст, сохранение эксперимента и экспорт")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => void handleCopyContext()}>
                  <Copy className="h-4 w-4" />
                  {t("rr.actions.copy_context", "Скопировать контекст")}
                </Button>
                <Button onClick={() => { setExpName(""); setSaveOpen(true); }}>
                  <Save className="h-4 w-4" />
                  {t("rr.actions.save", "Сохранить эксперимент")}
                </Button>
                <Button
                  variant="outline"
                  disabled={!savedExperiment}
                  onClick={() => void handleExport("json")}
                  title={!savedExperiment ? t("rr.actions.need_save", "Сначала сохраните эксперимент") : undefined}
                >
                  <FileJson className="h-4 w-4" />
                  {t("rr.actions.export_json", "Экспорт JSON")}
                </Button>
                <Button
                  variant="outline"
                  disabled={!savedExperiment}
                  onClick={() => void handleExport("csv")}
                  title={!savedExperiment ? t("rr.actions.need_save", "Сначала сохраните эксперимент") : undefined}
                >
                  <FileSpreadsheet className="h-4 w-4" />
                  {t("rr.actions.export_csv", "Экспорт CSV")}
                </Button>
              </div>
              {savedExperiment ? (
                <p className="text-xs text-muted-foreground">
                  {t("rr.actions.saved_as", "Эксперимент")}: <span className="font-medium">{savedExperiment.name}</span>{" "}
                  <span className="font-mono">({savedExperiment.id})</span>
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  {t("rr.actions.export_hint", "Экспорт JSON/CSV доступен после сохранения эксперимента")}
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      ) : null}

      {/* ------------------------------------------------------------------ */}
      {/* Диалог сохранения эксперимента */}
      {/* ------------------------------------------------------------------ */}
      <Dialog
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        title={t("rr.save.title", "Сохранить эксперимент")}
        description={t("rr.save.description", "Сохраняются текущая конфигурация и результаты поиска")}
      >
        <div className="space-y-3">
          <Input
            label={t("rr.save.name", "Название")}
            value={expName}
            onChange={(e) => setExpName(e.target.value)}
            placeholder={t("rr.save.name_placeholder", "Например: cross-encoder + MMR 0.7")}
            hint={`${t("rr.save.query", "Запрос")}: ${result ? result.original_query : (query.trim() || "—")}`}
          />
          {result ? (
            <p className="text-xs text-muted-foreground">
              IP: {result.retrieval.initial_top_k}, FP: {result.final.top_k}, threshold: {result.filtering.threshold.toFixed(3)}, reranker: {result.reranking.reranker ?? "—"}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setSaveOpen(false)}>
              {t("rr.save.cancel", "Отмена")}
            </Button>
            <Button onClick={() => void handleSaveExperiment()} loading={saving}>
              <Save className="h-4 w-4" />
              {t("rr.save.submit", "Сохранить")}
            </Button>
          </div>
        </div>
      </Dialog>

      {/* ------------------------------------------------------------------ */}
      {/* Диалог просмотра чанка (клик по чанку в списке pipeline) */}
      {/* ------------------------------------------------------------------ */}
      <Dialog
        open={selectedChunk !== null}
        onClose={() => setSelectedChunk(null)}
        title={selectedChunk ? selectedChunk.title || selectedChunk.source : ""}
        description={selectedChunk ? selectedChunk.chunk_id : ""}
        wide
      >
        {selectedChunk ? (
          <div className="space-y-4">
            {/* Информация о чанке */}
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3">
              <InfoCell label={t("rr.chunk.source", "Файл")} value={selectedChunk.source} />
              <InfoCell label={t("rr.chunk.document", "Документ")} value={selectedChunk.document_id} mono />
              <InfoCell label={t("rr.chunk.section", "Раздел")} value={selectedChunk.section ?? "—"} />
              <InfoCell label={t("rr.chunk.strategy", "Стратегия")} value={String(selectedChunk.chunking_strategy ?? "—")} />
              <InfoCell
                label={t("rr.chunk.offsets", "Смещения")}
                value={`${selectedChunk.start_offset}–${selectedChunk.end_offset}`}
                mono
              />
              <InfoCell
                label={t("rr.chunk.pages", "Страницы")}
                value={
                  selectedChunk.page_start && selectedChunk.page_end
                    ? `${selectedChunk.page_start}–${selectedChunk.page_end}`
                    : "—"
                }
                mono
              />
              <InfoCell label={t("rr.chunk.chars", "Символы")} value={String(selectedChunk.char_count)} mono />
              <InfoCell
                label={t("rr.chunk.similarity", "Similarity")}
                value={selectedChunk.retrieval_score.toFixed(3)}
                title={t("rr.chunk.similarity_tip", "Близость embedding'ов query и чанка")}
                mono
              />
              <InfoCell
                label={t("rr.chunk.reranker", "Reranker score")}
                value={selectedChunk.reranker_score !== null ? selectedChunk.reranker_score.toFixed(3) : "—"}
                title={t("rr.chunk.reranker_tip", "Релевантность пары query+chunk отдельной моделью — не сопоставима напрямую с similarity")}
                mono
              />
              <InfoCell
                label={t("rr.chunk.ranks", "Ранги (FAISS/реранкер/final)")}
                value={`${selectedChunk.retrieval_rank} / ${selectedChunk.reranker_rank ?? "—"} / ${selectedChunk.final_rank ?? "—"}`}
                mono
              />
              <InfoCell
                label={t("rr.chunk.status", "Статус")}
                value={
                  <Badge variant={selectedChunk.status === "kept" ? "success" : "outline"}>
                    {CHUNK_STATUS_LABELS[selectedChunk.status]}
                  </Badge>
                }
              />
            </div>

            {/* Полный текст чанка */}
            <div>
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium text-muted-foreground">
                  {t("rr.chunk.text", "Текст чанка")}
                </p>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => void copyToClipboard(selectedChunk.text).then((ok) =>
                    toast[ok ? "success" : "error"](
                      ok ? t("rr.chunk.copied", "Текст скопирован") : t("rr.chunk.copy_failed", "Не удалось скопировать"),
                    ),
                  )}
                >
                  <Copy className="h-3.5 w-3.5" />
                  {t("rr.chunk.copy", "Копировать")}
                </Button>
              </div>
              <pre className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-secondary DEFAULT/20 px-3 py-2 text-xs">
                {selectedChunk.text}
              </pre>
            </div>
          </div>
        ) : null}
      </Dialog>
    </div>
  );
}