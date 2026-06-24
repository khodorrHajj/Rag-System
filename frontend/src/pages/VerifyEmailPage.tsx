import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";
import { supabase } from "../lib/supabase";

const EMAIL_VERIFICATION_STORAGE_KEY = "rag-document-assistant:pending-verification-email";

type VerifyLocationState = {
  email?: string;
};

export function VerifyEmailPage() {
  const { isConfigured, session } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pendingEmail = useMemo(() => {
    const state = location.state as VerifyLocationState | null;
    if (state?.email) {
      return state.email;
    }

    if (typeof window === "undefined") {
      return null;
    }

    return window.sessionStorage.getItem(EMAIL_VERIFICATION_STORAGE_KEY);
  }, [location.state]);

  useEffect(() => {
    if (!session) {
      return;
    }

    if (typeof window !== "undefined") {
      window.sessionStorage.removeItem(EMAIL_VERIFICATION_STORAGE_KEY);
    }

    void navigate("/chat", { replace: true });
  }, [navigate, session]);

  useEffect(() => {
    if (!supabase || session) {
      return;
    }

    const authClient = supabase;
    const intervalId = window.setInterval(() => {
      void authClient.auth.getSession();
    }, 2500);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [session]);

  async function checkVerificationNow() {
    if (!supabase) {
      return;
    }

    setChecking(true);
    setError(null);

    const { data, error: sessionError } = await supabase.auth.getSession();
    if (sessionError) {
      setError("We couldn't check verification status just now. Try again in a moment.");
    } else if (data.session) {
      if (typeof window !== "undefined") {
        window.sessionStorage.removeItem(EMAIL_VERIFICATION_STORAGE_KEY);
      }
      void navigate("/chat", { replace: true });
    } else {
      setError("Your email is not verified yet. Open the link in the email we sent, then come back here.");
    }

    setChecking(false);
  }

  return (
    <main className="auth-page">
      <section className="auth-card auth-card--centered">
        <div className="auth-card__intro">
          <p className="auth-card__eyebrow">Verify your email</p>
          <h1>Waiting for confirmation</h1>
          <p>
            {pendingEmail
              ? `We sent a verification link to ${pendingEmail}.`
              : "We sent a verification link to your email address."}
          </p>
        </div>

        {!isConfigured ? (
          <div className="alert alert--warning">
            Supabase Auth is not configured for this frontend yet.
          </div>
        ) : null}

        {error ? <div className="alert alert--warning">{error}</div> : null}

        <div className="verification-wait" aria-live="polite">
          <div className="verification-wait__spinner" aria-hidden="true" />
          <p className="verification-wait__title">Checking for verification</p>
          <p className="verification-wait__copy">Keep this page open.</p>
        </div>

        <div className="button-row">
          <button
            className="button button--primary"
            disabled={!isConfigured || checking}
            onClick={() => void checkVerificationNow()}
            type="button"
          >
            {checking ? "Checking..." : "I verified my email"}
          </button>
          <Link className="button button--ghost" to="/login">
            Back to sign in
          </Link>
        </div>
      </section>
    </main>
  );
}
