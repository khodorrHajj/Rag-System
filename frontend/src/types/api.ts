export type CurrentUser = {
  user_id: string;
  email: string | null;
  role: string | null;
  is_admin: boolean;
  can_access_developer_tools: boolean;
};

export type FeedbackRating = "positive" | "negative";

export type DocumentStatus =
  | "uploaded"
  | "queued"
  | "processing"
  | "parsed"
  | "chunked"
  | "indexed"
  | "failed"
  | "deleted";

export type DocumentSummary = {
  document_id: string;
  original_filename: string;
  safe_filename: string;
  file_type: string;
  file_size_bytes: number;
  status: DocumentStatus;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
};

export type DocumentDetail = DocumentSummary & {
  deleted_at: string | null;
};

export type DocumentUploadResponse = {
  document_id: string;
  status: DocumentStatus;
};

export type DocumentDeleteResponse = {
  document_id: string;
  status: DocumentStatus;
};

export type ChatSessionSummary = {
  session_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
};

export type ChatSessionListResponse = {
  sessions: ChatSessionSummary[];
};

export type ChatSessionDeleteResponse = {
  session_id: string;
  deleted: boolean;
};

export type ChatSource = {
  source_number: number;
  chunk_id: string;
  document_id: string;
  source_file: string;
  page_number: number | null;
  section_title: string | null;
  subsection_title: string | null;
  chunk_index: number;
  score: number;
};

export type ChatMessageCitation = {
  source_number: number;
  chunk_id: string;
  document_id: string;
  source_file: string;
  page_number: number | null;
  section_title: string | null;
  similarity_score: number | null;
};

export type ChatMessageRecord = {
  message_id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  model_used: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  estimated_cost: number | null;
  created_at: string;
  citations: ChatMessageCitation[];
};

export type ChatMessageListResponse = {
  session_id: string;
  messages: ChatMessageRecord[];
};

export type RetrievalDebugInfo = {
  candidate_count: number;
  vector_candidate_count: number;
  keyword_candidate_count: number;
  top_k: number;
  candidate_k: number;
  threshold: number | null;
  latency_ms: number;
  vector_weight: number;
  keyword_weight: number;
  document_filter_count: number;
};

export type ChatDebugChunk = {
  chunk_id: string;
  document_id: string;
  source_file: string;
  section_title: string | null;
  subsection_title: string | null;
  combined_score: number;
  vector_score: number | null;
  keyword_score: number | null;
  content_preview: string;
};

export type ChatDebugInfo = {
  original_question: string;
  retrieval_query: string;
  history_used_for_rewrite: boolean;
  retrieval: RetrievalDebugInfo;
  chunks: ChatDebugChunk[];
};

export type ChatResponse = {
  session_id: string;
  answer: string;
  sources: ChatSource[];
  model_used: string | null;
  retrieval_passed: boolean;
  user_message: ChatMessageRecord | null;
  assistant_message: ChatMessageRecord | null;
  debug: ChatDebugInfo | null;
};

export type ChatConnectedEvent = {
  type: "chat.connected" | "chat.pong";
};

export type ChatSessionUpsertEvent = {
  type: "chat.session.upsert";
  session: ChatSessionSummary;
};

export type ChatSessionDeletedEvent = {
  type: "chat.session.deleted";
  session_id: string;
};

export type ChatMessageCreatedEvent = {
  type: "chat.message.created";
  session_id: string;
  message: ChatMessageRecord;
};

export type ChatRealtimeEvent =
  | ChatConnectedEvent
  | ChatSessionUpsertEvent
  | ChatSessionDeletedEvent
  | ChatMessageCreatedEvent;

export type SendChatMessagePayload = {
  session_id?: string;
  question: string;
  document_ids?: string[];
  debug?: boolean;
};

export type FeedbackRecord = {
  feedback_id: string;
  user_id: string;
  message_id: string;
  rating: FeedbackRating;
  comment: string | null;
  created_at: string;
  user_email: string | null;
};

export type FeedbackListResponse = {
  feedback: FeedbackRecord[];
};

export type SubmitFeedbackPayload = {
  message_id: string;
  rating: FeedbackRating;
  comment?: string;
};

export type EvaluationCase = {
  case_name?: string;
  question: string;
  document_ids?: string[];
  expected_answer_contains?: string[];
  expected_source_file?: string | null;
  expected_page_number?: number | null;
};

export type EvaluationRunRequest = {
  run_all?: boolean;
  case_name?: string;
  case?: EvaluationCase;
};

export type EvaluationResultRecord = {
  result_id: string;
  run_id: string;
  case_name: string | null;
  question: string;
  document_ids: string[];
  retrieval_passed: boolean;
  retrieved_source_match: boolean;
  expected_terms_found: Record<string, boolean>;
  expected_terms_passed: boolean;
  answer_generated: boolean;
  citations_present: boolean;
  latency_ms: number;
  expected_source_file: string | null;
  expected_page_number: number | null;
  answer_preview: string | null;
  created_at: string;
};

export type EvaluationRunResponse = {
  run_id: string;
  run_mode: string;
  case_count: number;
  passed_count: number;
  created_at: string;
  results: EvaluationResultRecord[];
};

export type EvaluationResultsListResponse = {
  runs: EvaluationRunResponse[];
};

export type DeveloperMetrics = {
  indexed_documents: number;
  total_chunks: number;
  low_confidence_retrievals: number;
  failed_indexing_jobs: number;
  positive_feedback: number;
  negative_feedback: number;
  average_retrieval_latency_ms: number | null;
  model_fallback_count: number;
};

export type RecentRetrievalLog = {
  log_id: string;
  user_id: string;
  user_email: string | null;
  query: string;
  original_question: string | null;
  top_k: number;
  threshold: number | null;
  latency_ms: number | null;
  retrieved_chunk_count: number;
  created_at: string;
};

export type RecentAuditLog = {
  log_id: string;
  user_id: string | null;
  user_email: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  metadata: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
};

export type DeveloperDashboardResponse = {
  metrics: DeveloperMetrics;
  recent_retrieval_logs: RecentRetrievalLog[];
  recent_audit_logs: RecentAuditLog[];
  recent_feedback: FeedbackRecord[];
  recent_evaluations: EvaluationRunResponse[];
};
