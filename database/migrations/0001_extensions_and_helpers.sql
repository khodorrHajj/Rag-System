BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = timezone('utc', now());
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.current_app_user_id()
RETURNS uuid
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  resolved_user_id uuid;
  jwt_sub text;
  local_user_id text;
BEGIN
  IF to_regprocedure('auth.uid()') IS NOT NULL THEN
    EXECUTE 'SELECT auth.uid()' INTO resolved_user_id;
    RETURN resolved_user_id;
  END IF;

  jwt_sub := current_setting('request.jwt.claim.sub', true);
  IF jwt_sub IS NOT NULL AND jwt_sub <> '' THEN
    RETURN jwt_sub::uuid;
  END IF;

  local_user_id := current_setting('app.current_user_id', true);
  IF local_user_id IS NOT NULL AND local_user_id <> '' THEN
    RETURN local_user_id::uuid;
  END IF;

  RETURN NULL;
END;
$$;

COMMENT ON FUNCTION public.current_app_user_id() IS
'Returns auth.uid() when Supabase auth is available, otherwise falls back to request.jwt.claim.sub or app.current_user_id for local policy testing.';

COMMIT;

