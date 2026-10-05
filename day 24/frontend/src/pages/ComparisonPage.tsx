/** Страница «Сравнение стратегий»: метрики и графики по фактическим результатам индексации. */

import { useCallback, useEffect, useState } from "react";
import { ArrowLeftRight, GitCompare, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { t } from "../app/i18n";
import { BoxPlotChart, ColumnChart, HistogramChart, TimingLineChart, boxStats } from "../components/charts/Charts";
import type { BoxStats } from "../components/charts/Charts";
import {
  Alert,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  EmptyState,
  Select,
  Spinner,
} from "../components/ui";
import { cn, formatBytes, formatMs, formatNumber } from "../lib/utils";
import { getComparison, listCollections } from "../services/api";
import type { Collection, ComparisonMetrics, ComparisonOut, Strategy } from "../types/api";

/** Человекочитаемая подпись стратегии чанкинга. */
function strategyLabel(s: Strategy): string {
  if (s === "fixed_size") return t("strategy.fixed_size", "Фиксированный размер");
  return t("strategy.structural", "Структурная");
}

/** Извлечение сообщения из ошибки (Error / неизвестное). */
function apiDetail(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

interface MetricRow {
  key: string;
  label: string;
  render: (m: ComparisonMetrics) => string;
}

const METRIC_ROWS: MetricRow[] = [
  { key: "documents", label: t("cmp.metrics.documents", "Документы"), render: (m) => formatNumber(m.documents) },
  { key: "chunks", label: t("cmp.metrics.chunks", "Чанки"), render: (m) => formatNumber(m.chunks) },
  {
    key: "mean_chars",
    label: t("cmp.metrics.mean_chars", "Средний размер (символов)"),
    render: (m) => formatNumber(m.mean_chars),
  },
  {
    key: "median_chars",
    label: t("cmp.metrics.median_chars", "Медианный размер"),
    render: (m) => formatNumber(m.median_chars),
  },
  {
    key: "min_chars",
    label: t("cmp.metrics.min_chars", "Минимальный размер"),
    render: (m) => formatNumber(m.min_chars),
  },
  {
    key: "max_chars",
    label: t("cmp.metrics.max_chars", "Максимальный размер"),
    render: (m) => formatNumber(m.max_chars),
  },
  {
    key: "std_chars",
    label: t("cmp.metrics.std_chars", "Станд. отклонение"),
    render: (m) => formatNumber(m.std_chars),
  },
  {
    key: "empty_chunks",
    label: t("cmp.metrics.empty_chunks", "Пустые/отброшенные чанки"),
    render: (m) => formatNumber(m.empty_chunks),
  },
  {
    key: "index_size",
    label: t("cmp.metrics.index_size", "Размер FAISS-индекса"),
    render: (m) => formatBytes(m.index_size_bytes),
  },
  {
    key: "time_chunking",
    label: t("cmp.metrics.time_chunking", "Время chunking"),
    render: (m) => formatMs(m.time_chunking_ms),
  },
  {
    key: "time_embeddings",
    label: t("cmp.metrics.time_embeddings", "Время эмбеддингов"),
    render: (m) => formatMs(m.time_embeddings_ms),
  },
  {
    key: "time_total",
    label: t("cmp.metrics.time_total", "Общее время"),
    render: (m) => formatMs(m.time_total_ms),
  },
  { key: "errors", label: t("cmp.metrics.errors", "Ошибки"), render: (m) => formatNumber(m.errors) },
];

/** Графики и таблица метрик по загруженному сравнению. */
function ComparisonContent({ comparison }: { comparison: ComparisonOut }) {
  const strategies = comparison.strategies;

  const boxSeries = strategies
    .map((s) => {
      const stats = boxStats(comparison.sizes[s] ?? []);
      return stats ? { name: strategyLabel(s), stats } : null;
    })
    .filter((x): x is { name: string; stats: BoxStats } => x !== null);

  // Объединяем «чанки по документам» всех стратегий в одну таблицу данных:
  // данные = [{ name: title, [strategy]: chunks }], отсутствующие значения — 0.
  const docRows: Array<{ name: string; [key: string]: unknown }> = [];
  const docIndex: Record<string, { name: string; [key: string]: unknown }> = {};
  for (const s of strategies) {
    for (const row of comparison.per_document[s] ?? []) {
      let entry = docIndex[row.title];
      if (entry === undefined) {
        entry = { name: row.title };
        docIndex[row.title] = entry;
        docRows.push(entry);
      }
      entry[s] = row.chunks;
    }
  }
  for (const row of docRows) {
    for (const s of strategies) {
      if (row[s] === undefined) row[s] = 0;
    }
  }
  const docKeys = strategies.map((s) => ({ key: s, name: strategyLabel(s) }));

  // Один линейный график на стратегию: 3 точки (chunking / эмбеддинги / всего).
  const timingPoints = (s: Strategy): Array<{ name: string; value: number }> => {
    const timings = comparison.timings[s] ?? {};
    const points: Array<{ name: string; value: number }> = [];
    if (typeof timings.chunking_ms === "number") {
      points.push({ name: t("cmp.stage.chunking", "Chunking"), value: timings.chunking_ms });
    }
    if (typeof timings.embeddings_ms === "number") {
      points.push({ name: t("cmp.stage.embeddings", "Эмбеддинги"), value: timings.embeddings_ms });
    }
    if (typeof timings.total_ms === "number") {
      points.push({ name: t("cmp.stage.total", "Всего"), value: timings.total_ms });
    }
    return points;
  };

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t("cmp.metrics_title", "Метрики")}</CardTitle>
          <CardDescription>{comparison.collection_name}</CardDescription>
        </CardHeader>
        <CardContent>
          {strategies.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-4 py-2.5 font-medium">{t("cmp.metric_col", "Метрика")}</th>
                    {strategies.map((s) => (
                      <th key={s} className="px-4 py-2.5 text-right font-medium">
                        {strategyLabel(s)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {METRIC_ROWS.map((row) => (
                    <tr key={row.key} className="hover:bg-accent/40">
                      <td className="px-4 py-2.5">{row.label}</td>
                      {strategies.map((s) => {
                        const metrics = comparison.metrics[s];
                        return (
                          <td key={s} className="px-4 py-2.5 text-right tabular-nums">
                            {metrics ? row.render(metrics) : "—"}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {t("cmp.no_indexes", "Для выбранной коллекции нет проиндексированных стратегий")}
            </p>
          )}
        </CardContent>
      </Card>

      <p className="text-xs leading-relaxed text-muted-foreground">
        {t(
          "cmp.note",
          "Сравнение построено по фактическим результатам индексации. Большее/меньшее число чанков само по себе не означает качество.",
        )}
      </p>

      {strategies.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {strategies.map((s) => {
            const histogram = comparison.histogram[s];
            return (
              <Card key={`hist-${s}`}>
                <CardHeader>
                  <CardTitle>{t("cmp.chart.histogram", "Распределение размеров чанков")}</CardTitle>
                  <CardDescription>{strategyLabel(s)}</CardDescription>
                </CardHeader>
                <CardContent>
                  {histogram && histogram.length > 0 ? (
                    <HistogramChart data={histogram} />
                  ) : (
                    <p className="text-sm text-muted-foreground">{t("cmp.no_data", "Нет данных")}</p>
                  )}
                </CardContent>
              </Card>
            );
          })}

          <Card>
            <CardHeader>
              <CardTitle>{t("cmp.chart.boxplot", "Box plot размеров")}</CardTitle>
              <CardDescription>{t("cmp.chart.boxplot_desc", "Мин., квартили и макс. размера чанков")}</CardDescription>
            </CardHeader>
            <CardContent>
              {boxSeries.length > 0 ? (
                <BoxPlotChart series={boxSeries} />
              ) : (
                <p className="text-sm text-muted-foreground">{t("cmp.no_data", "Нет данных")}</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("cmp.chart.per_document", "Чанки по документам")}</CardTitle>
              <CardDescription>{t("cmp.chart.per_document_desc", "Количество чанков на документ")}</CardDescription>
            </CardHeader>
            <CardContent>
              {docRows.length > 0 ? (
                <ColumnChart data={docRows} keys={docKeys} />
              ) : (
                <p className="text-sm text-muted-foreground">{t("cmp.no_data", "Нет данных")}</p>
              )}
            </CardContent>
          </Card>

          {strategies.map((s) => {
            const points = timingPoints(s);
            return (
              <Card key={`timing-${s}`}>
                <CardHeader>
                  <CardTitle>{t("cmp.chart.timings", "Время индексации")}</CardTitle>
                  <CardDescription>{strategyLabel(s)}</CardDescription>
                </CardHeader>
                <CardContent>
                  {points.length > 0 ? (
                    <TimingLineChart data={points} />
                  ) : (
                    <p className="text-sm text-muted-foreground">{t("cmp.no_data", "Нет данных")}</p>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{t("cmp.tradeoffs", "О компромиссах")}</CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant="info" icon={<ArrowLeftRight className="h-4 w-4" />}>
            {comparison.tradeoffs.length > 0 ? (
              <ul className="list-inside list-disc space-y-1">
                {comparison.tradeoffs.map((tradeoff, i) => (
                  <li key={i}>{tradeoff}</li>
                ))}
              </ul>
            ) : (
              <p>
                {t(
                  "cmp.tradeoffs_fallback",
                  "Fixed-size chunking даёт предсказуемый размер чанков, но может разрезать мысль посередине. Structural chunking сохраняет смысловые границы (заголовки, функции, страницы), но размер чанков менее равномерен. «Лучшая» стратегия зависит от структуры корпуса и качества извлечения текста.",
                )}
              </p>
            )}
          </Alert>
        </CardContent>
      </Card>
    </>
  );
}

export function ComparisonPage() {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionsError, setCollectionsError] = useState<string | null>(null);

  const [selectedCollection, setSelectedCollection] = useState("__all__");
  const [comparison, setComparison] = useState<ComparisonOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadCollections = useCallback(async () => {
    setCollectionsError(null);
    try {
      setCollections(await listCollections());
    } catch (e) {
      setCollectionsError(apiDetail(e));
    }
  }, []);

  const loadComparison = useCallback(async (collectionId: string) => {
    setLoading(true);
    setLoadError(null);
    try {
      setComparison(await getComparison(collectionId === "__all__" ? undefined : collectionId));
    } catch (e) {
      setComparison(null);
      setLoadError(apiDetail(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCollections();
  }, [loadCollections]);

  useEffect(() => {
    void loadComparison(selectedCollection);
  }, [selectedCollection, loadComparison]);

  const noIndexes =
    collections.length === 0 && comparison !== null && comparison.strategies.length === 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <GitCompare className="h-6 w-6 text-muted-foreground" />
          <h1 className="text-2xl font-bold tracking-tight">{t("cmp.title", "Сравнение стратегий")}</h1>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <Select
            label={t("cmp.collection", "Коллекция")}
            value={selectedCollection}
            disabled={loading}
            onChange={(e) => setSelectedCollection(e.target.value)}
            className="w-56"
          >
            <option value="__all__">{t("cmp.all_collections", "Все коллекции")}</option>
            {collections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Button variant="outline" disabled={loading} onClick={() => void loadComparison(selectedCollection)}>
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
            {t("cmp.refresh", "Обновить")}
          </Button>
        </div>
      </div>

      {collectionsError ? (
        <Alert variant="error" icon={<GitCompare className="h-4 w-4" />}>
          {t("cmp.collections_error", "Не удалось загрузить коллекции")}: {collectionsError}
        </Alert>
      ) : null}

      {loading && comparison === null ? (
        <Card>
          <CardContent>
            <Spinner label={t("cmp.loading", "Загрузка сравнения…")} />
          </CardContent>
        </Card>
      ) : loadError ? (
        <div className="space-y-3">
          <Alert variant="error" icon={<RefreshCw className="h-4 w-4" />}>
            <span className="font-medium">{t("cmp.load_error", "Не удалось загрузить сравнение")}</span>
            <p className="mt-0.5">{loadError}</p>
          </Alert>
          <Button variant="outline" size="sm" onClick={() => void loadComparison(selectedCollection)}>
            {t("cmp.retry", "Повторить")}
          </Button>
        </div>
      ) : noIndexes ? (
        <EmptyState
          icon={<GitCompare className="h-6 w-6" />}
          title={t("cmp.empty_title", "Сначала создайте индексы")}
          description={t(
            "cmp.empty_description",
            "Сравнение строится по фактическим результатам индексации. Создайте коллекцию и проиндексируйте документы хотя бы одной стратегией.",
          )}
          action={
            <Link to="/indexing">
              <Button size="sm">{t("cmp.go_indexing", "Перейти к индексации")}</Button>
            </Link>
          }
        />
      ) : comparison ? (
        <ComparisonContent comparison={comparison} />
      ) : null}
    </div>
  );
}