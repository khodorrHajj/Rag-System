ALTER TABLE public.message_citations
ADD COLUMN IF NOT EXISTS source_number integer;

WITH ordered_citations AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY message_id
            ORDER BY created_at ASC, id ASC
        ) AS computed_source_number
    FROM public.message_citations
)
UPDATE public.message_citations AS message_citations
SET source_number = ordered_citations.computed_source_number
FROM ordered_citations
WHERE message_citations.id = ordered_citations.id
  AND message_citations.source_number IS NULL;

ALTER TABLE public.message_citations
ALTER COLUMN source_number SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_message_citations_message_id_source_number
    ON public.message_citations (message_id, source_number);
