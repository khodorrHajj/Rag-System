import { AuthForm } from "../components/AuthForm";

export function SignupPage() {
  return (
    <main className="auth-page">
      <AuthForm mode="signup" />
    </main>
  );
}
