import { AuthForm } from "../components/AuthForm";

export function LoginPage() {
  return (
    <main className="auth-page">
      <AuthForm mode="login" />
    </main>
  );
}
