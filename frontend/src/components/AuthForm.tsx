import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";
import { normalizeLebanesePhone, validateSignUpPayload } from "../lib/auth";

type AuthFormProps = {
  mode: "login" | "signup";
};

export function AuthForm({ mode }: AuthFormProps) {
  const { authNotice, clearAuthNotice, isConfigured, signIn, signUp } =
    useAuth();
  const navigate = useNavigate();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isLoginMode = mode === "login";

  useEffect(() => {
    clearAuthNotice();
  }, [clearAuthNotice, mode]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    clearAuthNotice();

    try {
      if (isLoginMode) {
        await signIn(email, password);
      } else {
        if (password !== confirmPassword) {
          setError("Passwords do not match.");
          return;
        }

        const validationMessage = validateSignUpPayload({
          email,
          password,
          firstName,
          lastName,
          phoneNumber,
        });

        if (validationMessage) {
          setError(validationMessage);
          return;
        }

        const result = await signUp({
          email,
          password,
          firstName,
          lastName,
          phoneNumber,
        });

        const normalizedPhone = normalizeLebanesePhone(phoneNumber);
        setSuccess(
          result.requiresEmailConfirmation
            ? `Account created. Email confirmation is enabled for this project, so check your inbox before signing in. Your phone will be stored as ${normalizedPhone}.`
            : `Account created. You can continue into the workspace now. Your phone will be stored as ${normalizedPhone}.`,
        );

        if (result.requiresEmailConfirmation) {
          void navigate("/verify-email", {
            replace: true,
            state: { email: email.trim() },
          });
        } else {
          void navigate("/chat", { replace: true });
        }
      }
    } catch (submissionError) {
      setError(
        submissionError instanceof Error
          ? submissionError.message
          : "Authentication failed. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="auth-card">
      <div className="auth-card__intro">
        <p className="auth-card__eyebrow">
          {isLoginMode ? "Welcome back" : "Create your workspace"}
        </p>
        <h1>
          {isLoginMode
            ? "Sign in to RAG Document Assistant"
            : "Create an account"}
        </h1>
        <p>
          {isLoginMode
            ? "Sign in to chat with your indexed files."
            : "Use your name, email, and Lebanese phone number."}
        </p>
      </div>

      {!isConfigured ? (
        <div className="alert alert--warning">
          Supabase Auth is not configured for this frontend. Add
          <code> VITE_SUPABASE_URL </code>
          and either
          <code> VITE_SUPABASE_PUBLISHABLE_KEY </code>
          or
          <code> VITE_SUPABASE_ANON_KEY </code>
          before signing in.
        </div>
      ) : null}

      {authNotice ? (
        <div className="alert alert--warning">{authNotice}</div>
      ) : null}
      {error ? <div className="alert alert--error">{error}</div> : null}
      {success ? <div className="alert alert--success">{success}</div> : null}

      <form className="auth-form" onSubmit={handleSubmit}>
        {!isLoginMode ? (
          <div className="auth-form__grid">
            <label className="field">
              <span>First name</span>
              <input
                autoComplete="given-name"
                name="firstName"
                onChange={(event) => setFirstName(event.target.value)}
                required
                type="text"
                value={firstName}
              />
            </label>

            <label className="field">
              <span>Last name</span>
              <input
                autoComplete="family-name"
                name="lastName"
                onChange={(event) => setLastName(event.target.value)}
                required
                type="text"
                value={lastName}
              />
            </label>
          </div>
        ) : null}

        {!isLoginMode ? (
          <label className="field">
            <span>Lebanese phone number</span>
            <input
              autoComplete="tel"
              inputMode="tel"
              name="phoneNumber"
              onChange={(event) => setPhoneNumber(event.target.value)}
              placeholder="+961 71 123 456"
              required
              type="tel"
              value={phoneNumber}
            />
          </label>
        ) : null}

        <label className="field">
          <span>Email</span>
          <input
            autoComplete="email"
            name="email"
            onChange={(event) => setEmail(event.target.value)}
            required
            type="email"
            value={email}
          />
        </label>

        <label className="field">
          <span>Password</span>
          <input
            autoComplete={isLoginMode ? "current-password" : "new-password"}
            minLength={8}
            name="password"
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </label>

        {!isLoginMode ? (
          <label className="field">
            <span>Confirm password</span>
            <input
              autoComplete="new-password"
              minLength={8}
              name="confirmPassword"
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
              type="password"
              value={confirmPassword}
            />
          </label>
        ) : null}

        <button
          className="button button--primary"
          disabled={!isConfigured || submitting}
          type="submit"
        >
          {submitting
            ? isLoginMode
              ? "Signing in..."
              : "Creating account..."
            : isLoginMode
              ? "Sign in"
              : "Create account"}
        </button>
      </form>

      <p className="auth-card__switch">
        {isLoginMode ? "Need an account?" : "Already have an account?"}{" "}
        <Link to={isLoginMode ? "/signup" : "/login"}>
          {isLoginMode ? "Create one" : "Sign in"}
        </Link>
      </p>
    </section>
  );
}
