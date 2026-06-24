import type { Session, User } from "@supabase/supabase-js";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { configureApiClient, getMe } from "../api";
import {
  buildFullName,
  normalizeLebanesePhone,
  toFriendlyAuthError,
  type SignUpPayload,
} from "../lib/auth";
import { clearClientCache, readCachedValue, writeCachedValue } from "../lib/client-cache";
import { isSupabaseConfigured } from "../lib/env";
import { supabase } from "../lib/supabase";
import type { CurrentUser } from "../types/api";

type SignUpResult = {
  requiresEmailConfirmation: boolean;
};

type AuthContextValue = {
  authNotice: string | null;
  canAccessDeveloperTools: boolean;
  clearAuthNotice: () => void;
  currentUser: CurrentUser | null;
  isConfigured: boolean;
  isAdmin: boolean;
  loading: boolean;
  session: Session | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  signUp: (payload: SignUpPayload) => Promise<SignUpResult>;
  user: User | null;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);
const EMAIL_VERIFICATION_STORAGE_KEY = "rag-document-assistant:pending-verification-email";

type AuthProviderProps = {
  children: ReactNode;
};

export function AuthProvider({ children }: AuthProviderProps) {
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(
    () => readCachedValue<CurrentUser>("current-user", 15 * 60 * 1000),
  );
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [authNotice, setAuthNotice] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function initializeAuth() {
      if (!supabase) {
        if (isMounted) {
          setLoading(false);
        }
        return;
      }

      const { data, error } = await supabase.auth.getSession();
      if (!isMounted) {
        return;
      }

      if (error) {
        setAuthNotice("We couldn't restore your session. Please sign in again.");
      }

      setSession(data.session ?? null);
      setLoading(false);
    }

    void initializeAuth();

    if (!supabase) {
      return () => {
        isMounted = false;
      };
    }

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      if (!isMounted) {
        return;
      }

      setSession(nextSession);
      setLoading(false);
    });

    return () => {
      isMounted = false;
      subscription.unsubscribe();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadCurrentUser() {
      if (!session) {
        if (!cancelled) {
          setCurrentUser(null);
        }
        return;
      }

      try {
        const nextCurrentUser = await getMe();
        if (!cancelled) {
          setCurrentUser(nextCurrentUser);
          writeCachedValue("current-user", nextCurrentUser);
        }
      } catch {
        if (!cancelled) {
          setCurrentUser((existingUser) => existingUser);
        }
      }
    }

    void loadCurrentUser();

    return () => {
      cancelled = true;
    };
  }, [session]);

  configureApiClient({
    getAccessToken: async () => {
      if (session?.access_token) {
        return session.access_token;
      }

      if (!supabase) {
        return null;
      }

      const { data, error } = await supabase.auth.getSession();
      if (error) {
        return null;
      }

      return data.session?.access_token ?? null;
    },
    refreshAccessToken: async () => {
      if (!supabase) {
        return null;
      }

      const { data, error } = await supabase.auth.refreshSession();
      if (error) {
        return null;
      }

      return data.session?.access_token ?? null;
    },
    onUnauthorized: async () => {
      if (!supabase) {
        setAuthNotice("Your session expired. Please sign in again.");
        return;
      }

      const { data, error } = await supabase.auth.getSession();
      if (!error && data.session) {
        return;
      }

      setAuthNotice("Your session expired. Please sign in again.");
      await supabase.auth.signOut();
    },
  });

  async function signIn(email: string, password: string): Promise<void> {
    if (!supabase) {
      throw new Error("Supabase Auth is not configured for this frontend.");
    }

    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) {
      throw new Error(toFriendlyAuthError(error.message));
    }

    setAuthNotice(null);
  }

  async function signUp(payload: SignUpPayload): Promise<SignUpResult> {
    if (!supabase) {
      throw new Error("Supabase Auth is not configured for this frontend.");
    }

    const normalizedPhone = normalizeLebanesePhone(payload.phoneNumber);
    if (!normalizedPhone) {
      throw new Error("Enter a valid Lebanese phone number before creating the account.");
    }

    const { data, error } = await supabase.auth.signUp({
      email: payload.email.trim(),
      password: payload.password,
      options: {
        emailRedirectTo:
          typeof window !== "undefined"
            ? `${window.location.origin}/verify-email`
            : undefined,
        data: {
          first_name: payload.firstName.trim(),
          last_name: payload.lastName.trim(),
          full_name: buildFullName(payload.firstName, payload.lastName),
          phone_number: normalizedPhone,
        },
      },
    });

    if (error) {
      throw new Error(toFriendlyAuthError(error.message));
    }

    if (!data.session && typeof window !== "undefined") {
      window.sessionStorage.setItem(
        EMAIL_VERIFICATION_STORAGE_KEY,
        payload.email.trim(),
      );
    }

    setAuthNotice(null);
    return {
      requiresEmailConfirmation: !data.session,
    };
  }

  async function signOut(): Promise<void> {
    if (!supabase) {
      setSession(null);
      return;
    }

    await supabase.auth.signOut();
    if (typeof window !== "undefined") {
      window.sessionStorage.removeItem(EMAIL_VERIFICATION_STORAGE_KEY);
    }
    clearClientCache();
    setCurrentUser(null);
    setAuthNotice(null);
  }

  function clearAuthNotice() {
    setAuthNotice(null);
  }

  const value: AuthContextValue = {
    authNotice,
    canAccessDeveloperTools: currentUser?.can_access_developer_tools ?? false,
    clearAuthNotice,
    currentUser,
    isConfigured: isSupabaseConfigured,
    isAdmin: currentUser?.is_admin ?? false,
    loading,
    session,
    signIn,
    signOut,
    signUp,
    user: session?.user ?? null,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used within an AuthProvider.");
  }

  return value;
}
