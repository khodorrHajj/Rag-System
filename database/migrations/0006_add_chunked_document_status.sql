BEGIN;

ALTER TABLE public.documents
  DROP CONSTRAINT IF EXISTS documents_status_check;

ALTER TABLE public.documents
  ADD CONSTRAINT documents_status_check
  CHECK (
    status IN (
      'uploaded',
      'queued',
      'processing',
      'parsed',
      'chunked',
      'indexed',
      'failed',
      'deleted'
    )
  );

COMMIT;
