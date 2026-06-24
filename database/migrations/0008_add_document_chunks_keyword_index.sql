BEGIN;

CREATE INDEX IF NOT EXISTS idx_document_chunks_keyword_search
  ON public.document_chunks
  USING gin (
    (
      setweight(to_tsvector('english', coalesce(content, '')), 'A') ||
      setweight(to_tsvector('english', coalesce(section_title, '')), 'B') ||
      setweight(to_tsvector('english', coalesce(subsection_title, '')), 'B')
    )
  );

COMMENT ON INDEX public.idx_document_chunks_keyword_search IS
'GIN expression index for tenant-scoped keyword retrieval over chunk content and section metadata.';

COMMIT;
