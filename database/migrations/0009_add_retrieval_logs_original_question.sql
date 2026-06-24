ALTER TABLE public.retrieval_logs
ADD COLUMN IF NOT EXISTS original_question text NULL;
