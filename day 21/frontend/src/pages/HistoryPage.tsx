/** Страница «История запусков»: журнал заданий индексации с фильтрами и деталями. */

import { Eye, History, RefreshCw } from "lucide-react";
import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { t } from "../app/i18n";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  EmptyState,
  Input,
  Progress,
  Select,
  Spinner,
} from "../components/ui";
import { useToast } from "../components/ui/toast";
import { getHistory, getHistoryJob, listCollections, STRATEGY_LABELS } from "../services/api";
import type { Collection, JobStatus, JobSummary, Strategy } from "../types/api";
import { formatBytes, cn, formatDate, formatDuration, formatMs, formatNumber } from "../lib/utils";

type BadgeVariant = "default" | "secondary" | "success" | "warning" | "error" | "outline";

const STATUS_OPTIONS: Array<{ value: JobStatus; label: string }> = [
  { value: "queued", label: t("history.status.queued", "В очереди") },
  { value: "running", label: t("history.status.running", "Выполняется") },
  { value: "completed", label: t("history.status.completed", "Завершён") },
  { value: "completed_with_errors", label: t("history.status.completed_with_errors", "С ошибками") },
  { value: "failed", label: t("history.status.failed", "Ошибка") },
  { value: "cancelled", label: t("history.status.cancelled", "Отменён") },
];

const STATUS_BADGE: Record<JobStatus, BadgeVariant> = {
  queued: "secondary",
  running: "warning",
  completed: "success",
  completed_with_errors: "warning",
  failed: "error",
  cancelled: "secondary",
};

const MODE_LABELS: Record<string, string> = {
  new_collection: t("history.mode.new_collection", "Новая коллекция"),
  new_index: t("history.mode.new_index", "Новый индекс"),
  rebuild: t("history.mode.rebuild", "Перестроение"),
  add: t("history.mode.add", "Добавление документов"),
};

interface Filters {
  status: string;
  collection_id: string;
  strategy: string;
  date_from: string;
  date_to: string;
}

const EMPTY_FILTERS: Filters = {
  status: "",
  collection_id: "",
  strategy: "",
  date_from: "",
  date_to: "",
};

function statusLabel(status: JobStatus): string {
  return STATUS_OPTIONS.find((s) => s.value === status)?.label ?? status;
}

function modeLabel(mode: string): string {
  return MODE_LABELS[mode] ?? mode;
}

function strategyLabel(s: string): string {
  return STRATEGY_LABELS[s as Strategy] ?? s;
}

