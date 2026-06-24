import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import {
  ApiError,
  buildChatWebSocketUrl,
  getChatMessages,
  listFeedback,
  listChatSessions,
  listDocuments,
  sendChatMessage,
  submitFeedback,
} from "../api";
import {
  ChatPageSkeleton,
  ConversationSkeleton,
} from "../components/SkeletonScreens";
import { CitationList } from "../components/CitationList";
import { DebugPanel } from "../components/DebugPanel";
import { EmptyState } from "../components/EmptyState";
import { MessageFeedback } from "../components/MessageFeedback";
import { PageHeader } from "../components/PageHeader";
import { SafeMarkdownText } from "../components/SafeMarkdownText";
import { readCachedValue, writeCachedValue } from "../lib/client-cache";
import { formatTimestamp } from "../lib/format";
import { useAuth } from "../hooks/useAuth";
import type {
  ChatMessageCitation,
  ChatMessageRecord,
  ChatRealtimeEvent,
  ChatResponse,
  ChatSessionSummary,
  DocumentSummary,
  FeedbackRecord,
  FeedbackRating,
} from "../types/api";

type CitationScoreLookup = Record<string, number | null>;
type FeedbackLookup = Record<string, FeedbackRecord>;
type PendingDisplayMessage = {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  model_used: string | null;
  citations: ChatMessageCitation[];
  is_pending: true;
  pending_label?: string;
};

const CHAT_SCOPE_CACHE_MAX_AGE_MS = 12 * 60 * 60 * 1000;
const CHAT_SCOPE_DRAFT_KEY = "chat-scope:draft";
const CHAT_TRANSIENT_RETRY_DELAY_MS = 450;

function getChatScopeCacheKey(
  sessionId: string | null,
  isNewChatMode: boolean,
) {
  if (isNewChatMode || !sessionId) {
    return CHAT_SCOPE_DRAFT_KEY;
  }

  return `chat-scope:${sessionId}`;
}

