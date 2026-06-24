import { useEffect, useState } from "react";

import { fetchHealth } from "../api/health";
import type { HealthResponse } from "../types/health";

type UseHealthCheckResult = {
  health: HealthResponse | null;
  error: string | null;
  loading: boolean;
};

export function useHealthCheck(): UseHealthCheckResult {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;

    async function loadHealth() {
      try {
        const response = await fetchHealth();

        if (isMounted) {
          setHealth(response);
          setError(null);
        }
      } catch (err) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : "Unknown error");
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }

    void loadHealth();

    return () => {
      isMounted = false;
    };
  }, []);

  return { health, error, loading };
}

