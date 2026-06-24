BEGIN;

DROP INDEX IF EXISTS public.idx_document_chunks_embedding_cosine;

ALTER TABLE public.document_chunks
  ALTER COLUMN embedding TYPE vector(384);

COMMENT ON COLUMN public.document_chunks.embedding IS
'Embeddings stored with sentence-transformers/all-MiniLM-L6-v2 using vector(384). Indexing and query embedding must use the same model and dimension.';

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_cosine
  ON public.document_chunks
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

COMMENT ON INDEX public.idx_document_chunks_embedding_cosine IS
'IVFFlat cosine index for 384-dimensional all-MiniLM-L6-v2 embeddings. Tune lists/probes after corpus size and retrieval latency targets are known.';

COMMIT;