export function ChatPage() {
  const { canAccessDeveloperTools, session } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [sessions, setSessions] = useState<ChatSessionSummary[]>(
    () =>
      readCachedValue<ChatSessionSummary[]>("chat-sessions", 5 * 60 * 1000) ??
      [],
  );
  const [documents, setDocuments] = useState<DocumentSummary[]>(
    () => readCachedValue<DocumentSummary[]>("documents", 5 * 60 * 1000) ?? [],
  );
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(
    null,
  );
  const [messages, setMessages] = useState<ChatMessageRecord[]>([]);
  const [initialLoading, setInitialLoading] = useState(
    sessions.length === 0 && documents.length === 0,
  );
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [isDocumentModalOpen, setIsDocumentModalOpen] = useState(false);
  const [documentSearchQuery, setDocumentSearchQuery] = useState("");
  const [draftSelectedDocumentIds, setDraftSelectedDocumentIds] = useState<
    string[]
  >([]);
  const [debugEnabled, setDebugEnabled] = useState(false);
  const [sending, setSending] = useState(false);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [lastChatResponse, setLastChatResponse] = useState<ChatResponse | null>(
    null,
  );
  const [feedbackByMessageId, setFeedbackByMessageId] =
    useState<FeedbackLookup>({});
  const [feedbackSubmittingByMessageId, setFeedbackSubmittingByMessageId] =
    useState<Record<string, boolean>>({});
  const skipNextSessionFetchRef = useRef<string | null>(null);
  const hydratedScopeKeyRef = useRef<string | null>(null);
  const messageRequestIdRef = useRef(0);
  const selectedSessionIdRef = useRef<string | null>(null);
  const selectedSessionParam = searchParams.get("session");
  const isNewChatMode = searchParams.get("new") === "1";
  const chatScopeCacheKey = getChatScopeCacheKey(
    selectedSessionId,
    isNewChatMode,
  );

  const indexedDocuments = documents.filter(
    (document) => document.status === "indexed",
  );
  const filteredIndexedDocuments = indexedDocuments.filter((document) =>
    document.original_filename
      .toLowerCase()
      .includes(documentSearchQuery.trim().toLowerCase()),
  );
  const selectedDocuments = indexedDocuments.filter((document) =>
    selectedDocumentIds.includes(document.document_id),
  );
  const hasScopedDocuments = selectedDocumentIds.length > 0;

  async function loadSessions(
    preferredSessionId?: string | null,
    options?: { syncSelection?: boolean },
  ) {
    const syncSelection = options?.syncSelection ?? true;

    try {
      const response = await listChatSessions();
      setSessions(response);
      writeCachedValue("chat-sessions", response);
      setPageError(null);

      if (!syncSelection) {
        return;
      }

      if (isNewChatMode && !preferredSessionId && !selectedSessionId) {
        setSelectedSessionId(null);
        setMessages([]);
        setLastChatResponse(null);
        return;
      }

      if (!response.length) {
        setSelectedSessionId(null);
        setMessages([]);
        setLastChatResponse(null);
        setSearchParams({ new: "1" }, { replace: true });
        return;
      }

      const nextPreferredSessionId =
        preferredSessionId &&
        response.some((session) => session.session_id === preferredSessionId)
          ? preferredSessionId
          : null;
      const nextSelectedParam =
        selectedSessionParam &&
        response.some((session) => session.session_id === selectedSessionParam)
          ? selectedSessionParam
          : null;

      if (nextPreferredSessionId) {
        setSelectedSessionId(nextPreferredSessionId);
        setSearchParams({ session: nextPreferredSessionId }, { replace: true });
      } else if (nextSelectedParam) {
        setSelectedSessionId(nextSelectedParam);
      } else if (
        !isNewChatMode &&
        (!selectedSessionId ||
          !response.some((session) => session.session_id === selectedSessionId))
      ) {
        setSelectedSessionId(response[0].session_id);
        setSearchParams({ session: response[0].session_id }, { replace: true });
      }
    } catch (loadError) {
      setPageError(
        loadError instanceof Error
          ? loadError.message
          : "Could not load chat sessions.",
      );
    }
  }

  async function waitForTransientRetry() {
    await new Promise((resolve) =>
      window.setTimeout(resolve, CHAT_TRANSIENT_RETRY_DELAY_MS),
    );
  }

  async function loadDocuments(options?: { background?: boolean }) {
    const background = options?.background ?? false;

    try {
      const response = await listDocuments();
      setDocuments(response);
      writeCachedValue("documents", response);
      if (!background) {
        setPageError(null);
      }
    } catch (loadError) {
      if (!background && documents.length === 0) {
        setPageError(
          loadError instanceof Error
            ? loadError.message
            : "Could not load documents for chat.",
        );
      }
    }
  }

  async function loadFeedback(options?: { background?: boolean }) {
    const background = options?.background ?? false;

    try {
      const feedback = await listFeedback();
      setFeedbackByMessageId(
        feedback.reduce<FeedbackLookup>((accumulator, record) => {
          accumulator[record.message_id] = record;
          return accumulator;
        }, {}),
      );
      if (!background) {
        setPageError(null);
      }
    } catch (loadError) {
      if (!background && Object.keys(feedbackByMessageId).length === 0) {
        setPageError(
          loadError instanceof Error
            ? loadError.message
            : "Could not load saved feedback.",
        );
      }
    }
  }

  async function loadMessages(sessionId: string) {
    const requestId = messageRequestIdRef.current + 1;
    messageRequestIdRef.current = requestId;
    setMessagesLoading(true);

    try {
      let response: Awaited<ReturnType<typeof getChatMessages>>;
      try {
        response = await getChatMessages(sessionId);
      } catch (loadError) {
        if (!(loadError instanceof ApiError) || loadError.status !== 503) {
          throw loadError;
        }

        await waitForTransientRetry();
        response = await getChatMessages(sessionId);
      }

      if (requestId !== messageRequestIdRef.current) {
        return;
      }

      setMessages(response.messages);
      writeCachedValue(`chat-messages:${sessionId}`, response.messages);
      setPageError(null);
    } catch (loadError) {
      if (requestId !== messageRequestIdRef.current) {
        return;
      }

      setPageError(
        loadError instanceof Error
          ? loadError.message
          : "Could not load chat messages.",
      );
    } finally {
      if (requestId === messageRequestIdRef.current) {
        setMessagesLoading(false);
      }
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function loadInitialState() {
      if (sessions.length === 0 && documents.length === 0) {
        setInitialLoading(true);
      }
      await Promise.all([
        sessions.length === 0
          ? loadSessions(selectedSessionParam, { syncSelection: true })
          : Promise.resolve(),
        loadDocuments(),
      ]);
      void loadFeedback({ background: true });
      if (!cancelled) {
        setInitialLoading(false);
      }
    }

    void loadInitialState();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setPageError(null);
    setIsDocumentModalOpen(false);

    if (selectedSessionParam) {
      setSelectedSessionId(selectedSessionParam);
      return;
    }

    if (isNewChatMode) {
      setSelectedSessionId(null);
      setMessages([]);
      setLastChatResponse(null);
      setPendingQuestion(null);
      setQuestion("");
      setSelectedDocumentIds([]);
      writeCachedValue(CHAT_SCOPE_DRAFT_KEY, []);
    }
  }, [isNewChatMode, selectedSessionParam]);

  useEffect(() => {
    if (hydratedScopeKeyRef.current === chatScopeCacheKey) {
      return;
    }

    const cachedScope =
      readCachedValue<string[]>(
        chatScopeCacheKey,
        CHAT_SCOPE_CACHE_MAX_AGE_MS,
      ) ?? [];
    hydratedScopeKeyRef.current = chatScopeCacheKey;
    setSelectedDocumentIds(cachedScope);
  }, [chatScopeCacheKey]);

  useEffect(() => {
    if (!indexedDocuments.length) {
      return;
    }

    setSelectedDocumentIds((currentDocumentIds) => {
      const validScope = currentDocumentIds.filter((documentId) =>
        indexedDocuments.some(
          (document) => document.document_id === documentId,
        ),
      );

      if (validScope.length === currentDocumentIds.length) {
        return currentDocumentIds;
      }

      return validScope;
    });
  }, [indexedDocuments]);

  useEffect(() => {
    if (!selectedSessionId) {
      setMessages([]);
      setMessagesLoading(false);
      return;
    }

    if (isNewChatMode) {
      return;
    }

    if (skipNextSessionFetchRef.current === selectedSessionId) {
      skipNextSessionFetchRef.current = null;
      return;
    }

    const cachedMessages = readCachedValue<ChatMessageRecord[]>(
      `chat-messages:${selectedSessionId}`,
      5 * 60 * 1000,
    );
    if (cachedMessages?.length) {
      setMessages(cachedMessages);
      setMessagesLoading(false);
    }

    void loadMessages(selectedSessionId);
  }, [isNewChatMode, selectedSessionId]);

  useEffect(() => {
    selectedSessionIdRef.current = selectedSessionId;
  }, [selectedSessionId]);

  useEffect(() => {
    writeCachedValue(chatScopeCacheKey, selectedDocumentIds);
  }, [chatScopeCacheKey, selectedDocumentIds]);

  function upsertSessionSummary(nextSession: ChatSessionSummary) {
    setSessions((currentSessions) => {
      const updatedSessions = [
        nextSession,
        ...currentSessions.filter(
          (sessionRecord) => sessionRecord.session_id !== nextSession.session_id,
        ),
      ].sort(
        (left, right) =>
          new Date(right.updated_at).getTime()
          - new Date(left.updated_at).getTime(),
      );
      writeCachedValue("chat-sessions", updatedSessions);
      return updatedSessions;
    });
  }

  function appendMessageIfMissing(
    sessionId: string,
    nextMessage: ChatMessageRecord,
  ) {
    if (selectedSessionIdRef.current !== sessionId) {
      return;
    }

    setMessages((currentMessages) => {
      if (
        currentMessages.some(
          (existingMessage) => existingMessage.message_id === nextMessage.message_id,
        )
      ) {
        return currentMessages;
      }

      const updatedMessages = [...currentMessages, nextMessage];
      writeCachedValue(`chat-messages:${sessionId}`, updatedMessages);
      return updatedMessages;
    });
  }

  useEffect(() => {
    if (!session?.access_token) {
      return;
    }

    const socket = new WebSocket(buildChatWebSocketUrl(session.access_token));

    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as ChatRealtimeEvent;
      if (payload.type === "chat.session.upsert") {
        upsertSessionSummary(payload.session);
        return;
      }

      if (payload.type === "chat.session.deleted") {
        setSessions((currentSessions) => {
          const nextSessions = currentSessions.filter(
            (sessionRecord) => sessionRecord.session_id !== payload.session_id,
          );
          writeCachedValue("chat-sessions", nextSessions);
          return nextSessions;
        });

        if (selectedSessionIdRef.current === payload.session_id) {
          setMessages([]);
          setSelectedSessionId(null);
          setLastChatResponse(null);
          setPendingQuestion(null);
          setQuestion("");
          setSearchParams({ new: "1" }, { replace: true });
        }
        return;
      }

      if (payload.type === "chat.message.created") {
        appendMessageIfMissing(payload.session_id, payload.message);
      }
    };

    return () => {
      socket.close();
    };
  }, [session?.access_token, setSearchParams]);

  useEffect(() => {
    function refreshDocuments() {
      void loadDocuments({ background: true });
    }

    function handleVisibilityChange() {
      if (!document.hidden) {
        refreshDocuments();
      }
    }

    window.addEventListener("focus", refreshDocuments);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.removeEventListener("focus", refreshDocuments);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  async function handleCreateSession() {
    setPageError(null);
    setSelectedSessionId(null);
    setMessages([]);
    setLastChatResponse(null);
    setPendingQuestion(null);
    setSelectedDocumentIds([]);
    writeCachedValue(CHAT_SCOPE_DRAFT_KEY, []);
    setQuestion("");
    setSearchParams({ new: "1" }, { replace: true });
  }

  function openDocumentModal() {
    setDraftSelectedDocumentIds(selectedDocumentIds);
    setDocumentSearchQuery("");
    setIsDocumentModalOpen(true);
  }

  function toggleDraftDocument(documentId: string) {
    setDraftSelectedDocumentIds((currentDocumentIds) =>
      currentDocumentIds.includes(documentId)
        ? currentDocumentIds.filter((currentId) => currentId !== documentId)
        : [...currentDocumentIds, documentId],
    );
  }

  function removeSelectedDocument(documentId: string) {
    setSelectedDocumentIds((currentDocumentIds) =>
      currentDocumentIds.filter((currentId) => currentId !== documentId),
    );
  }

  function closeDocumentModal() {
    setIsDocumentModalOpen(false);
    setDocumentSearchQuery("");
    setDraftSelectedDocumentIds([]);
  }

  function applyDocumentSelection() {
    setSelectedDocumentIds(draftSelectedDocumentIds);
    closeDocumentModal();
  }

  async function handleSendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanedQuestion = question.trim();
    if (!cleanedQuestion) {
      return;
    }

    setSending(true);
    setPendingQuestion(cleanedQuestion);
    setPageError(null);
    setQuestion("");

    try {
      const response = await sendChatMessage({
        session_id: selectedSessionId ?? undefined,
        question: cleanedQuestion,
        document_ids: selectedDocumentIds.length
          ? selectedDocumentIds
          : undefined,
        debug: canAccessDeveloperTools ? debugEnabled : false,
      });

      setLastChatResponse(response);

      const nextMessages = [
        ...(selectedSessionId === response.session_id ? messages : []),
        response.user_message,
        response.assistant_message,
      ].filter((message): message is ChatMessageRecord => Boolean(message));

      if (nextMessages.length) {
        setMessages(nextMessages);
        writeCachedValue(`chat-messages:${response.session_id}`, nextMessages);
      }

      if (selectedSessionId !== response.session_id) {
        writeCachedValue(
          `chat-scope:${response.session_id}`,
          selectedDocumentIds,
        );
        writeCachedValue(CHAT_SCOPE_DRAFT_KEY, []);
        skipNextSessionFetchRef.current = response.session_id;
        setSearchParams({ session: response.session_id }, { replace: true });
        setSelectedSessionId(response.session_id);
      }

      void loadSessions(response.session_id, { syncSelection: false });
      void loadFeedback({ background: true });
      setPageError(null);
    } catch (sendError) {
      setQuestion(cleanedQuestion);
      setPageError(
        sendError instanceof Error
          ? sendError.message
          : "The backend could not answer that question right now.",
      );
    } finally {
      setPendingQuestion(null);
      setSending(false);
    }
  }

  async function handleFeedbackSubmit(
    messageId: string,
    rating: FeedbackRating,
    comment?: string,
  ) {
    setFeedbackSubmittingByMessageId((currentState) => ({
      ...currentState,
      [messageId]: true,
    }));
    setPageError(null);

    try {
      const feedback = await submitFeedback({
        message_id: messageId,
        rating,
        comment,
      });
      setFeedbackByMessageId((currentState) => ({
        ...currentState,
        [messageId]: feedback,
      }));
    } catch (feedbackError) {
      setPageError(
        feedbackError instanceof Error
          ? feedbackError.message
          : "Could not save feedback for that answer.",
      );
      throw feedbackError;
    } finally {
      setFeedbackSubmittingByMessageId((currentState) => ({
        ...currentState,
        [messageId]: false,
      }));
    }
  }

  function buildCitationItems(
    citations: ChatMessageCitation[],
    scoreLookup: CitationScoreLookup,
  ) {
    return citations.map((citation) => ({
      sourceNumber: citation.source_number,
      chunkId: citation.chunk_id,
      pageNumber: citation.page_number,
      score:
        citation.similarity_score ?? scoreLookup[citation.chunk_id] ?? null,
      sectionTitle: citation.section_title,
      sourceFile: citation.source_file,
    }));
  }

  const latestSourceScores = (
    lastChatResponse?.sources ?? []
  ).reduce<CitationScoreLookup>((accumulator, source) => {
    accumulator[source.chunk_id] = source.score;
    return accumulator;
  }, {});

  const selectedSessionTitle = sessions.find(
    (session) => session.session_id === selectedSessionId,
  )?.title;
  const pageTitle = selectedSessionId && !isNewChatMode ? "Chat" : "New chat";

  const displayedMessages: Array<ChatMessageRecord | PendingDisplayMessage> =
    pendingQuestion
      ? [
          ...messages,
          {
            message_id: "pending-user-message",
            role: "user",
            content: pendingQuestion,
            created_at: new Date().toISOString(),
            model_used: null,
            citations: [],
            is_pending: true,
          },
          {
            message_id: "pending-assistant-message",
            role: "assistant",
            content: "",
            created_at: new Date().toISOString(),
            model_used: null,
            citations: [],
            is_pending: true,
            pending_label: "Answering...",
          },
        ]
      : messages;

  if (initialLoading) {
    return <ChatPageSkeleton />;
  }

  return (
    <div className="page-stack page-stack--chat">
      <PageHeader
        actions={
          canAccessDeveloperTools ? (
            <button
              type="button"
              className={`debug-toggle ${debugEnabled ? "debug-toggle--on" : "debug-toggle--off"}`}
              onClick={() => setDebugEnabled((prev) => !prev)}
              aria-pressed={debugEnabled}
            >
              {debugEnabled ? "Debug On" : "Debug Off"}
            </button>
          ) : undefined
        }
        eyebrow="Chat"
        title={pageTitle}
        description={
          selectedSessionId && !isNewChatMode
            ? (selectedSessionTitle ?? "")
            : ""
        }
      />

      {pageError ? <div className="alert alert--error">{pageError}</div> : null}

      {!indexedDocuments.length ? (
        <div className="alert alert--warning">
          No indexed documents are ready yet.
        </div>
      ) : null}

      {!indexedDocuments.length &&
      documents.some(
        (document) =>
          document.status === "processing" || document.status === "queued",
      ) ? (
        <div className="alert alert--info">
          Some documents are still processing.
        </div>
      ) : null}

      <section className="chat-main">
        <article className="panel panel--section panel--chat-surface">
          <div className="chat-toolbar">
            <div className="chat-toolbar__meta"></div>
          </div>

          {messagesLoading ? (
            <ConversationSkeleton />
          ) : displayedMessages.length ? (
            <div className="message-thread">
              {displayedMessages.map((message) => {
                const isPending = "is_pending" in message;

                return (
                  <article
                    key={message.message_id}
                    className={`message-bubble message-bubble--${message.role}`}
                  >
                    {message.role === "assistant" ? (
                      <div className="message-bubble__header">
                        <div>
                          <p className="message-bubble__role">Assistant</p>
                          <p className="message-bubble__timestamp">
                            {formatTimestamp(message.created_at)}
                          </p>
                        </div>
                        {message.model_used ? (
                          <span className="message-bubble__model">
                            {message.model_used}
                          </span>
                        ) : null}
                      </div>
                    ) : null}

                    {isPending && message.pending_label ? (
                      <div className="message-bubble__pending">
                        <div className="message-bubble__text message-bubble__text--pending">
                          {message.pending_label}
                        </div>
                      </div>
                    ) : (
                      <div className="message-bubble__text">
                        <SafeMarkdownText text={message.content} />
                      </div>
                    )}

                    {message.role === "assistant" && !isPending ? (
                      <>
                        <CitationList
                          items={buildCitationItems(
                            message.citations,
                            latestSourceScores,
                          )}
                          showScores={debugEnabled}
                        />
                        <MessageFeedback
                          feedback={feedbackByMessageId[message.message_id]}
                          loading={
                            feedbackSubmittingByMessageId[message.message_id] ??
                            false
                          }
                          onSubmit={(rating, comment) =>
                            handleFeedbackSubmit(
                              message.message_id,
                              rating,
                              comment,
                            )
                          }
                        />
                      </>
                    ) : null}
                  </article>
                );
              })}
            </div>
          ) : (
            <EmptyState
              title="No messages"
              description="Ask a question to start."
            />
          )}
        </article>

        <article className="panel panel--section chat-composer-panel">
          <form
            className="chat-composer chat-composer--inline"
            onSubmit={handleSendMessage}
          >
            <div className="chat-scope-bar">
              {selectedDocuments.length ? (
                <div className="chat-scope-bar__chips">
                  {selectedDocuments.map((document) => (
                    <span
                      key={document.document_id}
                      className="document-chip document-chip--interactive"
                    >
                      <span className="document-chip__label">
                        {document.original_filename}
                      </span>
                      <button
                        aria-label={`Remove ${document.original_filename}`}
                        className="document-chip__remove"
                        onClick={() =>
                          removeSelectedDocument(document.document_id)
                        }
                        type="button"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              ) : (
                <p className="chat-scope-bar__empty">All indexed documents</p>
              )}
            </div>

            <div className="chat-composer__row">
              <label className="field chat-composer__field">
                <textarea
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="Ask about your documents"
                  rows={2}
                  value={question}
                />
              </label>
              <div className="chat-composer__actions">
                <button
                  className="button button--ghost button--compact"
                  disabled={!indexedDocuments.length}
                  onClick={openDocumentModal}
                  type="button"
                >
                  Add Document
                </button>
                <button
                  className="button button--ghost button--compact"
                  disabled={sending || !indexedDocuments.length}
                  type="submit"
                >
                  {sending ? "Asking..." : "Send"}
                </button>
              </div>
            </div>
          </form>
        </article>

        {lastChatResponse && !lastChatResponse.retrieval_passed ? (
          <div className="alert alert--warning">
            Not enough matching context.
          </div>
        ) : null}

        {canAccessDeveloperTools && debugEnabled && lastChatResponse?.debug ? (
          <DebugPanel
            debug={lastChatResponse.debug}
            retrievalPassed={lastChatResponse.retrieval_passed}
          />
        ) : null}
      </section>

      {isDocumentModalOpen ? (
        <div
          aria-modal="true"
          className="modal-backdrop"
          onClick={closeDocumentModal}
          role="dialog"
        >
          <div
            className="modal-card"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-card__header">
              <div className="modal-card__title-row">
                <div>
                  <p className="panel__eyebrow">Select documents</p>
                  <h2>Choose scope</h2>
                </div>
                <span className="modal-card__count">
                  {draftSelectedDocumentIds.length
                    ? `${draftSelectedDocumentIds.length} selected`
                    : "All indexed documents"}
                </span>
              </div>
              <button
                aria-label="Close document selector"
                className="button button--ghost button--compact"
                onClick={closeDocumentModal}
                type="button"
              >
                ×
              </button>
            </div>

            <label className="field document-filter__search">
              <input
                autoFocus
                onChange={(event) => setDocumentSearchQuery(event.target.value)}
                placeholder="Search documents"
                type="text"
                value={documentSearchQuery}
              />
            </label>

            <div className="modal-document-list">
              {filteredIndexedDocuments.length ? (
                filteredIndexedDocuments.map((document) => {
                  const isSelected = draftSelectedDocumentIds.includes(
                    document.document_id,
                  );

                  return (
                    <button
                      key={document.document_id}
                      className={`modal-document-option ${isSelected ? "modal-document-option--selected" : ""}`}
                      onClick={() => toggleDraftDocument(document.document_id)}
                      type="button"
                    >
                      <span className="modal-document-option__check">
                        {isSelected ? "" : ""}
                      </span>
                      <span className="modal-document-option__label">
                        {document.original_filename}
                      </span>
                    </button>
                  );
                })
              ) : (
                <p className="document-filter__empty">No matching documents.</p>
              )}
            </div>

            <div className="modal-card__footer">
              <p className="modal-card__hint">
                {draftSelectedDocumentIds.length
                  ? "Selected documents stay attached to this chat session."
                  : "No selection means the chat will search across all indexed documents."}
              </p>
              <div className="button-row modal-card__actions">
                <button
                  className="button button--ghost"
                  onClick={closeDocumentModal}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="button button--primary"
                  onClick={applyDocumentSelection}
                  type="button"
                >
                  Select
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
