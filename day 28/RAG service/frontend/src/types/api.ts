/** Типы данных API (соответствуют Pydantic-схемам backend). */

export type DocumentStatus =
  | "uploaded"
  | "extracting"
  | "ready"
  | "indexing"
  | "indexed"
  | "error";

export interface WarningItem {
  filename?: string;
  message: string;
}

export interface DocumentOut {
  id: string;
  source: string;
  title: string;
  file_type: string;
  file_size: number;
  storage_name: string;
  char_count: number | null;
  page_count: number | null;
  status: DocumentStatus;
  content_hash: string;
  warnings: string[];
  errors: string[];
  created_at: string;
  extracted_at: string | null;
  has_text: boolean;
}

export interface UploadResponse {
  documents: DocumentOut[];
  errors: WarningItem[];
  uploaded: number;
  failed: number;
}

export interface DocumentText {
  id: string;
  source: string;
  text: string;
  char_count: number;
  page_count: number | null;
  warnings: string[];
  truncated: boolean;
}

export type JobStatus = "queued" | "running" | "completed" | "completed_with_errors" | "failed" | "cancelled";

export type Strategy = "fixed_size" | "structural";
export type IndexMode = "new_collection" | "new_index" | "rebuild" | "add";

export interface JobProgress {
  job_id: string;
  status: JobStatus;
  stage: string;
  stage_label: string;
  percent: number;
  document_index: number;
  document_total: number;
  current_document: string | null;
  chunks: number;
  embeddings_done: number;
  errors: number;
  message: string | null;
  elapsed_seconds: number;
  updated_at: string;
  cancel_requested: boolean;
  result: JobResult | null;
  collection_id: string | null;
  collection_name: string | null;
}

export interface JobResultIndex {
  collection_id: string;
  strategy: string;
  index_id: string;
  num_vectors: number;
  num_documents: number;
  action: string;
  size_bytes: number;
  dimension: number;
}

export interface JobResult {
  collection_id: string;
  collection_name: string;
  indexes: JobResultIndex[];
  documents: number;
  chunks: number;
  embeddings_ok: number;
  embeddings_failed: number;
  errors: string[];
  warnings: string[];
  time_chunking_ms: number | null;
  time_embeddings_ms: number | null;
  time_total_ms: number | null;
}

export interface JobSummary {
  job_id: string;
  status: JobStatus;
  mode: string;
  collection_id: string | null;
  collection_name: string | null;
  strategies: string[];
  model: string | null;
  documents: number;
  chunks: number;
  embeddings_ok: number;
  errors: number;
  progress_percent: number;
  message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  result: JobResult | null;
}

export interface IndexConfig {
  index_id: string;
  collection_id: string;
  strategy: Strategy;
  embedding_model: string;
  dimension: number;
  schema_version: number;
  index_version: number;
  num_vectors: number;
  num_documents: number;
  document_ids: string[];
  chunking_params: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  size_bytes: number;
  time_chunking_ms: number | null;
  time_embeddings_ms: number | null;
  time_total_ms: number | null;
  job_id: string | null;
  warnings: string[];
  errors_count: number;
}

export interface Collection {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  strategies: Strategy[];
  indexes: IndexConfig[];
}

export interface Chunk {
  chunk_id: string;
  document_id: string;
  source: string;
  title: string;
  section: string | null;
  text: string;
  chunk_index: number;
  chunking_strategy: Strategy;
  start_offset: number;
  end_offset: number;
  page_start: number | null;
  page_end: number | null;
  char_count: number;
  embedding_model: string;
  collection_id: string;
  index_version: number;
  symbol_type?: string | null;
  symbol_name?: string | null;
  similarity?: number;
  rank?: number;
}

export interface SearchRequest {
  collection_id: string;
  strategy: Strategy;
  query: string;
  top_k: number;
}

export interface SearchResultItem {
  rank: number;
  score: number;
  chunk: Chunk;
}

