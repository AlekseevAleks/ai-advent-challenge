/** Страница «Обзор»: состояние backend и Ollama, сводная статистика и графики. */

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeftRight,
  BookOpen,
  CheckCircle2,
  CircleAlert,
  Cpu,
  Database,
  FileDown,
  FileText,
  HardDrive,
  History,
  LayoutDashboard,
  RefreshCw,
  Server,
} from "lucide-react";
import { t } from "../app/i18n";
import { Alert, Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, Spinner, StatCard } from "../components/ui";
import { useToast } from "../components/ui/toast";
import { ColumnChart, HistogramChart, TimingLineChart } from "../components/charts/Charts";
import { getHealth, getOllamaStatus, getOverview, testOllama } from "../services/api";
import type { Health, OllamaStatus, OverviewStats } from "../types/api";
import { cn, formatDate, formatNumber } from "../lib/utils";

interface LinkButtonProps {
  to: string;
  children: ReactNode;
  variant?: "default" | "outline";
  className?: string;
}

/** Кнопка-ссылка с теми же стилями, что и Button. */
function LinkButton({ to, children, variant = "outline", className }: LinkButtonProps) {
  return (
    <Link
      to={to}
      className={cn(
        "inline-flex h-9 items-center justify-center gap-2 whitespace-nowrap rounded-md px-4 text-sm font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        variant === "default"
          ? "bg-primary DEFAULT text-primary-foreground shadow-sm hover:bg-primary DEFAULT/90"
          : "border border-border text-accent-foreground hover:bg-accent DEFAULT",
        className,
      )}
    >
      {children}
    </Link>
  );
}

