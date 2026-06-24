BEGIN;

ALTER TABLE public.evaluation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evaluation_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY evaluation_runs_select_own
  ON public.evaluation_runs
  FOR SELECT
  USING (triggered_by_user_id = public.current_app_user_id());

CREATE POLICY evaluation_runs_insert_own
  ON public.evaluation_runs
  FOR INSERT
  WITH CHECK (triggered_by_user_id = public.current_app_user_id());

CREATE POLICY evaluation_runs_update_own
  ON public.evaluation_runs
  FOR UPDATE
  USING (triggered_by_user_id = public.current_app_user_id())
  WITH CHECK (triggered_by_user_id = public.current_app_user_id());

CREATE POLICY evaluation_runs_delete_own
  ON public.evaluation_runs
  FOR DELETE
  USING (triggered_by_user_id = public.current_app_user_id());

CREATE POLICY evaluation_results_select_via_owned_run
  ON public.evaluation_results
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM public.evaluation_runs AS er
      WHERE er.id = evaluation_results.run_id
        AND er.triggered_by_user_id = public.current_app_user_id()
    )
  );

CREATE POLICY evaluation_results_insert_via_owned_run
  ON public.evaluation_results
  FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.evaluation_runs AS er
      WHERE er.id = evaluation_results.run_id
        AND er.triggered_by_user_id = public.current_app_user_id()
    )
  );

CREATE POLICY evaluation_results_update_via_owned_run
  ON public.evaluation_results
  FOR UPDATE
  USING (
    EXISTS (
      SELECT 1
      FROM public.evaluation_runs AS er
      WHERE er.id = evaluation_results.run_id
        AND er.triggered_by_user_id = public.current_app_user_id()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.evaluation_runs AS er
      WHERE er.id = evaluation_results.run_id
        AND er.triggered_by_user_id = public.current_app_user_id()
    )
  );

CREATE POLICY evaluation_results_delete_via_owned_run
  ON public.evaluation_results
  FOR DELETE
  USING (
    EXISTS (
      SELECT 1
      FROM public.evaluation_runs AS er
      WHERE er.id = evaluation_results.run_id
        AND er.triggered_by_user_id = public.current_app_user_id()
    )
  );

COMMIT;