export interface SearchResponse {
  query: string;
  collection_id: string;
  strategy: Strategy;
  model: string;
  dimension: number;
  n_indexed: number;
  took_ms: number;
  results: SearchResultItem[];
  note: string;
}

export interface ComparisonMetrics {
  documents: number;
  chunks: number;
  mean_chars: number;
  median_chars: number;
  min_chars: number;
  max_chars: number;
  std_chars: number;
  empty_chunks: number;
  index_size_bytes: number;
  time_chunking_ms: number | null;
  time_embeddings_ms: number | null;
  time_total_ms: number | null;
  errors: number;
}

export interface ComparisonOut {
  collection_id: string;
  collection_name: string;
  strategies: Strategy[];
  metrics: Partial<Record<Strategy, ComparisonMetrics>>;
  sizes: Partial<Record<Strategy, number[]>>;
  histogram: Partial<Record<Strategy, Array<{ label: string; count: number }>>>;
  per_document: Partial<Record<Strategy, Array<{ document_id: string; title: string; chunks: number }>>>;
  timings: Partial<Record<Strategy, Record<string, number | null>>>;
  tradeoffs: string[];
}

export interface IndexStats extends IndexConfig {
  chunks: number;
  mean_chars: number;
  median_chars: number;
  min_chars: number;
  max_chars: number;
  std_chars: number;
  empty_chunks: number;
}

export interface ChunksPage {
  chunks: Chunk[];
  total: number;
  index_id: string;
}

export interface OllamaStatus {
  ok: boolean;
  available: boolean;
  version: string | null;
  message: string;
  model: string | null;
  model_available: boolean | null;
  model_dimension: number | null;
  models: string[];
  ollama_url: string;
  error: string | null;
}

export interface OllamaTest {
  ok: boolean;
  step: string;
  message: string;
  ollama_url: string;
  model: string | null;
  dimension: number | null;
  vector_sample: number[] | null;
  vector_finite: boolean | null;
  model_available: boolean;
  pull_command: string | null;
  error: string | null;
}

export interface OllamaModelInfo {
  name: string;
  size: number | null;
  parameter_size: string | null;
  quantization_level: string | null;
  embedding_length: number | null;
  capabilities: string[];
}

export interface AppSettings {
  app_name: string;
  version: string;
  backend: {
    ollama_url: string;
    embedding_model: string;
    embedding_batch_size: number;
    embedding_retries: number;
    ollama_timeout: number;
    ollama_connection_timeout: number;
    max_file_size_mb: number;
    max_files_per_request: number;
    storage_dir: string;
    default_chunk_size: number;
    default_chunk_overlap: number;
    default_structural_max_chunk_size: number;
    default_structural_min_chunk_size: number;
    allowed_extensions: string[];
    query_rewrite_model: string;
    reranker_type: string;
    reranker_model: string;
    default_initial_top_k: number;
    default_final_top_k: number;
    default_similarity_threshold: number;
    answer_model: string;
    default_relevance_threshold: number;
    default_grounding_threshold: number;
    default_min_supporting_chunks: number;
    grounding_similarity_threshold: number;
  };
  ollama: {
    url: string;
    model: string;
    available: boolean;
    model_available: boolean | null;
    dimension: number | null;
    version: string | null;
    message: string;
  };
  storage: {
    dir: string;
    collections_dir: string;
    uploads_dir: string;
    db_path: string;
  };
}

export interface OverviewStats {
  backend_status: string;
  apps: { version: string; name: string; storage_dir: string };
  documents: {
    total: number;
    ready: number;
    indexed: number;
    errors: number;
    pages: number;
    char_count: number;
    file_bytes: number;
    limit_mb: number;
    max_files: number;
  };
  chunks: {
    total: number;
    by_strategy: Array<{ strategy: string; chunks: number }>;
    median_size: number;
    mean_size: number;
    min_size: number;
    max_size: number;
    sample_sizes: number[];
  };
  collections: {
    total: number;
    indexes: number;
    list: Array<{ id: string; name: string }>;
    index_sizes: Array<{ collection_id: string; strategy: string; size_bytes: number }>;
  };
  jobs: {
    total: number;
    ok: number;
    with_errors: number;
    failed: number;
    running: number;
    last_indexed_at: string | null;
    recent: Array<{ job_id: string; status: string; created_at: string; finished_at: string | null; strategies: string[] }>;
    running_jobs: Array<{ job_id: string; status: string; strategies: string[]; message: string | null }>;
  };
  charts: {
    chunks_by_strategy: Record<string, number>;
    size_histogram: Array<{ label: string; count: number }>;
    last_durations: Array<{ job_id: string; label: string; ms: number | null; status: string }>;
    index_sizes: Array<{ collection_id: string; strategy: string; size_bytes: number }>;
  };
}

