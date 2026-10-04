/** Клиент REST API backend со строгой типизацией и единой обработкой ошибок. */

import type {
  AppSettings,
  ChunksPage,
  Collection,
  ComparisonOut,
  DocumentOut,
  DocumentText,
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

export const STRATEGY_LABELS: Record<Strategy, string> = {
  fixed_size: "Fixed-size chunking",
  structural: "Structural chunking",
};