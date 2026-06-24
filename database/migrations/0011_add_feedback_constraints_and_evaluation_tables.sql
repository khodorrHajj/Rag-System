BEGIN;

ALTER TABLE public.feedback
  DROP CONSTRAINT IF EXISTS feedback_rating_check;

ALTER TABLE public.feedback
  ADD CONSTRAINT feedback_rating_check
  CHECK (rating IN ('positive', 'negative'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_user_message_unique
  ON public.feedback (user_id, message_id);

CREATE TABLE IF NOT EXISTS public.evaluation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  triggered_by_user_id uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  run_mode text NOT NULL,
  case_count integer NOT NULL CHECK (case_count >= 0),
  passed_count integer NOT NULL CHECK (passed_count >= 0),
  created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
  CONSTRAINT evaluation_runs_mode_check
    CHECK (run_mode IN ('single', 'named', 'all'))
);

CREATE TABLE IF NOT EXISTS public.evaluation_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES public.evaluation_runs(id) ON DELETE CASCADE,
  case_name text,
  question text NOT NULL,
  document_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  expected_answer_contains jsonb NOT NULL DEFAULT '[]'::jsonb,
  expected_source_file text,
  expected_page_number integer,
  retrieval_passed boolean NOT NULL,
  retrieved_source_match boolean NOT NULL,
  expected_terms_found jsonb NOT NULL DEFAULT '{}'::jsonb,
  expected_terms_passed boolean NOT NULL,
  answer_generated boolean NOT NULL,
  citations_present boolean NOT NULL,
  latency_ms integer NOT NULL CHECK (latency_ms >= 0),
  answer_preview text,
  created_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX IF NOT EXISTS idx_evaluation_runs_created_at
  ON public.evaluation_runs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_evaluation_results_run_id
  ON public.evaluation_results (run_id);

COMMIT;