export function DashboardPage() {
  const toast = useToast();

  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [overview, setOverview] = useState<OverviewStats | null>(null);

  const [ollama, setOllama] = useState<OllamaStatus | null>(null);
  const [ollamaLoading, setOllamaLoading] = useState<boolean>(true);
  const [ollamaError, setOllamaError] = useState<string | null>(null);
  const [testingOllama, setTestingOllama] = useState<boolean>(false);

  const loadOllama = useCallback(async () => {
    setOllamaLoading(true);
    setOllamaError(null);
    try {
      const s = await getOllamaStatus();
      setOllama(s);
    } catch (e) {
      setOllama(null);
      setOllamaError(e instanceof Error ? e.message : String(e));
    } finally {
      setOllamaLoading(false);
    }
  }, []);

  const load = useCallback(async (): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      const [h, o] = await Promise.all([getHealth(), getOverview()]);
      setHealth(h);
      setOverview(o);
      return true;
    } catch (e) {
      setHealth(null);
      setOverview(null);
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    void loadOllama();
  }, [load, loadOllama]);

  const handleRefresh = useCallback(async () => {
    const ok = await load();
    void loadOllama();
    if (ok) {
      toast.success(t("overview.refreshed", "Данные обновлены"));
    } else {
      toast.error(t("overview.refreshError", "Не удалось обновить данные"));
    }
  }, [load, loadOllama, toast]);

  const handleTestOllama = useCallback(async () => {
    setTestingOllama(true);
    try {
      const res = await testOllama();
      if (res.ok) {
        toast.success(t("overview.ollamaTestOk", "Ollama работает"), res.message || undefined);
      } else {
        toast.warning(
          t("overview.ollamaTestWarn", "Проблемы с Ollama"),
          res.message || res.error || undefined,
        );
      }
    } catch (e) {
      toast.error(
        t("overview.ollamaTestError", "Ошибка проверки Ollama"),
        e instanceof Error ? e.message : String(e),
      );
    } finally {
      setTestingOllama(false);
    }
  }, [toast]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-24">
        <Spinner label={t("overview.loading", "Загрузка данных…")} />
      </div>
    );
  }

  const backendOk = health?.status === "ok" && overview?.backend_status === "ok";

  if (!backendOk || !overview || !health) {
    return (
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
              <LayoutDashboard className="h-6 w-6 text-primary DEFAULT" />
              {t("overview.title", "Обзор")}
            </h1>
            <Badge variant="error">{t("overview.backendDown", "недоступен")}</Badge>
          </div>
          <Button variant="outline" onClick={handleRefresh} loading={loading}>
            <RefreshCw className="h-4 w-4" />
            {t("overview.retry", "Повторить")}
          </Button>
        </div>
        <Alert variant="error" icon={<CircleAlert className="h-4 w-4" />}>
          <span>{t("overview.backendUnavailable", "Нет соединения с backend")}</span>
          {error ? <p className="mt-1 text-xs opacity-80">{error}</p> : null}
        </Alert>
      </div>
    );
  }

  const chunkStrategyData: Array<{ name: string; value: number }> = Object.entries(
    overview.charts.chunks_by_strategy,
  ).map(([name, value]) => ({ name, value }));

  const lastDurations: Array<{ name: string; value: number }> = overview.charts.last_durations.flatMap((d) =>
    d.ms === null ? [] : [{ name: d.label.slice(0, 8), value: d.ms }],
  );

  const indexSizeData: Array<{ name: string; value: number }> = overview.charts.index_sizes.map((ix) => ({
    name: `${ix.collection_id} / ${ix.strategy}`,
    value: ix.size_bytes,
  }));

  const noDocuments = overview.documents.total === 0;
  const noIndexes = overview.collections.indexes === 0;

  return (
    <div className="space-y-6">
      {/* Заголовок */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <LayoutDashboard className="h-6 w-6 text-primary DEFAULT" />
            {t("overview.title", "Обзор")}
          </h1>
          <Badge variant="success">{t("overview.backendUp", "работает")}</Badge>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={handleRefresh} loading={loading}>
            <RefreshCw className="h-4 w-4" />
            {t("overview.refresh", "Обновить")}
          </Button>
          <LinkButton to="/settings">
            <ArrowLeftRight className="h-4 w-4" />
            {t("overview.goToOllamaTests", "К тестам Ollama")}
          </LinkButton>
        </div>
      </div>

      {/* Статус Ollama */}
      <Card>
        <CardHeader className="sm:flex-row sm:items-center sm:justify-between sm:space-y-0">
          <CardTitle className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-muted-foreground" />
            {t("overview.ollamaTitle", "Ollama")}
          </CardTitle>
          {ollama ? (
            <Badge variant={ollama.available ? "success" : "error"}>
              {ollama.available
                ? t("overview.ollamaOnline", "онлайн")
                : t("overview.ollamaOffline", "недоступен")}
            </Badge>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-4">
          {ollamaLoading ? (
            <Spinner label={t("overview.ollamaLoading", "Проверка статуса Ollama…")} />
          ) : ollama ? (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <div>
                  <p className="text-xs font-medium text-muted-foreground">{t("overview.ollamaVersion", "Версия")}</p>
                  <p className="mt-0.5 text-sm font-medium">{ollama.version ?? "—"}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground">{t("overview.ollamaModel", "Модель")}</p>
                  <p className="mt-0.5 text-sm font-medium">{ollama.model ?? "—"}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground">{t("overview.ollamaDimension", "Размерность")}</p>
                  <p className="mt-0.5 text-sm font-medium">
                    {ollama.model_dimension ?? t("overview.ollamaDimensionEmpty", "— (проверьте в Настройках)")}
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="outline" size="sm" onClick={handleTestOllama} loading={testingOllama}>
                  {t("overview.testOllama", "Проверить Ollama")}
                </Button>
                {ollama.message ? <p className="text-xs text-muted-foreground">{ollama.message}</p> : null}
              </div>
            </>
          ) : (
            <Alert variant="error" icon={<CircleAlert className="h-4 w-4" />}>
              <span>{t("overview.ollamaError", "Не удалось получить статус Ollama")}</span>
              {ollamaError ? <p className="mt-1 text-xs opacity-80">{ollamaError}</p> : null}
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* StatCard-ы */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={t("overview.docs", "Документы")}
          value={formatNumber(overview.documents.total)}
          icon={<FileText className="h-4 w-4" />}
        />
        <StatCard
          label={t("overview.pages", "Страницы")}
          value={formatNumber(overview.documents.pages)}
          icon={<BookOpen className="h-4 w-4" />}
        />
        <StatCard
          label={t("overview.chars", "Символы извлечённого текста")}
          value={formatNumber(overview.documents.char_count)}
          icon={<FileDown className="h-4 w-4" />}
        />
        <StatCard
          label={t("overview.chunks", "Чанки всего")}
          value={formatNumber(overview.chunks.total)}
          icon={<Database className="h-4 w-4" />}
        />
        <StatCard
          label={t("overview.collections", "Коллекции")}
          value={formatNumber(overview.collections.total)}
          icon={<HardDrive className="h-4 w-4" />}
        />
        <StatCard
          label={t("overview.indexes", "Индексы")}
          value={formatNumber(overview.collections.indexes)}
          icon={<Server className="h-4 w-4" />}
        />
        <StatCard
          label={t("overview.jobsOk", "Успешных запусков")}
          value={formatNumber(overview.jobs.ok)}
          icon={<CheckCircle2 className="h-4 w-4" />}
        />
        <StatCard
          label={t("overview.jobsFailed", "Ошибки запусков")}
          value={formatNumber(overview.jobs.failed)}
          icon={<CircleAlert className="h-4 w-4" />}
        />
      </div>

      {/* Пустые состояния и графики */}
      {noDocuments || noIndexes ? (
        <div className="space-y-6">
          {noDocuments ? (
            <EmptyState
              icon={<FileText className="h-6 w-6" />}
              title={t("overview.noDocuments", "Нет загруженных документов")}
              description={t("overview.noDocumentsDesc", "Загрузите документы, чтобы начать извлечение текста и индексацию.")}
              action={
                <LinkButton to="/documents" variant="default">
                  {t("overview.uploadDocs", "Загрузить документы")}
                </LinkButton>
              }
            />
          ) : null}
          {noIndexes ? (
            <EmptyState
              icon={<Database className="h-6 w-6" />}
              title={t("overview.noIndexes", "Индексы ещё не созданы")}
              description={t("overview.noIndexesDesc", "Запустите индексацию, чтобы создать векторные индексы и увидеть статистику чанков.")}
              action={
                <LinkButton to="/indexing" variant="default">
                  {t("overview.goIndexing", "К индексации")}
                </LinkButton>
              }
            />
          ) : null}
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>{t("overview.chartChunksByStrategy", "Чанки по стратегиям")}</CardTitle>
            </CardHeader>
            <CardContent>
              {chunkStrategyData.length === 0 ? (
                <EmptyState
                  icon={<Database className="h-6 w-6" />}
                  title={t("overview.noChartData", "Нет данных")}
                  description={t("overview.noChartDataDesc", "Создайте индексы, чтобы увидеть статистику по стратегиям.")}
                />
              ) : (
                <ColumnChart
                  data={chunkStrategyData}
                  keys={[{ key: "value", name: t("overview.chunksCount", "Чанки") }]}
                />
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{t("overview.chartSizeHistogram", "Распределение размеров чанков")}</CardTitle>
            </CardHeader>
            <CardContent>
              {overview.charts.size_histogram.length === 0 ? (
                <EmptyState
                  icon={<FileText className="h-6 w-6" />}
                  title={t("overview.noChartData", "Нет данных")}
                  description={t("overview.noChartDataDesc", "Создайте индексы, чтобы увидеть распределение размеров чанков.")}
                />
              ) : (
                <HistogramChart data={overview.charts.size_histogram} unit={t("overview.chunksHistUnit", "чанков")} />
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{t("overview.chartLastDurations", "Длительность последних индексаций")}</CardTitle>
            </CardHeader>
            <CardContent>
              {lastDurations.length === 0 ? (
                <EmptyState
                  icon={<History className="h-6 w-6" />}
                  title={t("overview.noChartData", "Нет данных")}
                  description={t("overview.noChartDataDesc", "Завершённые индексации ещё не выполнялись.")}
                />
              ) : (
                <TimingLineChart data={lastDurations} unit={t("overview.durationUnit", "мс")} />
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{t("overview.chartIndexSizes", "Размер индексов")}</CardTitle>
            </CardHeader>
            <CardContent>
              {indexSizeData.length === 0 ? (
                <EmptyState
                  icon={<HardDrive className="h-6 w-6" />}
                  title={t("overview.noChartData", "Нет данных")}
                  description={t("overview.noChartDataDesc", "Создайте индексы, чтобы увидеть их размер.")}
                />
              ) : (
                <ColumnChart
                  data={indexSizeData}
                  keys={[{ key: "value", name: t("overview.bytesName", "Байт") }]}
                />
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Последняя индексация */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="h-4 w-4 text-muted-foreground" />
            {t("overview.lastIndexation", "Последняя индексация")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {overview.jobs.last_indexed_at ? (
            <p className="text-sm font-medium">{formatDate(overview.jobs.last_indexed_at)}</p>
          ) : (
            <p className="text-sm text-muted-foreground">{t("overview.lastIndexationEmpty", "ещё не выполнялась")}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}