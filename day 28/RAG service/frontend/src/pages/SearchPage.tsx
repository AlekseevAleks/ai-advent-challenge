/** Страница «Поиск по индексу»: тестовая проверка качества чанков для RAG. */

import { useEffect, useState } from "react";
import { ArrowLeftRight, Copy, Eye, FileText, Search, X } from "lucide-react";
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
  Progress,
  Select,
  Spinner,
  Textarea,
} from "../components/ui";
import { useToast } from "../components/ui/toast";
import { clamp, formatDate } from "../lib/utils";
import { ApiError, getDocumentText, listCollections, search } from "../services/api";
import type { Chunk, Collection, SearchResponse, SearchResultItem, Strategy } from "../types/api";

/** Человекочитаемая подпись стратегии чанкинга. */
function strategyLabel(s: Strategy): string {
  if (s === "fixed_size") return t("strategy.fixed_size", "Фиксированный размер");
  return t("strategy.structural", "Структурная");
}

/** Подпись диапазона страниц чанка («стр. X–Y») или null, если страницы не известны. */
function pagesLabel(chunk: Chunk): string | null {
  if (!chunk.page_start) return null;
  return `стр. ${chunk.page_start}–${chunk.page_end ?? chunk.page_start}`;
}

/** Извлечение detail из ошибки API (ApiError / Error / неизвестное). */
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

