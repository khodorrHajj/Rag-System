BEGIN;

CREATE INDEX IF NOT EXISTS idx_documents_user_status
  ON public.documents (user_id, status);

CREATE INDEX IF NOT EXISTS idx_document_chunks_user_document
  ON public.document_chunks (user_id, document_id);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user
  ON public.chat_sessions (user_id);

CREATE INDEX IF NOT EXISTS idx_chat_messages_user_session
  ON public.chat_messages (user_id, session_id);

CREATE INDEX IF NOT EXISTS idx_message_citations_message
  ON public.message_citations (message_id);

CREATE INDEX IF NOT EXISTS idx_retrieval_logs_user_created_at
  ON public.retrieval_logs (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_user_created_at
  ON public.audit_logs (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_permissions_document_permitted_user
  ON public.document_permissions (document_id, permitted_user_id);

CREATE INDEX IF NOT EXISTS idx_document_permissions_owner
  ON public.document_permissions (owner_user_id);

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_cosine
  ON public.document_chunks
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

COMMENT ON INDEX public.idx_document_chunks_embedding_cosine IS
'IVFFlat cosine index for future semantic retrieval. Tune lists/probes after the embedding model and corpus size are finalized.';

COMMIT;

