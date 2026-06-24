export function buildBackendUnavailableMessage(apiBaseUrl: string): string {
  return `Could not reach the backend API at ${apiBaseUrl}. Start the FastAPI server and confirm the API URL and CORS settings.`;
}

export function isNetworkFetchError(error: unknown): boolean {
  return (
    error instanceof TypeError
    || (
      error instanceof Error
      && error.message.toLowerCase().includes("failed to fetch")
    )
  );
}