export interface Health {
  status: string;
  app_name: string;
  version: string;
  storage_dir: string;
}

export interface HistoryFilters {
  status?: string;
  collection_id?: string;
  strategy?: string;
  date_from?: string;
  date_to?: string;
}

export interface SettingsPatch {
  ollama_url?: string;
  embedding_model?: string;
  embedding_batch_size?: number;
  embedding_retries?: number;
  ollama_timeout?: number;
  ollama_connection_timeout?: number;
  max_file_size_mb?: number;
  max_files_per_request?: number;
  default_chunk_size?: number;
  default_chunk_overlap?: number;
  default_structural_max_chunk_size?: number;
  default_structural_min_chunk_size?: number;
  query_rewrite_model?: string;
  reranker_type?: string;
  reranker_model?: string;
  default_initial_top_k?: number;
  default_final_top_k?: number;
  default_similarity_threshold?: number;
}

// ---------------------------------------------------------------------------
// RAG: reranking & filtering
// ---------------------------------------------------------------------------

export type RerankerKind = "heuristic" | "cross_encoder" | "similarity";

export interface RetrievalConfigFields {
  query_rewrite: boolean;
  query_rewrite_model?: string;
  initial_top_k: number;
  final_top_k: number;
  enable_filter: boolean;
  similarity_threshold: number;
  enable_reranker: boolean;
  reranker: RerankerKind;
  reranker_model?: string;
  reranker_query?: "original" | "rewritten";
  deduplicate?: boolean;
  dedup_threshold?: number;
  mmr?: boolean;
  mmr_lambda?: number;
}

export type ChunkFinalStatus =
  | "kept"
  | "filtered"
  | "deduplicated"
  | "mmr_removed"
  | "outside_final_top_k";

export interface RagChunk {
  chunk_id: string;
  document_id: string;
  source: string;
  title: string;
  section: string | null;
  text: string;
  [key: string]: unknown;
  retrieval_rank: number;
  retrieval_score: number;
  filter_score: number;
  passed_filter: boolean;
  deduplicated: boolean;
  mmr_removed: boolean;
  mmr_rank: number | null;
  reranker_score: number | null;
  reranker_rank: number | null;
  final_rank: number | null;
  status: ChunkFinalStatus;
}

export interface RagSearchResult {
  original_query: string;
  rewritten_query: string | null;
  rewrite: { enabled: boolean; model: string | null; latency_ms: number | null };
  retrieval: { initial_top_k: number; candidates: number; strategy: string; collection_id: string; index_id: string | null; latency_ms: number };
  deduplication: { enabled: boolean; threshold: number; before: number; after: number; removed: number; latency_ms: number };
  mmr: { enabled: boolean; lambda: number; applied: boolean; latency_ms: number; note: string | null };
  filtering: { enabled: boolean; threshold: number; passed: number; filtered: number; latency_ms: number; rule: string };
  reranking: { enabled: boolean; reranker: string | null; model: string | null; query_used: string; n_reranked: number; latency_ms: number };
  final: { top_k: number; count: number; results: RagChunk[] };
  items: RagChunk[];
  latency: {
    query_rewrite_ms: number;
    embedding_ms: number;
    retrieval_ms: number;
    filtering_ms: number;
    reranking_ms: number;
    deduplication_ms: number;
    mmr_ms: number;
    total_ms: number;
  };
  config: RetrievalConfigFields;
  note: string;
}

