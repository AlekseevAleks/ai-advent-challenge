/** Клиент REST API backend со строгой типизацией и единой обработкой ошибок. */

import type {
  AnswerConfigFields,
  AppSettings,
  ChatConversation,
  ChatResponse,
  ChatTaskState,
  GroundedEvalRun,
  ChunksPage,
  Collection,
  ComparisonOut,
  DocumentOut,
  DocumentText,
  EvalDataset,
  EvalItem,
  EvalRun,
  EvalRunRequest,
  ExperimentItem,
  FilterResponse,
  Health,
  HistoryFilters,
  IndexStats,
  JobProgress,
  JobRequestPayload,
  JobSummary,
  OllamaModelInfo,
  OllamaStatus,
  OllamaTest,
  OverviewStats,
  QueryRewriteResponse,
  RagAnswerResult,
  RagSearchResult,
  RerankResponse,
  RerankersStatusResponse,
  RetrievalConfigFields,
  SearchRequest,
  SearchResponse,
  SettingsPatch,
  Strategy,
  UploadResponse,
} from "../types/api";

export class ApiError extends Error {
  status: number;
  code?: string;
  details?: unknown;

  constructor(status: number, detail: string, code?: string, details?: unknown) {
    super(detail);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const BASE = (import.meta.env?.VITE_API_BASE as string | undefined) || "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${BASE}${path}`, options);
  } catch {
    throw new ApiError(0, "Нет соединения с backend. Проверьте, что сервер запущен (uvicorn).");
  }
  if (resp.status === 204) {
    return undefined as T;
  }
  let payload: unknown = null;
  const contentType = resp.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      payload = await resp.json();
    } catch {
      payload = null;
    }
  }
  if (!resp.ok) {
    const err = payload as { detail?: unknown; code?: string; details?: unknown } | null;
    const detail = typeof err?.detail === "string" ? err.detail : `Ошибка HTTP ${resp.status}`;
    throw new ApiError(resp.status, detail, err?.code, err?.details);
  }
  return payload as T;
}

