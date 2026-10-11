/** Страница «Индексация»: выбор документов, стратегии chunking, эмбеддинги, запуск и прогресс. */

import {
  BarChart3,
  CheckCircle2,
  CircleAlert,
  Copy,
  Database,
  FileText,
  Info,
  Play,
  Plus,
  RefreshCw,
  Server,
  Square,
  Trash2,
} from "lucide-react";
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { STRATEGY_LABELS } from "../services/api";
import {
  cancelJob,
  createIndexJob,
  getJob,
  getOllamaStatus,
  getSettings,
  listCollections,
  listDocuments,
  testOllama,
} from "../services/api";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Checkbox,
  Input,
  Kbd,
  Progress,
  Select,
  Spinner,
  ToggleSwitch,
} from "../components/ui";
import { useToast } from "../components/ui/toast";
import { t } from "../app/i18n";
import {
  formatBytes,
  formatDuration,
  formatNumber,
} from "../lib/utils";
import type {
  AppSettings,
  Collection,
  DocumentOut,
  JobProgress,
  OllamaTest,
  Strategy,
} from "../types/api";

const STAGE_ORDER = ["prepare", "extract", "chunking", "embeddings", "faiss", "metadata", "integrity", "done"];
const STAGE_LABELS_RU: Record<string, string> = {
  prepare: "Подготовка документов",
  extract: "Извлечение текста",
  chunking: "Chunking",
  embeddings: "Генерация эмбеддингов",
  faiss: "Построение FAISS",
  metadata: "Сохранение метаданных",
  integrity: "Проверка целостности",
  done: "Завершение",
};

const CODE_TYPES = ["py", "js", "jsx", "ts", "tsx", "c", "cpp", "java", "rb", "php", "go", "rs", "sql", "sh", "bash", "html", "css", "scss"];
const MD_TYPES = ["md", "mdx", "markdown", "rst"];
const PDF_TYPES = ["pdf"];

const TERMINAL = new Set(["completed", "completed_with_errors", "failed", "cancelled"]);

