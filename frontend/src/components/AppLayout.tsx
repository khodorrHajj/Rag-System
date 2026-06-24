import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { buildChatWebSocketUrl, deleteChatSession, listChatSessions } from "../api";
import { useAuth } from "../hooks/useAuth";
import { readCachedValue, writeCachedValue } from "../lib/client-cache";
import type { ChatRealtimeEvent, ChatSessionSummary } from "../types/api";

export function AppLayout() {
  const { canAccessDeveloperTools, currentUser, session, signOut, user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<ChatSessionSummary[]>(
    () =>
      readCachedValue<ChatSessionSummary[]>("chat-sessions", 5 * 60 * 1000) ??
      [],
  );
  const [sessionsLoading, setSessionsLoading] = useState(sessions.length === 0);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(
    null,
  );
  const [sessionError, setSessionError] = useState<string | null>(null);

  async function loadSessions(options?: { background?: boolean }) {
    const background = options?.background ?? false;

    if (!background) {
      setSessionsLoading(true);
    }

    try {
      const response = await listChatSessions();
      setSessions(response);
      writeCachedValue("chat-sessions", response);
      setSessionError(null);
    } catch {
      if (!background) {
        setSessions([]);
        setSessionError("Chats are temporarily unavailable.");
      }
    } finally {
      if (!background) {
        setSessionsLoading(false);
      }
    }
  }

  useEffect(() => {
    void loadSessions();
  }, []);

  useEffect(() => {
    if (!session?.access_token) {
      return;
    }

    const socket = new WebSocket(buildChatWebSocketUrl(session.access_token));

    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as ChatRealtimeEvent;
      if (payload.type === "chat.session.upsert") {
        setSessions((currentSessions) => {
          const nextSessions = [
            payload.session,
            ...currentSessions.filter(
              (sessionRecord) =>
                sessionRecord.session_id !== payload.session.session_id,
            ),
          ].sort(
            (left, right) =>
              new Date(right.updated_at).getTime()
              - new Date(left.updated_at).getTime(),
          );
          writeCachedValue("chat-sessions", nextSessions);
          return nextSessions;
        });
        setSessionError(null);
      }

      if (payload.type === "chat.session.deleted") {
        setSessions((currentSessions) => {
          const nextSessions = currentSessions.filter(
            (sessionRecord) => sessionRecord.session_id !== payload.session_id,
          );
          writeCachedValue("chat-sessions", nextSessions);
          return nextSessions;
        });
      }
    };

    return () => {
      socket.close();
    };
  }, [session?.access_token]);

  const activeSessionId =
    new URLSearchParams(location.search).get("session") ?? null;

  function handleNewChat() {
    void navigate("/chat?new=1");
  }

  async function handleDeleteSession(session: ChatSessionSummary) {
    const confirmed = window.confirm("Delete this chat?");
    if (!confirmed) {
      return;
    }

    const wasActiveSession = activeSessionId === session.session_id;
    const previousSessions = sessions;
    const nextSessions = sessions.filter(
      (item) => item.session_id !== session.session_id,
    );

    setDeletingSessionId(session.session_id);
    setSessionError(null);
    setSessions(nextSessions);
    writeCachedValue("chat-sessions", nextSessions);

    if (wasActiveSession) {
      void navigate("/chat?new=1", { replace: true });
    }

    try {
      await deleteChatSession(session.session_id);
    } catch {
      setSessions(previousSessions);
      writeCachedValue("chat-sessions", previousSessions);
      if (wasActiveSession) {
        void navigate(`/chat?session=${session.session_id}`, { replace: true });
      }
      setSessionError("Could not delete this chat. Please try again.");
    } finally {
      setDeletingSessionId(null);
    }
  }

  return (
    <div className="workspace-shell">
      <aside className="workspace-shell__sidebar">
        <div className="brand-lockup">
          <p className="brand-lockup__title">RAG System</p>
        </div>

        <div className="workspace-shell__actions">
          <button
            className="button button--primary button--full"
            onClick={handleNewChat}
            type="button"
          >
            New chat
          </button>

          <nav className="workspace-nav" aria-label="Primary">
            <NavLink to="/documents">Documents</NavLink>
            {canAccessDeveloperTools ? (
              <NavLink to="/developer">Developer</NavLink>
            ) : null}
          </nav>
        </div>

        <section className="workspace-shell__sessions">
          <div className="workspace-shell__sessions-header">
            <p className="panel__eyebrow">Chats</p>
          </div>
          {sessionError ? (
            <p className="workspace-shell__sessions-error">{sessionError}</p>
          ) : null}

          {sessionsLoading ? (
            <div className="session-list" aria-hidden="true">
              {Array.from({ length: 5 }).map((_, index) => (
                <div key={index} className="skeleton skeleton--session-item" />
              ))}
            </div>
          ) : sessions.length ? (
            <ul className="session-list">
              {sessions.map((session) => (
                <li className="session-list__item" key={session.session_id}>
                  <button
                    className={`session-list__button ${activeSessionId === session.session_id ? "session-list__button--active" : ""}`}
                    onClick={() =>
                      void navigate(`/chat?session=${session.session_id}`)
                    }
                    title={session.title ?? "New chat"}
                    type="button"
                  >
                    <span className="session-list__title">
                      {session.title ?? "New chat"}
                    </span>
                  </button>
                  <button
                    aria-label={`Delete chat ${session.title ?? "New chat"}`}
                    className="session-list__delete"
                    disabled={deletingSessionId === session.session_id}
                    onClick={() => void handleDeleteSession(session)}
                    title="Delete chat"
                    type="button"
                  >
                    x
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="workspace-shell__sessions-empty">No chats yet</p>
          )}
        </section>

        <div className="workspace-shell__account">
          <p
            className="workspace-shell__account-value"
            title={currentUser?.email ?? user?.email ?? "Unknown user"}
          >
            {currentUser?.email ?? user?.email ?? "Unknown user"}
          </p>
          <button
            className="button button--ghost"
            onClick={() => void signOut()}
            type="button"
          >
            Log out
          </button>
        </div>
      </aside>

      <main className="workspace-shell__main">
        <Outlet />
      </main>
    </div>
  );
}