function json(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

// ---------------------------------------------------------------------------
// Система и Ollama
// ---------------------------------------------------------------------------

export const getHealth = () => request<Health>("/health");
export const getOverview = () => request<OverviewStats>("/stats/overview");
export const getOllamaStatus = () => request<OllamaStatus>("/ollama/status");
export const testOllama = () => request<OllamaTest>("/ollama/test", json("POST"));
export const listOllamaModels = () => request<{ ollama_url: string; available: boolean; models: OllamaModelInfo[]; message: string }>("/ollama/models");

// ---------------------------------------------------------------------------
// Документы
// ---------------------------------------------------------------------------

export const listDocuments = () => request<DocumentOut[]>("/documents");
export const getDocument = (id: string) => request<DocumentOut>(`/documents/${id}`);
export const getDocumentText = (id: string, preview = 0) =>
  request<DocumentText>(`/documents/${id}/text?preview=${preview}`);
export const deleteDocument = (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" });
export const extractDocument = (id: string) => request<DocumentOut>(`/documents/${id}/extract`, json("POST"));

export async function uploadDocuments(files: File[]): Promise<UploadResponse> {
  const form = new FormData();
  for (const f of files) {
    form.append("files", f, f.name);
  }
  return request<UploadResponse>("/documents/upload", { method: "POST", body: form });
}

export const uploadDemoDocuments = () => request<UploadResponse>("/documents/demo", json("POST"));

// ---------------------------------------------------------------------------
// Индексация (задания)
// ---------------------------------------------------------------------------

export const createIndexJob = (payload: JobRequestPayload) =>
  request<{ job_id: string; status: string; detail: string }>("/indexing/jobs", json("POST", payload));

export const listJobs = (limit = 100) => request<{ jobs: JobSummary[]; total: number }>(`/indexing/jobs?limit=${limit}`);
export const getJob = (jobId: string) => request<JobProgress>(`/indexing/jobs/${jobId}`);
export const getJobResult = (jobId: string) => request<Record<string, unknown>>(`/indexing/jobs/${jobId}/result`);
export const cancelJob = (jobId: string) => request<{ job_id: string; cancel_requested: boolean; message: string }>(
  `/indexing/jobs/${jobId}/cancel`, json("POST"),
);

// ---------------------------------------------------------------------------
// Коллекции и индексы
// ---------------------------------------------------------------------------

export const listCollections = () => request<Collection[]>("/collections");
export const createCollection = (name: string, description = "") =>
  request<Collection>("/collections", json("POST", { name, description }));
export const getCollection = (id: string) => request<Collection>(`/collections/${id}`);
export const deleteCollection = (id: string) => request<void>(`/collections/${id}`, { method: "DELETE" });
export const listCollectionIndexes = (collectionId: string) => request<unknown[]>(`/collections/${collectionId}/indexes`);
export const getIndexStats = (indexId: string) => request<IndexStats>(`/indexes/${indexId}/stats`);
export const getIndexChunks = (indexId: string, limit = 50, offset = 0) =>
  request<ChunksPage>(`/indexes/${indexId}/chunks?limit=${limit}&offset=${offset}`);
export const deleteIndex = (indexId: string) => request<void>(`/indexes/${indexId}`, { method: "DELETE" });

// ---------------------------------------------------------------------------
// Поиск, сравнение, история, настройки
// ---------------------------------------------------------------------------

export const search = (req: SearchRequest) => request<SearchResponse>("/search", json("POST", req));
export const getComparison = (collectionId?: string) =>
  request<ComparisonOut>(collectionId ? `/comparison/${collectionId}` : "/comparison");
export const getHistory = (filters: HistoryFilters = {}, limit = 100) => {
  const qs = new URLSearchParams();
  if (filters.status) qs.set("status", filters.status);
  if (filters.collection_id) qs.set("collection_id", filters.collection_id);
  if (filters.strategy) qs.set("strategy", filters.strategy);
  if (filters.date_from) qs.set("date_from", filters.date_from);
  if (filters.date_to) qs.set("date_to", filters.date_to);
  qs.set("limit", String(limit));
  return request<{ jobs: JobSummary[]; total: number }>(`/history?${qs.toString()}`);
};
export const getHistoryJob = (jobId: string) => request<JobSummary>(`/history/${jobId}`);
export const getSettings = () => request<AppSettings>("/settings");
export const patchSettings = (patch: SettingsPatch) => request<AppSettings>("/settings", json("PATCH", patch));

// ---------------------------------------------------------------------------
// RAG: reranking & filtering
// ---------------------------------------------------------------------------

export const ragQueryRewrite = (query: string, model?: string) =>
  request<QueryRewriteResponse>("/rag/query-rewrite", json("POST", { query, model }));

export const ragRetrieve = (collection_id: string, strategy: string, query: string, top_k: number) =>
  request<Record<string, unknown>>(
    "/rag/retrieve", json("POST", { collection_id, strategy, query, top_k }),
  );

export const ragFilter = (scores: number[], threshold: number) =>
  request<FilterResponse>("/rag/filter", json("POST", { scores, threshold }));

export const ragRerank = (query: string, documents: string[], reranker: string, baseScores?: number[]) =>
  request<RerankResponse>("/rag/rerank", json("POST", { query, documents, reranker, base_scores: baseScores }));

export const ragSearch = (
  collection_id: string,
  strategy: string,
  query: string,
  config: RetrievalConfigFields,
) => request<RagSearchResult>("/rag/search", json("POST", { collection_id, strategy, query, config }));

export const ragRerankersStatus = () => request<RerankersStatusResponse>("/rag/rerankers/status");

// --- Evaluation ---

export const listEvalDatasets = () => request<EvalDataset[]>("/evaluation/datasets");
export const createEvalDataset = (name: string, description: string, items: EvalItem[]) =>
  request<EvalDataset>("/evaluation/datasets", json("POST", { name, description, items }));
export const getEvalDataset = (id: string) => request<EvalDataset>(`/evaluation/datasets/${id}`);
export const deleteEvalDataset = (id: string) => request<void>(`/evaluation/datasets/${id}`, { method: "DELETE" });
export const seedDemoEvalDataset = () => request<EvalDataset>("/evaluation/datasets/demo", json("POST"));

export const runEvaluation = (datasetId: string, req: EvalRunRequest) =>
  request<EvalRun>(`/evaluation/datasets/${datasetId}/run`, json("POST", req));
export const listEvalRuns = (limit = 50) => request<EvalRun[]>(`/evaluation/runs?limit=${limit}`);
export const getEvalRun = (runId: string) => request<EvalRun>(`/evaluation/runs/${runId}`);
export const exportEvalRun = (runId: string, format: "json" | "csv") =>
  request<Record<string, unknown> | string>(`/evaluation/runs/${runId}/export?format=${format}`);

// --- Эксперименты ---

export const listExperiments = (limit = 200) => request<ExperimentItem[]>(`/experiments?limit=${limit}`);
export const saveExperiment = (payload: {
  name: string;
  query: string;
  config: RetrievalConfigFields;
  collection_id?: string;
  strategy?: string;
  result: RagSearchResult;
}) => request<ExperimentItem>("/experiments", json("POST", payload));
export const getExperiment = (id: string) => request<ExperimentItem>(`/experiments/${id}`);
export const deleteExperiment = (id: string) => request<void>(`/experiments/${id}`, { method: "DELETE" });
export const exportExperiment = (id: string, format: "json" | "csv") =>
  request<Record<string, unknown> | string>(`/experiments/${id}/export?format=${format}`);
export const compareExperiments = (id: string, otherId: string) =>
  request<{ current: ExperimentItem; compared: ExperimentItem; note: string }>(
    `/experiments/${id}/compare?other_id=${otherId}`, json("POST", {}),
  );

export const STRATEGY_LABELS: Record<Strategy, string> = {
  fixed_size: "Fixed-size chunking",
  structural: "Structural chunking",
};
// ---------------------------------------------------------------------------
// Grounded RAG: ответы с источниками и цитатами + оценка
// ---------------------------------------------------------------------------

export const ragAnswer = (
  collection_id: string,
  strategy: string,
  query: string,
  config: AnswerConfigFields,
) => request<RagAnswerResult>("/rag/answer", json("POST", { collection_id, strategy, query, config }));

export const listAnswers = (limit = 100) => request<RagAnswerResult[]>(`/rag/answers?limit=${limit}`);
export const getAnswer = (id: string) => request<RagAnswerResult>(`/rag/answers/${id}`);
export const deleteAnswer = (id: string) => request<void>(`/rag/answers/${id}`, { method: "DELETE" });

export const seedGroundedEvalDataset = () => request<EvalDataset>("/rag/evaluation/dataset", json("POST"));
export const runGroundedEval = (payload: {
  dataset_id: string;
  collection_id?: string;
  strategy?: string;
  base_config: AnswerConfigFields;
  name?: string;
}) => request<GroundedEvalRun>("/rag/evaluation/run", json("POST", payload));
export const listGroundedEvalRuns = (limit = 50) =>
  request<GroundedEvalRun[]>(`/rag/evaluation/runs?limit=${limit}`);
export const getGroundedEvalRun = (id: string) => request<GroundedEvalRun>(`/rag/evaluation/runs/${id}`);

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

export const chatSend = (
  message: string,
  conversation_id?: string | null,
  collection_id?: string,
  strategy?: string,
) => request<ChatResponse>("/chat", json("POST", { conversation_id, message, collection_id, strategy }));

export const chatNew = () => request<{ conversation_id: string }>("/chat/new", json("POST"));
export const chatConversations = () =>
  request<{ id: string; title: string; created_at: string; updated_at: string }[]>("/chat");
export const chatGet = (id: string) => request<ChatConversation>(`/chat/${id}`);
export const chatState = (id: string) => request<ChatTaskState>(`/chat/${id}/state`);
export const chatEvalRun = (scenario: string, collection_id?: string, strategy?: string) =>
  request<Record<string, unknown>>("/chat/evaluation/run", json("POST", { scenario, collection_id, strategy }));