export function SearchPage() {
  const toast = useToast();

  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionsLoading, setCollectionsLoading] = useState(true);
  const [collectionsError, setCollectionsError] = useState<string | null>(null);

  const [collectionId, setCollectionId] = useState("");
  const [strategy, setStrategy] = useState<"" | Strategy>("");
  const [topK, setTopK] = useState(5);
  const [query, setQuery] = useState("");

  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const [docOpen, setDocOpen] = useState(false);
  const [docLoading, setDocLoading] = useState(false);
  const [docTitle, setDocTitle] = useState("");
  const [docText, setDocText] = useState("");
  const [docError, setDocError] = useState<string | null>(null);

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

  const selectedCollection = collections.find((c) => c.id === collectionId);
  const strategyOptions: Strategy[] = selectedCollection ? selectedCollection.strategies : [];

  function handleCollectionChange(value: string) {
    setCollectionId(value);
    setStrategy("");
    setResult(null);
    setSearchError(null);
    setHasSearched(false);
  }

  async function handleSubmit() {
    if (!collectionId) {
      toast.error(
        t("search.validation", "Форма не заполнена"),
        t("search.need_collection", "Выберите коллекцию."),
      );
      return;
    }
    if (!strategy) {
      toast.error(
        t("search.validation", "Форма не заполнена"),
        t("search.need_strategy", "Выберите стратегию."),
      );
      return;
    }
    if (!query.trim()) {
      toast.error(
        t("search.validation", "Форма не заполнена"),
        t("search.need_query", "Введите текст запроса."),
      );
      return;
    }
    setSearching(true);
    setSearchError(null);
    setHasSearched(true);
    try {
      const res = await search({ collection_id: collectionId, strategy, query: query.trim(), top_k: topK });
      setResult(res);
    } catch (err: unknown) {
      setResult(null);
      setSearchError(apiDetail(err));
    } finally {
      setSearching(false);
    }
  }

  async function handleCopy(text: string) {
    const ok = await copyToClipboard(text);
    if (ok) {
      toast.success(t("search.copied", "Скопировано"));
    } else {
      toast.error(t("search.copy_failed", "Не удалось скопировать"));
    }
  }

  function handleExpand(chunkId: string) {
    const next = { ...expanded };
    next[chunkId] = !next[chunkId];
    setExpanded(next);
  }

  async function handleOpenDocument(item: SearchResultItem) {
    if (!item.chunk.document_id) return;
    setDocOpen(true);
    setDocLoading(true);
    setDocError(null);
    setDocTitle(item.chunk.title || item.chunk.document_id);
    setDocText("");
    try {
      const dt = await getDocumentText(item.chunk.document_id, 0);
      setDocLoading(false);
      setDocTitle(item.chunk.title || dt.source || item.chunk.document_id);
      setDocText(dt.text);
    } catch (err: unknown) {
      setDocLoading(false);
      setDocError(apiDetail(err));
    }
  }

  return (
    <div className="space-y-6">
      {/* Заголовок и форма поиска */}
      <Card>
        <CardHeader>
          <CardTitle>{t("search.title", "Поиск по индексу")}</CardTitle>
          <CardDescription>{t("search.description", "Тестовая проверка качества чанков для RAG")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {collectionsError ? (
            <Alert variant="error">
              {t("search.collections_error", "Не удалось загрузить коллекции")}: {collectionsError}
            </Alert>
          ) : null}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Select
              label={t("search.collection", "Коллекция")}
              value={collectionId}
              disabled={collectionsLoading}
              onChange={(e) => handleCollectionChange(e.target.value)}
              hint={
                collectionsLoading
                  ? t("search.collections_loading", "Загрузка коллекций…")
                  : selectedCollection
                    ? `${t("search.collection_created", "Создана")} ${formatDate(selectedCollection.created_at)}`
                    : undefined
              }
            >
              <option value="">{t("search.collection_placeholder", "Выберите коллекцию")}</option>
              {collections.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
            <Select
              label={t("search.strategy", "Стратегия")}
              value={strategy}
              disabled={!selectedCollection}
              onChange={(e) => setStrategy(e.target.value === "" ? "" : (e.target.value as Strategy))}
              hint={!selectedCollection ? t("search.strategy_needs_collection", "Сначала выберите коллекцию") : undefined}
            >
              <option value="">{t("search.strategy_placeholder", "Выберите стратегию")}</option>
              {strategyOptions.map((s) => (
                <option key={s} value={s}>
                  {strategyLabel(s)}
                </option>
              ))}
            </Select>
            <Select
              label={t("search.top_k", "Top-K")}
              value={String(topK)}
              onChange={(e) => setTopK(Number(e.target.value))}
            >
              {Array.from({ length: 20 }, (_, i) => i + 1).map((n) => (
                <option key={n} value={String(n)}>
                  {n}
                </option>
              ))}
            </Select>
          </div>
          <Textarea
            label={t("search.query", "Запрос")}
            rows={3}
            value={query}
            placeholder={t("search.query_placeholder", "Например: как проверить качество чанков для RAG?")}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="flex items-center justify-between gap-3">
            <Button onClick={handleSubmit} loading={searching}>
              <Search className="h-4 w-4" />
              {t("search.submit", "Найти")}
            </Button>
            {searching ? <Spinner label={t("search.searching", "Поиск…")} /> : null}
          </div>
        </CardContent>
      </Card>

      {/* Состояния */}
      {!hasSearched && !searchError ? (
        <Alert variant="info">
          {t(
            "search.hint",
            "Сформулируйте запрос и нажмите «Найти». Результаты ранжируются по cosine similarity между запросом и чанками.",
          )}
        </Alert>
      ) : null}

      {searchError ? <Alert variant="error">{searchError}</Alert> : null}

      {result?.note ? <Alert variant="info">{result.note}</Alert> : null}

      {result && result.results.length === 0 ? (
        <EmptyState
          icon={<FileText className="h-6 w-6" />}
          title={t("search.empty_title", "Ничего не найдено")}
          description={t("search.empty_description", "Попробуйте изменить запрос, стратегию или Top-K.")}
        />
      ) : null}

      {/* Результаты */}
      {result && result.results.length > 0 ? (
        <div className="space-y-3">
          {result.results.map((item) => {
            const isExpanded = expanded[item.chunk.chunk_id] === true;
            const pages = pagesLabel(item.chunk);
            return (
              <Card key={`${item.chunk.chunk_id}-${item.rank}`}>
                <CardContent className="flex items-start gap-4">
                  <div className="flex w-20 shrink-0 flex-col items-center gap-1.5">
                    <span className="text-3xl font-bold leading-none text-muted-foreground">{item.rank}</span>
                    <Progress value={item.score * 100} />
                    <span className="text-[11px] tabular-nums text-muted-foreground">{item.score.toFixed(3)}</span>
                  </div>
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold">{item.chunk.title}</span>
                      {item.chunk.section ? <Badge variant="outline">{item.chunk.section}</Badge> : null}
                      <Badge variant="secondary">{strategyLabel(item.chunk.chunking_strategy)}</Badge>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span className="font-mono">chunk_id: {item.chunk.chunk_id}</span>
                      {pages ? <span className="font-mono">{pages}</span> : null}
                    </div>
                    <p className="text-sm leading-relaxed whitespace-pre-wrap">
                      {isExpanded ? item.chunk.text : clamp(item.chunk.text, 300)}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" variant="ghost" onClick={() => handleExpand(item.chunk.chunk_id)}>
                        {isExpanded ? <X className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        {isExpanded ? t("search.hide", "Скрыть") : t("search.show_more", "Показать полностью")}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => void handleCopy(item.chunk.text)}>
                        <Copy className="h-4 w-4" />
                        {t("search.copy", "Копировать")}
                      </Button>
                      {item.chunk.document_id ? (
                        <Button size="sm" variant="secondary" onClick={() => void handleOpenDocument(item)}>
                          <ArrowLeftRight className="h-4 w-4" />
                          {t("search.open_document", "Перейти к документу")}
                        </Button>
                      ) : null}
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      ) : null}

      {/* Постоянная подсказка про cosine similarity */}
      <Alert variant="info">
        {t(
          "search.cosine_note",
          "Cosine similarity — это оценка векторного сходства, а не гарантированная вероятность правильности ответа",
        )}
      </Alert>

      {/* Диалог с текстом документа */}
      <Dialog
        wide
        open={docOpen}
        onClose={() => setDocOpen(false)}
        title={docTitle}
        description={t("search.document_dialog_description", "Полный текст документа")}
      >
        {docLoading ? (
          <Spinner label={t("search.document_loading", "Загрузка текста документа…")} />
        ) : docError ? (
          <Alert variant="error">{docError}</Alert>
        ) : docText ? (
          <pre className="max-h-[60vh] overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-secondary DEFAULT/20 p-3 text-xs font-mono leading-relaxed">
            {docText}
          </pre>
        ) : null}
      </Dialog>
    </div>
  );
}