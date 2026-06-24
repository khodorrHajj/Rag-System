import { StatusCard } from "../components/StatusCard";
import { useHealthCheck } from "../hooks/useHealthCheck";

export function HomePage() {
  const { health, error, loading } = useHealthCheck();

  const backendStatus = loading
    ? "Checking backend..."
    : error
      ? "Unavailable"
      : health?.status ?? "Unknown";

  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">Repository Foundation</p>
        <h1>RAG Document Assistant</h1>
        <p className="hero__copy">
          This UI is a starter shell for the future ingestion, retrieval, and chat
          workflows. The current step only verifies that the frontend can talk to
          the backend health endpoint.
        </p>
      </section>

      <section className="status-grid">
        <StatusCard title="Frontend" value="Ready" tone="success" />
        <StatusCard title="Backend Health" value={backendStatus} tone={error ? "warning" : "success"} />
        <StatusCard title="Pipeline" value="Planned" />
      </section>

      {error ? (
        <p className="inline-note">
          Backend connection is a placeholder at this stage. Start the FastAPI app
          on <code>http://localhost:8000</code>
        </p>
      ) : null}
    </main>
  );
}