export function IndexingPage() {
  const toast = useToast();
  const [docs, setDocs] = useState<DocumentOut[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loadingData, setLoadingData] = useState(true);
  const [loadingErr, setLoadingErr] = useState<string | null>(null);

  // выбор документов
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showOnlyUnindexed, setShowOnlyUnindexed] = useState(false);

  // стратегии
  const [useFixed, setUseFixed] = useState(true);
  const [useStructural, setUseStructural] = useState(true);
  const [chunkSize, setChunkSize] = useState(1200);
  const [overlap, setOverlap] = useState(200);
  const [unit, setUnit] = useState<"chars" | "tokens">("chars");
  const [maxChunk, setMaxChunk] = useState(1500);
  const [minChunk, setMinChunk] = useState(200);
  const [mergeSmall, setMergeSmall] = useState(true);

  // эмбеддинги
  const [ollamaUrl, setOllamaUrl] = useState("");
  const [model, setModel] = useState("");
  const [batchSize, setBatchSize] = useState(32);
  const [retries, setRetries] = useState(3);
  const [ollamaStatus, setOllamaStatus] = useState<{ available: boolean; model_available: boolean | null; message: string } | null>(null);
  const [testResult, setTestResult] = useState<OllamaTest | null>(null);
  const [testing, setTesting] = useState(false);

  // режим
  const [mode, setMode] = useState<"new_collection" | "new_index" | "rebuild" | "add">("new_collection");
  const [collectionId, setCollectionId] = useState("");
  const [collectionName, setCollectionName] = useState("");

  // задание
  const [job, setJob] = useState<JobProgress | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  async function loadData() {
    try {
      const [d, c, s] = await Promise.all([listDocuments(), listCollections(), getSettings()]);
      setDocs(d);
      setCollections(c);
      setSettings(s);
      setChunkSize(s.backend.default_chunk_size);
      setOverlap(s.backend.default_chunk_overlap);
      setMaxChunk(s.backend.default_structural_max_chunk_size);
      setMinChunk(s.backend.default_structural_min_chunk_size);
      setOllamaUrl(s.backend.ollama_url);
      setModel(s.backend.embedding_model);
      setBatchSize(s.backend.embedding_batch_size);
      setRetries(s.backend.embedding_retries);
      if (c.length > 0) setCollectionId(c[0].id);
      setLoadingErr(null);
    } catch (e) {
      setLoadingErr(e instanceof Error ? e.message : "Ошибка загрузки данных");
    } finally {
      setLoadingData(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  useEffect(() => {
    if (!jobId) return;
    const timer = window.setInterval(async () => {
      try {
        const p = await getJob(jobId);
        setJob(p);
        if (TERMINAL.has(p.status)) {
          window.clearInterval(timer);
        }
      } catch {
        window.clearInterval(timer);
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [jobId]);

  // ------------------------------------------------------------------
  // Индексы, доступные для документов (для фильтра «ещё не проиндексировано»)
  // ------------------------------------------------------------------
  const strategyPresent: Record<Strategy, boolean> = { fixed_size: useFixed, structural: useStructural };
  const activeStrategies: Strategy[] = ([useFixed ? "fixed_size" : null, useStructural ? "structural" : null].filter(Boolean) as Strategy[]);
  const indexedDocIds = new Set<string>();
  for (const col of collections) {
    for (const idx of col.indexes) {
      if (activeStrategies.includes(idx.strategy)) {
        for (const did of idx.document_ids) indexedDocIds.add(did);
      }
    }
  }

  const visibleDocs = showOnlyUnindexed
    ? docs.filter((d) => !indexedDocIds.has(d.id))
    : docs;

  const selectedCount = () => visibleDocs.filter((d) => selected.has(d.id)).length;

  const toggleDoc = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const filterSelect = (pred: (d: DocumentOut) => boolean) => {
    const next = new Set(selected);
    for (const d of visibleDocs) {
      if (pred(d)) next.add(d.id);
      else next.delete(d.id);
    }
    setSelected(next);
  };

  const docType = (d: DocumentOut) => d.file_type.toLowerCase();

  // ------------------------------------------------------------------
  // Проверка Ollama
  // ------------------------------------------------------------------
  async function refreshOllamaStatus() {
    try {
      const s = await getOllamaStatus();
      setOllamaStatus({ available: s.available, model_available: s.model_available, message: s.message });
    } catch {
      setOllamaStatus({ available: false, model_available: null, message: "Ollama недоступен" });
    }
  }

  useEffect(() => {
    void refreshOllamaStatus();
  }, []);

  async function runTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await testOllama();
      setTestResult(r);
      if (r.ok) toast.success(t("indexing.connTestOk", "Подключение к Ollama работает"), t("indexing.dim", "Размерность эмбеддинга: {dim}").replace("{dim}", String(r.dimension)));
      else toast.warning(t("indexing.connTestWarn", "Проблема с подключением"), r.message);
    } catch (e) {
      toast.error(t("indexing.connTestFail", "Не удалось выполнить проверку"), e instanceof Error ? e.message : undefined);
    } finally {
      setTesting(false);
    }
  }

  async function copyPullCommand() {
    const cmd = `ollama pull ${model.trim() || "nomic-embed-text"}`;
    try {
      await navigator.clipboard.writeText(cmd);
    } catch {
      /* fallback ниже */
      const ta = document.createElement("textarea");
      ta.value = cmd;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    toast.success(t("indexing.copied", "Команда скопирована"), cmd);
  }

  // ------------------------------------------------------------------
  // Запуск
  // ------------------------------------------------------------------
  function validate(): string | null {
    if (activeStrategies.length === 0) {
      return t("indexing.needStrategy", "Выберите хотя бы одну стратегию chunking");
    }
    if (selectedCount() === 0) {
      return t("indexing.needDocs", "Выберите хотя бы один документ");
    }
    if (useFixed && overlap >= chunkSize) {
      return t("indexing.overlapErr", "Overlap должен быть меньше размера чанка");
    }
    if (useFixed && unit === "tokens") {
      return t("indexing.tokensHint", "Единица «токены» требует установленного tiktoken (pip install tiktoken). Если он не установлен, задание будет отклонено.");
    }
    if (useStructural && minChunk > maxChunk) {
      return t("indexing.minMaxErr", "Минимальный размер не может быть больше максимального");
    }
    if (mode === "new_collection" && !collectionName.trim()) {
      return t("indexing.needCollName", "Укажите название новой коллекции");
    }
    if (mode !== "new_collection" && !collectionId) {
      return t("indexing.needColl", "Выберите коллекцию");
    }
    if (mode === "new_index") {
      const col = collections.find((c) => c.id === collectionId);
      const exists = col?.indexes.some((i) => activeStrategies.includes(i.strategy));
      if (exists) {
        return t("indexing.indexExists", "Выбранная стратегия уже индексирована в этой коллекции. Используйте «Перестроить» или «Добавить документы».");
      }
    }
    if (mode === "rebuild" || mode === "add") {
      const col = collections.find((c) => c.id === collectionId);
      const missing = activeStrategies.filter((s) => !col?.indexes.some((i) => i.strategy === s));
      if (missing.length > 0) {
        return t("indexing.noIndexFor", "Для стратегии из списка нет существующего индекса: {list}").replace("{list}", missing.join(", "));
      }
    }
    return null;
  }

  async function launch() {
    const problem = validate();
    if (problem) {
      toast.error(t("indexing.validation", "Проверьте параметры"), problem);
      return;
    }
    setStarting(true);
    try {
      const payload = {
        document_ids: visibleDocs.filter((d) => selected.has(d.id)).map((d) => d.id),
        strategies: activeStrategies,
        mode,
        collection_id: mode === "new_collection" ? undefined : collectionId,
        collection_name: mode === "new_collection" ? collectionName.trim() : undefined,
        fixed_size: useFixed ? { chunk_size: chunkSize, overlap, unit } : undefined,
        structural: useStructural ? { max_chunk_size: maxChunk, min_chunk_size: minChunk, merge_small_sections: mergeSmall } : undefined,
        embedding_model: model.trim() || undefined,
        embedding_batch_size: batchSize,
      };
      const res = await createIndexJob(payload);
      setJobId(res.job_id);
      toast.info(t("indexing.started", "Задание поставлено в очередь"), res.job_id);
    } catch (e) {
      toast.error(t("indexing.startFail", "Не удалось запустить индексацию"), e instanceof Error ? e.message : undefined);
    } finally {
      setStarting(false);
    }
  }

  async function requestCancel() {
    if (!jobId) return;
    try {
      await cancelJob(jobId);
      toast.warning(t("indexing.cancelReq", "Отмена запрошена"), t("indexing.cancelHint", "Задание остановится между пакетами"));
    } catch (e) {
      toast.error(t("indexing.cancelFail", "Не удалось отменить задание"), e instanceof Error ? e.message : undefined);
    }
  }

  // ------------------------------------------------------------------
  // Прогресс задания
  // ------------------------------------------------------------------

  function renderJobActive(p: JobProgress) {
    const stageIdx = Math.max(0, STAGE_ORDER.indexOf(p.stage));
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("indexing.progressTitle", "Задание {id} выполняется").replace("{id}", p.job_id)}</CardTitle>
          <CardDescription>{p.message || p.stage_label}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <Progress value={p.percent} className="flex-1" />
            <span className="w-12 text-right text-sm font-semibold">{Math.round(p.percent)}%</span>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-3">
            <span className="text-muted-foreground">{t("indexing.stage", "Этап")}</span>
            <span className="font-medium col-span-2 md:col-span-2">{p.stage_label}</span>
            <span className="text-muted-foreground">{t("indexing.documents", "Документы")}</span>
            <span className="font-medium">{p.document_index} / {p.document_total}</span>
            <span className="text-muted-foreground">{t("indexing.currentDoc", "Текущий документ")}</span>
            <span className="font-medium truncate" title={p.current_document || ""}>{p.current_document || "—"}</span>
            <span className="text-muted-foreground">{t("indexing.chunks", "Чанки")}</span>
            <span className="font-medium">{formatNumber(p.chunks)}</span>
            <span className="text-muted-foreground">{t("indexing.embeddings", "Эмбеддинги")}</span>
            <span className="font-medium">{formatNumber(p.embeddings_done)}</span>
            <span className="text-muted-foreground">{t("indexing.errors", "Ошибки")}</span>
            <span className={p.errors > 0 ? "font-medium text-red-600 dark:text-red-400" : "font-medium"}>{p.errors}</span>
            <span className="text-muted-foreground">{t("indexing.elapsed", "Прошло")}</span>
            <span className="font-medium">{formatDuration(p.elapsed_seconds)}</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {STAGE_ORDER.map((s, i) => {
              const done = i < stageIdx || (p.status !== "running" && i <= stageIdx);
              const current = i === stageIdx && p.status === "running";
return (
                 <span key={s} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] ${current ? "bg-[hsl(var(--primary)/0.14)] text-foreground" : done ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "bg-secondary DEFAULT text-muted-foreground"}`}>
                   {done ? <CheckCircle2 className="h-3 w-3" /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
                   {STAGE_LABELS_RU[s]}
                 </span>
               );
            })}
          </div>
          {p.status === "running" ? (
            <div className="flex justify-end">
              <Button variant="destructive" size="sm" onClick={() => void requestCancel()}>
                <Square className="h-4 w-4" />
                {t("indexing.cancel", "Отменить задание")}
              </Button>
            </div>
          ) : (
            <Alert variant="warning" icon={<Info className="h-4 w-4" />}>
              {t("indexing.cancelPending", "Отмена выполняется до завершения текущей операции.")}
            </Alert>
          )}
        </CardContent>
      </Card>
    );
  }

  function renderJobResult(p: JobProgress) {
    const res = p.result;
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("indexing.doneTitle", "Задание {id} завершено").replace("{id}", p.job_id)}</CardTitle>
          <CardDescription>{p.message}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {p.status === "completed" || p.status === "completed_with_errors" ? (
            <Alert variant={p.status === "completed" ? "success" : "warning"} icon={<CheckCircle2 className="h-4 w-4" />}>
              {p.status === "completed"
                ? t("indexing.doneOk", "Индексация завершена успешно. Все чанки проиндексированы.")
                : t("indexing.donePartial", "Задание завершено с ошибками — часть данных могла быть пропущена. Список проблем см. в отчёте.")}
            </Alert>
          ) : (
            <Alert variant="error" icon={<CircleAlert className="h-4 w-4" />}>
              {t("indexing.doneFailed", "Задание не выполнено: {msg}").replace("{msg}", p.message || "")}
            </Alert>
          )}
          {res ? (
            <div>
              <p className="mb-2 text-sm font-medium">{t("indexing.createdIndexes", "Созданные индексы")}</p>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-2 py-1.5">{t("common.strategy", "Стратегия")}</th>
                    <th className="px-2 py-1.5">{t("indexing.vectors", "Векторов")}</th>
                    <th className="px-2 py-1.5">{t("indexing.docsIn", "Документов")}</th>
                    <th className="px-2 py-1.5">{t("indexing.size", "Размер")}</th>
                  </tr>
                </thead>
                <tbody>
                  {(res.indexes || []).map((ix) => (
                    <tr key={ix.index_id} className="border-b border-border/60">
                      <td className="px-2 py-1.5"><Badge variant="outline">{STRATEGY_LABELS[ix.strategy as Strategy]}</Badge></td>
                      <td className="px-2 py-1.5">{formatNumber(ix.num_vectors)}</td>
                      <td className="px-2 py-1.5">{formatNumber(ix.num_documents)}</td>
                      <td className="px-2 py-1.5 mono">{formatBytes(ix.size_bytes)}</td>
                    </tr>
                  ))}
                  {res.indexes && res.indexes.length === 0 ? (
                    <tr><td colSpan={4} className="px-2 py-2 text-muted-foreground">{t("indexing.noIndexes", "Индексы не созданы")}</td></tr>
                  ) : null}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-muted-foreground">
                {t("indexing.totalInfo", "Всего: {chunks} чанков, {emb} эмбеддингов, время {time}").replace("{chunks}", formatNumber(res.chunks)).replace("{emb}", formatNumber(res.embeddings_ok)).replace("{time}", formatDuration(res.time_total_ms ? res.time_total_ms / 1000 : 0))}
              </p>
            </div>
          ) : null}
          <div className="flex gap-2">
            <Link to="/comparison"><Button variant="outline" size="sm"><BarChart3 className="h-4 w-4" />{t("indexing.toComparison", "К сравнению")}</Button></Link>
            <Link to="/search"><Button variant="outline" size="sm">{t("indexing.toSearch", "К поиску")}</Button></Link>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setJob(null);
                setJobId(null);
                void loadData();
              }}
            >
              <RefreshCw className="h-4 w-4" />
              {t("indexing.newRun", "Новый запуск")}
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  // ------------------------------------------------------------------
  // Основной рендер
  // ------------------------------------------------------------------

  if (loadingData) return <Spinner label={t("indexing.loading", "Загрузка данных…")} className="py-10" />;
  if (loadingErr) {
    return (
      <Alert variant="error" icon={<CircleAlert className="h-4 w-4" />} className="my-6">
        <p className="font-medium">{t("indexing.loadErr", "Не удалось загрузить данные")}</p>
        <p className="mt-1">{loadingErr}</p>
        <Button variant="secondary" size="sm" className="mt-2" onClick={() => void loadData()}>
          <RefreshCw className="h-4 w-4" /> {t("common.retry", "Повторить")}
        </Button>
      </Alert>
    );
  }

  if (job && jobId && TERMINAL.has(job.status)) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-bold tracking-tight">{t("indexing.title", "Индексация")}</h1>
        {renderJobResult(job)}
      </div>
    );
  }

  if (job && jobId) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-bold tracking-tight">{t("indexing.title", "Индексация")}</h1>
        {renderJobActive(job)}
      </div>
    );
  }

  const isDocIndexed = (d: DocumentOut) => indexedDocIds.has(d.id);
  const col = collections.find((c) => c.id === collectionId);

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-bold tracking-tight">{t("indexing.title", "Индексация")}</h1>
      <p className="text-sm text-muted-foreground">
        {t("indexing.subtitle", "Выберите документы и стратегии chunking. Эмбеддинги создаются локально моделью {model} через Ollama.").replace("{model}", model || "nomic-embed-text")}
      </p>

      {/* A. Документы */}
      <Card>
        <CardHeader>
          <CardTitle>{t("indexing.docsTitle", "1. Выбор документов")}</CardTitle>
          <CardDescription>
            {t("indexing.docsSub", "Отмечено: {n} из {total}").replace("{n}", String(selectedCount())).replace("{total}", String(visibleDocs.length))}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="secondary" onClick={() => filterSelect(() => true)}>{t("indexing.selAll", "Выбрать все")}</Button>
            <Button size="sm" variant="secondary" onClick={() => filterSelect(() => false)}>{t("indexing.selNone", "Снять выделение")}</Button>
            <Button size="sm" variant="ghost" onClick={() => filterSelect((d) => PDF_TYPES.includes(docType(d)))}>{t("indexing.selPdf", "Только PDF")}</Button>
            <Button size="sm" variant="ghost" onClick={() => filterSelect((d) => CODE_TYPES.includes(docType(d)))}>{t("indexing.selCode", "Только код")}</Button>
            <Button size="sm" variant="ghost" onClick={() => filterSelect((d) => MD_TYPES.includes(docType(d)))}>{t("indexing.selMd", "Только Markdown")}</Button>
            <div className="ml-auto">
              <ToggleSwitch
                checked={showOnlyUnindexed}
                onChange={setShowOnlyUnindexed}
                label={t("indexing.onlyUnindexed", "Только не проиндексированные выбранной стратегией")}
              />
            </div>
          </div>
          {docs.length === 0 ? (
            <Alert variant="info" icon={<FileText className="h-4 w-4" />}>
              {t("indexing.noDocs", "Документов пока нет. Перейдите на страницу «Документы» и загрузите файлы.")}
              <Link to="/documents" className="ml-1 underline">{t("indexing.toDocs", "Перейти к загрузке")}</Link>
            </Alert>
          ) : visibleDocs.length === 0 ? (
            <Alert variant="info" icon={<CheckCircle2 className="h-4 w-4" />}>
              {t("indexing.allIndexed", "Все документы уже проиндексированы выбранными стратегиями (фильтр «только не проиндексированные» включён).")}
            </Alert>
          ) : null}
          <div className="max-h-72 overflow-y-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="w-8 px-3 py-2" />
                  <th className="px-3 py-2">{t("common.file", "Файл")}</th>
                  <th className="px-3 py-2">{t("common.format", "Формат")}</th>
                  <th className="px-3 py-2">{t("indexing.chars", "Символы")}</th>
                  <th className="px-3 py-2">{t("indexing.status", "Статус")}</th>
                </tr>
              </thead>
              <tbody>
                {visibleDocs.map((d) => (
                  <tr key={d.id} className="border-b border-border/50 last:border-0 hover:bg-accent DEFAULT/60">
                    <td className="px-3 py-1.5">
                      <input
                        type="checkbox"
                        checked={selected.has(d.id)}
                        disabled={d.status === "error" || showOnlyUnindexed && isDocIndexed(d)}
                        onChange={() => toggleDoc(d.id)}
                        className="h-4 w-4 rounded border-border text-primary DEFAULT"
                      />
                    </td>
                    <td className="px-3 py-1.5 font-medium" title={d.errors.join("; ")}>{d.source}</td>
                    <td className="px-3 py-1.5"><Badge variant="outline">{d.file_type}</Badge></td>
                    <td className="px-3 py-1.5">{d.char_count != null ? formatNumber(d.char_count) : "—"}</td>
                    <td className="px-3 py-1.5">
                      {isDocIndexed(d)
                        ? <Badge variant="success">{t("indexing.indexed", "проиндексирован")}</Badge>
                        : d.status === "error"
                          ? <Badge variant="error">{t("indexing.err", "ошибка")}</Badge>
                          : <Badge variant="secondary">{t("indexing.ready", "готов")}</Badge>}
                    </td>
                  </tr>
                ))}
                {visibleDocs.length === 0 ? (
                  <tr><td colSpan={5} className="px-3 py-3 text-center text-muted-foreground">{t("indexing.emptyTable", "Нет документов для отображения")}</td></tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* B. Стратегии */}
      <Card>
        <CardHeader>
          <CardTitle>{t("indexing.stratTitle", "2. Стратегии chunking")}</CardTitle>
          <CardDescription>{t("indexing.stratSub", "Можно выбрать одну или обе стратегии")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5 lg:grid-cols-2">
          <div className="rounded-lg border border-border p-4">
            <Checkbox
              checked={useFixed}
              onChange={setUseFixed}
              label={t("indexing.fixedLabel", "Fixed-size chunking")}
              description={t("indexing.fixedDesc", "Чанки фиксированного размера с перекрытием")}
            />
            <div className="mt-3 space-y-3">
              <Input
                type="number"
                label={t("indexing.chunkSize", "Размер чанка")}
                value={chunkSize}
                min={50}
                disabled={!useFixed}
                onChange={(e) => setChunkSize(Number(e.target.value))}
              />
              <Input
                type="number"
                label={t("indexing.overlap", "Overlap (перекрытие)")}
                value={overlap}
                min={0}
                disabled={!useFixed}
                hint={overlap >= chunkSize && useFixed ? <span className="text-red-600 dark:text-red-400">{t("indexing.overlapErrShort", "Overlap должен быть меньше размера чанка")}</span> : undefined}
                onChange={(e) => setOverlap(Number(e.target.value))}
              />
              <Select
                label={t("indexing.unit", "Единица измерения")}
                value={unit}
                disabled={!useFixed}
                onChange={(e) => setUnit(e.target.value === "tokens" ? "tokens" : "chars")}
              >
                <option value="chars">{t("indexing.charsUnit", "Символы")}</option>
                <option value="tokens">{t("indexing.tokensUnit", "Токены (требуется tiktoken)")}</option>
              </Select>
            </div>
          </div>
          <div className="rounded-lg border border-border p-4">
            <Checkbox
              checked={useStructural}
              onChange={setUseStructural}
              label={t("indexing.structLabel", "Structural chunking")}
              description={t("indexing.structDesc", "Разделы, заголовки, функции и страницы")}
            />
            <div className="mt-3 space-y-3">
              <Input
                type="number"
                label={t("indexing.maxChunk", "Максимальный размер чанка")}
                value={maxChunk}
                min={100}
                disabled={!useStructural}
                onChange={(e) => setMaxChunk(Number(e.target.value))}
              />
              <Input
                type="number"
                label={t("indexing.minChunk", "Минимальный размер чанка")}
                value={minChunk}
                min={50}
                disabled={!useStructural}
                hint={minChunk > maxChunk && useStructural ? <span className="text-red-600 dark:text-red-400">{t("indexing.minMaxErrShort", "Минимум не может быть больше максимума")}</span> : undefined}
                onChange={(e) => setMinChunk(Number(e.target.value))}
              />
              <ToggleSwitch checked={mergeSmall} onChange={setMergeSmall} disabled={!useStructural} label={t("indexing.mergeSmall", "Объединять небольшие разделы")} />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* C. Эмбеддинги */}
      <Card>
        <CardHeader>
          <CardTitle>{t("indexing.embTitle", "3. Эмбеддинги (локальный Ollama)")}</CardTitle>
          <CardDescription>{t("indexing.embSub", "Векторизация выполняется локально — содержимое документов не покидает машину")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <Input label={t("indexing.ollamaUrl", "URL Ollama")} value={ollamaUrl} onChange={(e) => setOllamaUrl(e.target.value)} />
          <Input label={t("indexing.embModel", "Модель")} value={model} onChange={(e) => setModel(e.target.value)} />
          <Input type="number" label={t("indexing.batch", "Размер batch")} value={batchSize} min={1} max={512} onChange={(e) => setBatchSize(Number(e.target.value))} />
          <Input type="number" label={t("indexing.retries", "Повторные попытки")} value={retries} min={0} max={10} onChange={(e) => setRetries(Number(e.target.value))} />
        </CardContent>
        <CardContent>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => void runTest()} disabled={testing}>
              <Server className="h-4 w-4" /> {testing ? t("indexing.testing", "Проверка…") : t("indexing.testBtn", "Проверить подключение")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => void copyPullCommand()}>
              <Copy className="h-4 w-4" /> {t("indexing.copyPull", "Копировать: ollama pull {model}").replace("{model}", model.trim() || "nomic-embed-text")}
            </Button>
            {ollamaStatus ? (
              <Badge variant={ollamaStatus.available ? "success" : "error"}>
                {ollamaStatus.available
                  ? t("indexing.ollamaOn", "Ollama доступен") + (ollamaStatus.model_available === false ? ` · ${t("indexing.modelAbsent", "модель не установлена")}` : "")
                  : t("indexing.ollamaOff", "Ollama недоступен")}
              </Badge>
            ) : null}
          </div>
          {testResult ? (
            <div className="mt-3">
              <Alert variant={testResult.ok ? "success" : "error"} icon={testResult.ok ? <CheckCircle2 className="h-4 w-4" /> : <CircleAlert className="h-4 w-4" />}>
                <p className="font-medium">{testResult.message}</p>
                {testResult.dimension ? <p className="mt-1 text-xs">{t("indexing.dim", "Размерность вектора: {dim}").replace("{dim}", String(testResult.dimension))}{testResult.vector_finite === false ? ` · ${t("indexing.notFinite", "вектор содержит нечисловые значения!")}` : ""}</p> : null}
                {testResult.pull_command ? (
                  <p className="mt-1 text-xs">
                    <Kbd>{testResult.pull_command}</Kbd>
                  </p>
                ) : null}
              </Alert>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* D. Режим */}
      <Card>
        <CardHeader>
          <CardTitle>{t("indexing.modeTitle", "4. Коллекция и режим")}</CardTitle>
          <CardDescription>{t("indexing.modeSub", "Решите, куда сохранять результат. Индексы не перезаписываются молча.")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {([
              ["new_collection", t("indexing.mNew", "Создать новую коллекцию"), Database],
              ["new_index", t("indexing.mNewIndex", "Новый индекс в коллекции"), BarChart3],
              ["rebuild", t("indexing.mRebuild", "Перестроить индекс"), Trash2],
              ["add", t("indexing.mAdd", "Добавить документы"), Plus],
            ] as Array<[typeof mode, string, typeof Database]>).map(([m, label, Icon]) => (
              <button
                key={m}
type="button"
                 onClick={() => setMode(m)}
                 className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium ${mode === m ? "border-[hsl(var(--primary)/0.6)] bg-[hsl(var(--primary)/0.14)] text-foreground" : "border-border text-muted-foreground hover:bg-accent DEFAULT"}`}
               >
                <Icon className="h-4 w-4" />
                {label}
              </button>
            ))}
          </div>
          {mode === "new_collection" ? (
            <Input label={t("indexing.collName", "Название новой коллекции")} value={collectionName} onChange={(e) => setCollectionName(e.target.value)} placeholder={t("indexing.collNamePh", "Например: «База знаний 2026»")} />
          ) : (
            <Select label={t("indexing.collSelect", "Коллекция")} value={collectionId} onChange={(e) => setCollectionId(e.target.value)}>
              {collections.map((c) => (
                <option key={c.id} value={c.id}>{c.name} ({c.id})</option>
              ))}
            </Select>
          )}
          {col ? (
            <div className="rounded-lg border border-border bg-card p-3 text-sm">
              <p className="text-xs text-muted-foreground">{t("indexing.affected", "Существующие индексы коллекции «{name}»:").replace("{name}", col.name)}</p>
              {col.indexes.length === 0 ? (
                <p className="mt-1 text-muted-foreground">{t("indexing.noIndexesIn", "Индексов пока нет — будут созданы выбранные стратегии")}</p>
              ) : (
                <ul className="mt-1 list-disc pl-4">
                  {col.indexes.map((ix) => (
                    <li key={ix.strategy}>
                      {STRATEGY_LABELS[ix.strategy]} — {formatNumber(ix.num_vectors)} {t("indexing.vectors", "векторов")}, {formatBytes(ix.size_bytes)}
                      {mode === "rebuild" ? <Badge variant="warning" className="ml-2">{t("indexing.willRebuild", "будет перестроен")}</Badge> : mode === "add" ? <Badge variant="secondary" className="ml-2">{t("indexing.willAppend", "будет дополнен")}</Badge> : ""}
                    </li>
                  ))}
                </ul>
              )}
              {mode === "add" ? (
                <p className="mt-1.5 text-xs text-muted-foreground">{t("indexing.addCompat", "Добавление возможно только при совместимой модели и параметрах chunking; иначе backend отклонит задание.")}</p>
              ) : null}
            </div>
          ) : mode === "new_index" || mode === "rebuild" || mode === "add" ? (
            <Alert variant="warning"><Database className="h-4 w-4" /> {t("indexing.noCollections", "Коллекции не найдены — сначала создайте её режимом «Создать новую коллекцию».")}</Alert>
          ) : null}
          <Alert variant="info" icon={<Info className="h-4 w-4" />}>
            {t("indexing.expected", "Ожидаемые операции: {docs} документов × {strats} стратегий; эмбеддинги создаются пакетами по {batch} текстов.").replace("{docs}", String(selectedCount())).replace("{strats}", String(activeStrategies.length)).replace("{batch}", String(batchSize))}
          </Alert>
        </CardContent>
      </Card>

      {/* E. Запуск */}
      <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center">
        <Button size="lg" variant="default" onClick={() => void launch()} disabled={starting} className="px-8">
          <Play className="h-5 w-5" />
          {starting ? t("indexing.starting", "Запуск…") : t("indexing.launch", "Запустить индексацию")}
        </Button>
        {mode !== "new_collection" && col ? (
          <span className="text-sm text-muted-foreground">
            {mode === "rebuild" ? t("indexing.rebuildNote", "Выбранные индексы будут пересозданы") : mode === "add" ? t("indexing.addNote", "Документы будут добавлены в существующие индексы") : t("indexing.newIndexNote", "Будут созданы только отсутствующие индексы")}
          </span>
        ) : null}
      </div>
    </div>
  );
}