export function HistoryPage() {
  const toast = useToast();

  const [collections, setCollections] = useState<Collection[]>([]);
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [draft, setDraft] = useState<Filters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS);

  const [detailJobId, setDetailJobId] = useState<string | null>(null);
  const [detailJob, setDetailJob] = useState<JobSummary | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const loadHistory = useCallback(async (filters: Filters) => {
    setLoading(true);
    setError(null);
    try {
      const data = await getHistory({
        status: filters.status || undefined,
        collection_id: filters.collection_id || undefined,
        strategy: filters.strategy || undefined,
        date_from: filters.date_from || undefined,
        date_to: filters.date_to || undefined,
      });
      setJobs(data.jobs);
      setTotal(data.total);
    } catch (e) {
      setJobs(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadCollections = useCallback(async () => {
    try {
      setCollections(await listCollections());
    } catch (e) {
      toast.error(
        t("history.collections_error_title", "Не удалось загрузить коллекции"),
        e instanceof Error ? e.message : undefined,
      );
    }
  }, [toast]);

  useEffect(() => {
    void loadHistory(EMPTY_FILTERS);
    void loadCollections();
  }, [loadHistory, loadCollections]);

  const applyFilters = () => {
    setApplied(draft);
    void loadHistory(draft);
  };

  const resetFilters = () => {
    setDraft(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    void loadHistory(EMPTY_FILTERS);
  };

  const reload = () => {
    void loadHistory(applied);
  };

  const openDetail = useCallback(
    async (jobId: string) => {
      setDetailJobId(jobId);
      setDetailJob(null);
      setDetailError(null);
      setDetailLoading(true);
      try {
        setDetailJob(await getHistoryJob(jobId));
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setDetailError(msg);
        toast.error(t("history.detail_error_title", "Не удалось загрузить детали запуска"), msg);
      } finally {
        setDetailLoading(false);
      }
    },
    [toast],
  );

  const closeDetail = () => {
    setDetailJobId(null);
    setDetailJob(null);
    setDetailError(null);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold">{t("history.title", "История запусков")}</h1>
        <Button variant="outline" size="sm" onClick={reload} disabled={loading}>
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          {t("history.refresh", "Обновить")}
        </Button>
      </div>

      {/* Панель фильтров */}
      <Card>
        <CardHeader>
          <CardTitle>{t("history.filters_title", "Фильтры")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Select
              label={t("history.filter_status", "Статус")}
              value={draft.status}
              onChange={(e) => setDraft({ ...draft, status: e.target.value })}
            >
              <option value="">{t("history.filter_all", "Все")}</option>
              {STATUS_OPTIONS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
            <Select
              label={t("history.filter_collection", "Коллекция")}
              value={draft.collection_id}
              onChange={(e) => setDraft({ ...draft, collection_id: e.target.value })}
            >
              <option value="">{t("history.filter_all", "Все")}</option>
              {collections.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
            <Select
              label={t("history.filter_strategy", "Стратегия")}
              value={draft.strategy}
              onChange={(e) => setDraft({ ...draft, strategy: e.target.value })}
            >
              <option value="">{t("history.filter_all", "Все")}</option>
              {(["fixed_size", "structural"] as Strategy[]).map((s) => (
                <option key={s} value={s}>
                  {STRATEGY_LABELS[s]}
                </option>
              ))}
            </Select>
            <Input
              type="date"
              label={t("history.filter_date_from", "С даты")}
              value={draft.date_from}
              onChange={(e) => setDraft({ ...draft, date_from: e.target.value })}
            />
            <Input
              type="date"
              label={t("history.filter_date_to", "По дате")}
              value={draft.date_to}
              onChange={(e) => setDraft({ ...draft, date_to: e.target.value })}
            />
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button onClick={applyFilters} disabled={loading}>
              {t("history.apply", "Применить")}
            </Button>
            <Button variant="outline" onClick={resetFilters} disabled={loading}>
              {t("history.reset", "Сбросить")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Таблица запусков */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>{t("history.runs_title", "Запуски")}</CardTitle>
          {jobs !== null ? (
            <span className="text-xs text-muted-foreground">
              {t("history.total", "Всего записей")}: {formatNumber(total)}
            </span>
          ) : null}
        </CardHeader>
        <CardContent className="p-0">
          {loading && jobs === null ? (
            <div className="flex justify-center py-16">
              <Spinner label={t("history.loading", "Загрузка истории…")} />
            </div>
          ) : error ? (
            <div className="space-y-3 p-5">
              <Alert variant="error" icon={<RefreshCw className="h-4 w-4" />}>
                <span className="font-medium">{t("history.error_title", "Не удалось загрузить историю")}</span>
                <p className="mt-0.5">{error}</p>
              </Alert>
              <Button variant="outline" size="sm" onClick={reload}>
                {t("history.retry", "Повторить")}
              </Button>
            </div>
          ) : jobs && jobs.length === 0 ? (
            <div className="p-5">
              <EmptyState
                icon={<History className="h-6 w-6" />}
                title={t("history.empty_title", "Запусков пока нет")}
                description={t(
                  "history.empty_description",
                  "Запустите индексацию документов на странице «Индексация» — записи появятся в журнале.",
                )}
                action={
                  <Link to="/indexing">
                    <Button size="sm">{t("history.go_indexing", "Перейти к индексации")}</Button>
                  </Link>
                }
              />
            </div>
          ) : jobs ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[960px] text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-5 py-3 font-medium">{t("history.col_job", "Задание")}</th>
                    <th className="px-4 py-3 font-medium">{t("history.col_status", "Статус")}</th>
                    <th className="px-4 py-3 font-medium">{t("history.col_strategies", "Стратегии")}</th>
                    <th className="px-4 py-3 font-medium">{t("history.col_documents", "Документы")}</th>
                    <th className="px-4 py-3 font-medium">{t("history.col_chunks", "Чанки")}</th>
                    <th className="px-4 py-3 font-medium">{t("history.col_embeddings", "Эмбеддинги")}</th>
                    <th className="px-4 py-3 font-medium">{t("history.col_errors", "Ошибки")}</th>
                    <th className="px-4 py-3 font-medium">{t("history.col_duration", "Длительность")}</th>
                    <th className="px-4 py-3 font-medium">{t("history.col_created", "Создан")}</th>
                    <th className="px-4 py-3 text-right font-medium" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {jobs.map((job) => (
                    <tr key={job.job_id} className="transition-colors hover:bg-accent DEFAULT/40">
                      <td className="px-5 py-3">
                        <span className="font-mono text-xs">{job.job_id}</span>
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={STATUS_BADGE[job.status]}>{statusLabel(job.status)}</Badge>
                      </td>
                      <td className="px-4 py-3">{job.strategies.map(strategyLabel).join(", ") || "—"}</td>
                      <td className="px-4 py-3">{formatNumber(job.documents)}</td>
                      <td className="px-4 py-3">{formatNumber(job.chunks)}</td>
                      <td className="px-4 py-3">{formatNumber(job.embeddings_ok)}</td>
                      <td
                        className={cn(
                          "px-4 py-3",
                          job.errors > 0 ? "font-medium text-red-600 dark:text-red-400" : "",
                        )}
                      >
                        {formatNumber(job.errors)}
                      </td>
                      <td className="px-4 py-3">{formatDuration(job.duration_seconds)}</td>
                      <td className="px-4 py-3 text-muted-foreground">{formatDate(job.created_at)}</td>
                      <td className="px-4 py-3 text-right">
                        <Button variant="outline" size="sm" onClick={() => void openDetail(job.job_id)}>
                          <Eye className="h-3.5 w-3.5" />
                          {t("history.details", "Подробнее")}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <p className="text-xs leading-relaxed text-muted-foreground">
        {t(
          "history.note",
          "История хранится в SQLite и переживает перезапуск приложения. Полный текст документов не сохраняется в журнале.",
        )}
      </p>

      {/* Диалог деталей запуска */}
      <Dialog
        open={detailJobId !== null}
        onClose={closeDetail}
        title={t("history.detail_title", "Детали запуска")}
        description={detailJobId ?? undefined}
        wide
      >
        {detailLoading ? (
          <div className="flex justify-center py-10">
            <Spinner label={t("history.detail_loading", "Загрузка деталей…")} />
          </div>
        ) : detailError ? (
          <div className="space-y-3">
            <Alert variant="error">
              <span className="font-medium">{t("history.detail_error", "Не удалось загрузить детали запуска")}</span>
              <p className="mt-0.5">{detailError}</p>
            </Alert>
            <Button size="sm" onClick={() => void (detailJobId && openDetail(detailJobId))}>
              {t("history.retry", "Повторить")}
            </Button>
          </div>
        ) : detailJob ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={STATUS_BADGE[detailJob.status]}>{statusLabel(detailJob.status)}</Badge>
              <Badge variant="outline">{modeLabel(detailJob.mode)}</Badge>
            </div>

            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-xs text-muted-foreground">{t("history.detail_strategies", "Стратегии")}</dt>
                <dd className="mt-0.5 font-medium">
                  {detailJob.strategies.map(strategyLabel).join(", ") || "—"}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t("history.detail_collection", "Коллекция")}</dt>
                <dd className="mt-0.5 font-medium">{detailJob.collection_name ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t("history.detail_model", "Модель")}</dt>
                <dd className="mt-0.5 font-medium">{detailJob.model ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t("history.detail_documents", "Документы")}</dt>
                <dd className="mt-0.5 font-medium">{formatNumber(detailJob.documents)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t("history.detail_chunks", "Чанки")}</dt>
                <dd className="mt-0.5 font-medium">{formatNumber(detailJob.chunks)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t("history.detail_embeddings", "Эмбеддинги")}</dt>
                <dd className="mt-0.5 font-medium">
                  {t("history.detail_ok", "ок")}: {formatNumber(detailJob.embeddings_ok)} /{" "}
                  <span className={detailJob.errors > 0 ? "text-red-600 dark:text-red-400" : ""}>
                    {t("history.detail_failed", "ошибки")}: {formatNumber(detailJob.errors)}
                  </span>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t("history.detail_duration", "Длительность")}</dt>
                <dd className="mt-0.5 font-medium">{formatDuration(detailJob.duration_seconds)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t("history.detail_created", "Создан")}</dt>
                <dd className="mt-0.5 font-medium">{formatDate(detailJob.created_at)}</dd>
              </div>
            </dl>

            {detailJob.status === "queued" || detailJob.status === "running" ? (
              <div className="space-y-1">
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>{t("history.progress", "Прогресс")}</span>
                  <span>{formatNumber(detailJob.progress_percent)}%</span>
                </div>
                <Progress value={detailJob.progress_percent} stripe={detailJob.status === "running"} />
              </div>
            ) : null}

            <div>
              <h4 className="mb-2 text-sm font-semibold">{t("history.result_title", "Результат")}</h4>
              {detailJob.result?.indexes.length ? (
                <div className="space-y-2">
                  {detailJob.result.indexes.map((idx) => (
                    <div
                      key={idx.index_id}
                      className="space-y-1 rounded-md border border-border p-3 text-sm"
                    >
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span className="font-medium">{strategyLabel(idx.strategy)}</span>
                        <span className="font-mono text-xs text-muted-foreground">{idx.index_id}</span>
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
                        <span>
                          {t("history.result_vectors", "Векторов")}: {formatNumber(idx.num_vectors)}
                        </span>
                        <span>
                          {t("history.result_size", "Размер")}: {formatBytes(idx.size_bytes)}
                        </span>
                        <span>
                          {t("history.result_dimension", "Размерность")}: {formatNumber(idx.dimension)}
                        </span>
                      </div>
                    </div>
                  ))}
                  {detailJob.result.time_total_ms !== null && detailJob.result.time_total_ms !== undefined ? (
                    <p className="text-xs text-muted-foreground">
                      {t("history.result_total_time", "Общее время")}: {formatMs(detailJob.result.time_total_ms)}
                    </p>
                  ) : null}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">{t("history.result_empty", "Результат недоступен")}</p>
              )}
            </div>

            {detailJob.message ? <Alert variant="info">{detailJob.message}</Alert> : null}
          </div>
        ) : null}
      </Dialog>
    </div>
  );
}