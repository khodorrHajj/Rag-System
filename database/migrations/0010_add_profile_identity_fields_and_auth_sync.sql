BEGIN;

CREATE OR REPLACE FUNCTION public.normalize_lebanese_phone(raw_input text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  trimmed_input text;
  digit_string text;
  local_number text;
BEGIN
  IF raw_input IS NULL THEN
    RETURN NULL;
  END IF;

  trimmed_input := btrim(raw_input);
  IF trimmed_input = '' THEN
    RETURN NULL;
  END IF;

  IF left(trimmed_input, 1) = '+' THEN
    digit_string := regexp_replace(substring(trimmed_input FROM 2), '\D', '', 'g');
    IF left(digit_string, 3) <> '961' THEN
      RAISE EXCEPTION 'Invalid Lebanese phone number format';
    END IF;

    local_number := substring(digit_string FROM 4);
  ELSE
    digit_string := regexp_replace(trimmed_input, '\D', '', 'g');

    IF left(digit_string, 5) = '00961' THEN
      local_number := substring(digit_string FROM 6);
    ELSIF left(digit_string, 3) = '961' THEN
      local_number := substring(digit_string FROM 4);
    ELSIF left(digit_string, 1) = '0' THEN
      local_number := substring(digit_string FROM 2);
    ELSE
      local_number := digit_string;
    END IF;
  END IF;

  IF local_number !~ '^\d{7,8}$' THEN
    RAISE EXCEPTION 'Invalid Lebanese phone number format';
  END IF;

  RETURN '+961' || local_number;
END;
$$;

ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS first_name text,
  ADD COLUMN IF NOT EXISTS last_name text,
  ADD COLUMN IF NOT EXISTS phone_number text;

UPDATE public.profiles
SET phone_number = public.normalize_lebanese_phone(phone_number)
WHERE phone_number IS NOT NULL
  AND btrim(phone_number) <> ''
  AND phone_number !~ '^\+961\d{7,8}$';

ALTER TABLE public.profiles
  DROP CONSTRAINT IF EXISTS profiles_phone_number_format_check;

ALTER TABLE public.profiles
  ADD CONSTRAINT profiles_phone_number_format_check
  CHECK (phone_number IS NULL OR phone_number ~ '^\+961\d{7,8}$');

CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_phone_number_unique
  ON public.profiles (phone_number)
  WHERE phone_number IS NOT NULL;

COMMENT ON COLUMN public.profiles.phone_number IS
'Normalized Lebanese phone number stored in +961 format and enforced as unique when present.';

CREATE OR REPLACE FUNCTION public.handle_auth_user_profile_sync()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
  metadata jsonb;
  profile_first_name text;
  profile_last_name text;
  profile_full_name text;
  profile_phone text;
BEGIN
  metadata := COALESCE(NEW.raw_user_meta_data, '{}'::jsonb);
  profile_first_name := NULLIF(btrim(COALESCE(metadata ->> 'first_name', '')), '');
  profile_last_name := NULLIF(btrim(COALESCE(metadata ->> 'last_name', '')), '');
  profile_full_name := NULLIF(btrim(COALESCE(metadata ->> 'full_name', '')), '');

  IF profile_full_name IS NULL THEN
    profile_full_name := NULLIF(btrim(CONCAT_WS(' ', profile_first_name, profile_last_name)), '');
  END IF;

  IF NULLIF(btrim(COALESCE(metadata ->> 'phone_number', '')), '') IS NULL THEN
    profile_phone := NULL;
  ELSE
    profile_phone := public.normalize_lebanese_phone(metadata ->> 'phone_number');
  END IF;

  INSERT INTO public.profiles (
    id,
    email,
    full_name,
    first_name,
    last_name,
    phone_number,
    created_at,
    updated_at
  )
  VALUES (
    NEW.id,
    NEW.email,
    profile_full_name,
    profile_first_name,
    profile_last_name,
    profile_phone,
    COALESCE(NEW.created_at, timezone('utc', now())),
    timezone('utc', now())
  )
  ON CONFLICT (id) DO UPDATE
  SET email = EXCLUDED.email,
      full_name = EXCLUDED.full_name,
      first_name = EXCLUDED.first_name,
      last_name = EXCLUDED.last_name,
      phone_number = EXCLUDED.phone_number,
      updated_at = timezone('utc', now());

  RETURN NEW;
END;
$$;

DO $$
BEGIN
  IF to_regclass('auth.users') IS NOT NULL THEN
    EXECUTE 'DROP TRIGGER IF EXISTS on_auth_user_profile_sync ON auth.users';
    EXECUTE $trigger$
      CREATE TRIGGER on_auth_user_profile_sync
      AFTER INSERT OR UPDATE OF email, raw_user_meta_data
      ON auth.users
      FOR EACH ROW
      EXECUTE FUNCTION public.handle_auth_user_profile_sync()
    $trigger$;

    INSERT INTO public.profiles (
      id,
      email,
      full_name,
      first_name,
      last_name,
      phone_number,
      created_at,
      updated_at
    )
    SELECT
      users.id,
      users.email,
      NULLIF(
        btrim(
          COALESCE(users.raw_user_meta_data ->> 'full_name', CONCAT_WS(
            ' ',
            NULLIF(btrim(COALESCE(users.raw_user_meta_data ->> 'first_name', '')), ''),
            NULLIF(btrim(COALESCE(users.raw_user_meta_data ->> 'last_name', '')), '')
          ))
        ),
        ''
      ) AS full_name,
      NULLIF(btrim(COALESCE(users.raw_user_meta_data ->> 'first_name', '')), '') AS first_name,
      NULLIF(btrim(COALESCE(users.raw_user_meta_data ->> 'last_name', '')), '') AS last_name,
      CASE
        WHEN NULLIF(btrim(COALESCE(users.raw_user_meta_data ->> 'phone_number', '')), '') IS NULL THEN NULL
        ELSE public.normalize_lebanese_phone(users.raw_user_meta_data ->> 'phone_number')
      END AS phone_number,
      COALESCE(users.created_at, timezone('utc', now())) AS created_at,
      timezone('utc', now()) AS updated_at
    FROM auth.users AS users
    ON CONFLICT (id) DO UPDATE
    SET email = EXCLUDED.email,
        full_name = EXCLUDED.full_name,
        first_name = EXCLUDED.first_name,
        last_name = EXCLUDED.last_name,
        phone_number = EXCLUDED.phone_number,
        updated_at = timezone('utc', now());
  END IF;
END;
$$;

COMMIT;
