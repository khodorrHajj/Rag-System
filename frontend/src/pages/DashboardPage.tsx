import { Link } from "react-router-dom";
import { useEffect, useState } from "react";

import { getMe, listChatSessions, listDocuments } from "../api";
import { fetchHealth } from "../api/health";
import { EmptyState } from "../components/EmptyState";
import { DashboardSkeleton } from "../components/DashboardSkeleton";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { StatusCard } from "../components/StatusCard";
import { usePolling } from "../hooks/usePolling";
import { formatTimestamp } from "../lib/format";
import type { ChatSessionSummary, CurrentUser, DocumentSummary } from "../types/api";
import type { HealthResponse } from "../types/health";

type DashboardState = {
  health: HealthResponse | null;
  me: CurrentUser | null;
  sessions: ChatSessionSummary[];
  documents: DocumentSummary[];
};

export function DashboardPage() {
  const [dashboard, setDashboard] = useState<DashboardState>({
    health: null,
    me: null,
    sessions: [],
    documents: [],
  });
  const [error, setError] = useState<string | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);

  async function loadDashboard(options?: { background?: boolean }) {
    const background = options?.background ?? false;

    if (!background) {
      setInitialLoading(true);
    }

    setError(null);

    try {
      const [health, me, documents, sessions] = await Promise.all([
        fetchHealth(),
        getMe(),
        listDocuments(),
        listChatSessions(),
      ]);

      setDashboard({
        health,
        me,
        sessions,
        documents,
      });
    } catch (dashboardError) {
      setError(
        dashboardError instanceof Error
          ? dashboardError.message
          : "Could not load the dashboard right now.",
      );
    } finally {
      if (!background) {
        setInitialLoading(false);
      }
    }
  }

  useEffect(() => {
    void loadDashboard();
  }, []);

  usePolling(
    () => loadDashboard({ background: true }),
    20000,
    { enabled: !initialLoading },
  );

  if (initialLoading) {
    return <DashboardSkeleton />;
  }

  const indexedCount = dashboard.documents.filter((document) => document.status === "indexed").length;
  const processingCount = dashboard.documents.filter(
    (document) => document.status === "queued" || document.status === "processing",
  ).length;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Workspace overview"
        title="Your grounded document workspace"
        description="Track documents, status, and chat."
      />

      {error ? <div className="alert alert--error">{error}</div> : null}

      <section className="status-grid">
        <StatusCard title="Backend health" tone="success" value={dashboard.health?.status ?? "Unknown"} />
        <StatusCard title="Signed-in user" value={dashboard.me?.email ?? "Unknown"} />
        <StatusCard title="Indexed documents" tone="success" value={String(indexedCount)} />
        <StatusCard title="Still processing" tone={processingCount > 0 ? "warning" : "default"} value={String(processingCount)} />
      </section>

      <section className="quick-links">
        <Link className="quick-link" to="/documents">
          <span>Upload and monitor files</span>
          <strong>Open Documents</strong>
        </Link>
        <Link className="quick-link" to="/chat">
          <span>Ask questions with citations</span>
          <strong>Open Chat</strong>
        </Link>
      </section>

      <section className="dashboard-grid">
        <article className="panel">
          <div className="panel__header">
            <div>
              <p className="panel__eyebrow">Recent documents</p>
              <h2>Latest uploads</h2>
            </div>
            <Link className="panel__link" to="/documents">
              Manage all
            </Link>
          </div>

          {dashboard.documents.length ? (
            <ul className="list-stack">
              {dashboard.documents.slice(0, 5).map((document) => (
                <li key={document.document_id} className="list-row">
                  <div>
                    <p className="list-row__title">{document.original_filename}</p>
                    <p className="list-row__meta">{formatTimestamp(document.updated_at)}</p>
                  </div>
                  <StatusBadge status={document.status} />
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No documents yet"
              description="Upload a file to get started."
            />
          )}
        </article>

        <article className="panel">
          <div className="panel__header">
            <div>
              <p className="panel__eyebrow">Recent conversations</p>
              <h2>Chat sessions</h2>
            </div>
            <Link className="panel__link" to="/chat">
              Open chat
            </Link>
          </div>

          {dashboard.sessions.length ? (
            <ul className="list-stack">
              {dashboard.sessions.slice(0, 5).map((session) => (
                <li key={session.session_id} className="list-row">
                  <div>
                    <p className="list-row__title">{session.title ?? "Untitled chat session"}</p>
                    <p className="list-row__meta">{formatTimestamp(session.updated_at)}</p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No chat sessions yet"
              description="Your chats will appear here."
            />
          )}
        </article>
      </section>
    </div>
  );
}
