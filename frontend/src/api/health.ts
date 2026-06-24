import type { HealthResponse } from "../types/health";
import { frontendEnv } from "../lib/env";
import { buildBackendUnavailableMessage, isNetworkFetchError } from "../lib/api-errors";

export async function fetchHealth(): Promise<HealthResponse> {
  let response: Response;

  try {
    response = await fetch(`${frontendEnv.apiBaseUrl}/health`);
  } catch (error) {
    if (isNetworkFetchError(error)) {
      throw new Error(buildBackendUnavailableMessage(frontendEnv.apiBaseUrl));
    }

    throw error;
  }

  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`);
  }

  return response.json() as Promise<HealthResponse>;
}
