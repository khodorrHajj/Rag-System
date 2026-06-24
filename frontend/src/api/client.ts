import { frontendEnv } from "../lib/env";
import { buildBackendUnavailableMessage, isNetworkFetchError } from "../lib/api-errors";
import type {
  ChatMessageListResponse,
  ChatResponse,
  ChatSessionDeleteResponse,
  ChatSessionListResponse,
  ChatSessionSummary,
  CurrentUser,
  DeveloperDashboardResponse,
  DocumentDeleteResponse,
  DocumentDetail,
  DocumentSummary,
  DocumentUploadResponse,
  EvaluationResultsListResponse,
  EvaluationRunRequest,
  EvaluationRunResponse,
  FeedbackListResponse,
  FeedbackRecord,
  SendChatMessagePayload,
  SubmitFeedbackPayload,
} from "../types/api";

type ApiClientRuntime = {
  getAccessToken?: () => Promise<string | null>;
  refreshAccessToken?: () => Promise<string | null>;
  onUnauthorized?: () => Promise<void> | void;
};

type RequestOptions = RequestInit & {
  auth?: boolean;
};

const apiClientRuntime: ApiClientRuntime = {};
const GET_RETRYABLE_STATUS_CODES = new Set([502, 503, 504]);
const GET_REQUEST_RETRY_DELAY_MS = 350;
const GET_REQUEST_MAX_ATTEMPTS = 2;

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function configureApiClient(runtime: ApiClientRuntime): void {
  apiClientRuntime.getAccessToken = runtime.getAccessToken;
  apiClientRuntime.refreshAccessToken = runtime.refreshAccessToken;
  apiClientRuntime.onUnauthorized = runtime.onUnauthorized;
}

export function buildChatWebSocketUrl(token: string): string {
  const baseUrl = new URL(frontendEnv.apiBaseUrl);
  baseUrl.protocol = baseUrl.protocol === "https:" ? "wss:" : "ws:";
  baseUrl.pathname = `${trimTrailingSlash(baseUrl.pathname)}/chat/ws`;
  baseUrl.search = "";
  baseUrl.searchParams.set("token", token);
  return baseUrl.toString();
}

function resolveErrorMessage(payload: unknown, fallbackMessage: string): string {
  if (
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    typeof payload.detail === "string" &&
    payload.detail.trim()
  ) {
    return payload.detail;
  }

  return fallbackMessage;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { auth = true, headers: initialHeaders, body, ...rest } = options;
  const headers = new Headers(initialHeaders);
  const method = (rest.method ?? "GET").toUpperCase();
  const canRetryReadRequest = method === "GET";

  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
  if (!isFormData && body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (auth) {
    const accessToken = apiClientRuntime.getAccessToken
      ? await apiClientRuntime.getAccessToken()
      : null;

    if (!accessToken) {
      await apiClientRuntime.onUnauthorized?.();
      throw new ApiError("Your session has expired. Please sign in again.", 401);
    }

    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  async function performRequest(requestHeaders: Headers): Promise<Response> {
    let attempt = 0;

    while (attempt < GET_REQUEST_MAX_ATTEMPTS) {
      attempt += 1;

      try {
        const response = await fetch(`${frontendEnv.apiBaseUrl}${path}`, {
          ...rest,
          headers: requestHeaders,
          body,
        });

        if (
          canRetryReadRequest
          && GET_RETRYABLE_STATUS_CODES.has(response.status)
          && attempt < GET_REQUEST_MAX_ATTEMPTS
        ) {
          await new Promise((resolve) =>
            window.setTimeout(resolve, GET_REQUEST_RETRY_DELAY_MS * attempt),
          );
          continue;
        }

        return response;
      } catch (error) {
        if (!isNetworkFetchError(error)) {
          throw error;
        }

        if (canRetryReadRequest && attempt < GET_REQUEST_MAX_ATTEMPTS) {
          await new Promise((resolve) =>
            window.setTimeout(resolve, GET_REQUEST_RETRY_DELAY_MS * attempt),
          );
          continue;
        }

        throw new ApiError(buildBackendUnavailableMessage(frontendEnv.apiBaseUrl), 0);
      }
    }

    throw new ApiError(buildBackendUnavailableMessage(frontendEnv.apiBaseUrl), 0);
  }

  let response = await performRequest(headers);

  if (response.status === 401 && auth && apiClientRuntime.refreshAccessToken) {
    const refreshedToken = await apiClientRuntime.refreshAccessToken();
    if (refreshedToken) {
      const retryHeaders = new Headers(initialHeaders);
      if (!isFormData && body !== undefined && !retryHeaders.has("Content-Type")) {
        retryHeaders.set("Content-Type", "application/json");
      }

      retryHeaders.set("Authorization", `Bearer ${refreshedToken}`);
      response = await performRequest(retryHeaders);
    }
  }

  const contentType = response.headers.get("content-type") ?? "";
  let payload: unknown = null;

  if (contentType.includes("application/json")) {
    payload = await response.json();
  } else {
    const text = await response.text();
    payload = text ? { detail: text } : null;
  }

  if (response.status === 401) {
    await apiClientRuntime.onUnauthorized?.();
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }

  if (!response.ok) {
    throw new ApiError(
      resolveErrorMessage(payload, "Request failed. Please try again."),
      response.status,
    );
  }

  return payload as T;
}

export async function getMe(): Promise<CurrentUser> {
  return request<CurrentUser>("/me");
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  return request<DocumentSummary[]>("/documents");
}

export async function uploadDocument(file: File): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  return request<DocumentUploadResponse>("/documents/upload", {
    method: "POST",
    body: formData,
  });
}

export async function getDocument(documentId: string): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/documents/${documentId}`);
}

export async function deleteDocument(documentId: string): Promise<DocumentDeleteResponse> {
  return request<DocumentDeleteResponse>(`/documents/${documentId}`, {
    method: "DELETE",
  });
}

export async function createChatSession(title?: string): Promise<ChatSessionSummary> {
  return request<ChatSessionSummary>("/chat/sessions", {
    method: "POST",
    body: title ? JSON.stringify({ title }) : undefined,
  });
}

export async function listChatSessions(): Promise<ChatSessionSummary[]> {
  const response = await request<ChatSessionListResponse>("/chat/sessions");
  return response.sessions;
}

export async function getChatMessages(sessionId: string): Promise<ChatMessageListResponse> {
  return request<ChatMessageListResponse>(`/chat/sessions/${sessionId}/messages`);
}

export async function deleteChatSession(
  sessionId: string,
): Promise<ChatSessionDeleteResponse> {
  return request<ChatSessionDeleteResponse>(`/chat/sessions/${sessionId}`, {
    method: "DELETE",
  });
}

export async function sendChatMessage(
  payload: SendChatMessagePayload,
): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listFeedback(all = false): Promise<FeedbackRecord[]> {
  const response = await request<FeedbackListResponse>(all ? "/feedback?all=true" : "/feedback");
  return response.feedback;
}

export async function submitFeedback(
  payload: SubmitFeedbackPayload,
): Promise<FeedbackRecord> {
  return request<FeedbackRecord>("/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getDeveloperDashboard(): Promise<DeveloperDashboardResponse> {
  return request<DeveloperDashboardResponse>("/admin/dashboard");
}

export async function runEvaluations(
  payload: EvaluationRunRequest = { run_all: true },
): Promise<EvaluationRunResponse> {
  return request<EvaluationRunResponse>("/eval/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getEvaluationResults(): Promise<EvaluationRunResponse[]> {
  const response = await request<EvaluationResultsListResponse>("/eval/results");
  return response.runs;
}
