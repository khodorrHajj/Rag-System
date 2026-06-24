import { createClient } from "@supabase/supabase-js";

import { frontendEnv, isSupabaseConfigured } from "./env";

export const supabase = isSupabaseConfigured
  ? createClient(frontendEnv.supabaseUrl, frontendEnv.supabaseAnonKey, {
      auth: {
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: true,
      },
    })
  : null;