export interface QueryRewriteResponse {
  original_query: string;
  rewritten_query: string;
  model: string;
  latency_ms: number;
}

export interface FilterResponse {
  threshold: number;
  passed: number;
  filtered: number;
  kept_positions: number[];
}

export interface RerankResponse {
  reranker: string;
  model: string | null;
  scores: number[];
  reranked_positions: number[];
}

export interface RerankerStatusInfo {
  reranker: string;
  model: string | null;
  available: boolean;
  reason: string | null;
  install_hint: string | null;
}

export interface RerankersStatusResponse {
  heuristic: RerankerStatusInfo;
  cross_encoder: RerankerStatusInfo;
  similarity: RerankerStatusInfo;
  default_reranker: string;
  default_model: string;
}

// --- Evaluation ---

export interface EvalItem {
  question: string;
  expected_sources: string[];
  expected_sections: string[];
  relevant_chunk_ids: string[];
}

export interface EvalDataset {
  id: string;
  name: string;
  description: string;
  items: EvalItem[];
  created_at: string;
  updated_at: string;
}

export interface EvalRunRequest {
  collection_id?: string;
  index_id?: string;
  strategy?: string;
  modes: string[];
  base_config: RetrievalConfigFields;
  name?: string;
}

export interface EvalRun {
  id: string;
  dataset_id: string;
  name: string;
  status: "queued" | "running" | "completed" | "failed";
  collection_id: string | null;
  index_id: string | null;
  config: { modes: string[]; base_config: RetrievalConfigFields };
  results: Record<string, ModeRunResult> | null;
  metrics: Record<string, ModeMetrics> | null;
  latency: Record<string, Record<string, number>> | null;
  message: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface ModeMetrics {
  k: number;
  hit_at_k: number;
  precision_at_k: number;
  recall_at_k: number;
  mrr: number;
  latency_ms: number;
  questions: number;
  has_ground_truth: boolean;
  errors: number;
}

export interface ModeRunResult {
  mode: string;
  label: string;
  per_question: Array<{
    question: string;
    rewritten_query?: string | null;
    predicted_chunks: string[];
    relevant: string[];
    metrics: Record<string, number> | null;
    error?: string;
  }>;
  metrics: { k: number; questions: number; hit_at_k: number; precision_at_k: number; recall_at_k: number; mrr: number; warning?: string };
  technical: { avg_candidates: number; avg_filtered: number; avg_similarity: number; avg_reranker_score: number | null };
  has_ground_truth: boolean;
  errors: number;
  latency: Record<string, number>;
}

export interface ExperimentItem {
  id: string;
  name: string;
  collection_id: string | null;
  index_id: string | null;
  strategy: string | null;
  query: string;
  run_id: string | null;
  dataset_id: string | null;
  config: RetrievalConfigFields;
  metrics: Record<string, unknown> | null;
  latency: Record<string, number> | null;
  result: RagSearchResult;
  created_at: string;
}

export interface ApiError {
  status: number;
  detail: string;
  code?: string;
  details?: unknown;
}

export interface JobRequestPayload {
  document_ids: string[];
  strategies: Strategy[];
  mode: "new_collection" | "new_index" | "rebuild" | "add";
  collection_id?: string;
  collection_name?: string;
  fixed_size?: { chunk_size: number; overlap: number; unit: "chars" | "tokens" };
  structural?: { max_chunk_size: number; min_chunk_size: number; merge_small_sections: boolean };
  embedding_model?: string;
  embedding_batch_size?: number;
}
// ---------------------------------------------------------------------------
// Grounded RAG: ответы с источниками и цитатами
// ---------------------------------------------------------------------------

export type AnswerStatus = "answered" | "insufficient_context" | "grounding_failed";

export interface AnswerSource {
  source: string;
  section: string | null;
  chunk_id: string;
  title?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  symbol_name?: string | null;
}

export interface AnswerCitation {
  source: string;
  section: string | null;
  chunk_id: string;
  quote: string;
  page_start?: number | null;
  page_end?: number | null;
}

export interface AnswerClaim {
  text: string;
  chunk_ids: string[];
  grounded: boolean;
  grounding_score: number;
}

export interface GroundingInfo {
  grounded: boolean;
  grounding_score: number;
  claims_total: number;
  claims_supported: number;
}

export interface AnswerConfigFields {
  query_rewrite: boolean;
  query_rewrite_model?: string;
  initial_top_k: number;
  final_top_k: number;
  enable_filter: boolean;
  similarity_threshold: number;
  enable_reranker: boolean;
  reranker: RerankerKind;
  reranker_model?: string;
  answer_model?: string;
  answer_relevance_threshold: number;
  grounding_threshold: number;
  min_supporting_chunks: number;
}

export interface RagAnswerResult {
  id?: string;
  status: AnswerStatus;
  answer: string;
  original_query: string;
  rewritten_query: string | null;
  sources: AnswerSource[];
  citations: AnswerCitation[];
  claims: AnswerClaim[];
  grounding: GroundingInfo;
  retrieval: Record<string, unknown>;
  config: AnswerConfigFields;
  latency: Record<string, number>;
}

export interface GroundedEvalQuestionResult {
  question: string;
  expected_sources: string[];
  abstention: boolean;
  status: string;
  answer_excerpt: string;
  error?: string;
  results: {
    answer_present: boolean;
    sources_present: boolean;
    citations_present: boolean;
    citation_valid: boolean;
    source_valid: boolean;
    answer_grounded: boolean;
    unsupported_claims: number;
  };
  sources: AnswerSource[];
  citations: AnswerCitation[];
  claims: AnswerClaim[];
  grounding: GroundingInfo;
  relevance_score?: number | null;
  result: "PASS" | "FAIL" | "INSUFFICIENT_CONTEXT";
  latency?: Record<string, number>;
}

export interface GroundedEvalMetrics {
  questions: number;
  answers_generated: number;
  insufficient_context: number;
  source_coverage: number;
  citation_coverage: number;
  citation_validity: number;
  grounding_accuracy: number;
  abstention_accuracy: number | null;
  source_coverage_ratio: string;
  citation_coverage_ratio: string;
  grounding_ratio: string;
  abstention_ratio: string | null;
  total_citations: number;
}

export interface GroundedEvalRun {
  id: string;
  name: string;
  status: string;
  dataset_id: string | null;
  collection_id: string | null;
  index_id: string | null;
  strategy: string | null;
  config: AnswerConfigFields;
  per_question: GroundedEvalQuestionResult[] | null;
  metrics: GroundedEvalMetrics | null;
  message: string | null;
  created_at: string;
  finished_at: string | null;
}

// ---------------------------------------------------------------------------
// Chat: история + Task Memory + grounded-ответы
// ---------------------------------------------------------------------------

export interface ChatDecision {
  key: string;
  value: string;
  status: "active" | "superseded";
  source: string;
  message_id?: string | null;
  confidence: number;
}

export interface ChatTaskState {
  goal: string;
  constraints: string[];
  defined_terms: { term: string; definition: string }[];
  decisions: ChatDecision[];
  open_questions: string[];
  current_focus: string;
  version: number;
}

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  status: string;
  search_query: string | null;
  sources: AnswerSource[];
  citations: AnswerCitation[];
  retrieval: Record<string, unknown> | null;
  created_at: string;
}

export interface ChatResponse {
  conversation_id: string;
  message_id: string | null;
  status: AnswerStatus;
  answer: string;
  original_query: string;
  search_query: string;
  sources: AnswerSource[];
  citations: AnswerCitation[];
  claims: AnswerClaim[];
  grounding: GroundingInfo;
  retrieval: Record<string, unknown>;
  config: AnswerConfigFields;
  latency: Record<string, number>;
  task_state: ChatTaskState;
}

export interface ChatConversation {
  conversation_id: string;
  messages: ChatMessage[];
  task_state: ChatTaskState;
  created_at: string;
  updated_at: string;
}
