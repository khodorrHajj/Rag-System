import { useEffect, useRef } from "react";

type UsePollingOptions = {
  enabled?: boolean;
  runOnFocus?: boolean;
};

export function usePolling(
  callback: () => void | Promise<void>,
  intervalMs: number | null,
  options?: UsePollingOptions,
) {
  const enabled = options?.enabled ?? true;
  const runOnFocus = options?.runOnFocus ?? true;
  const callbackRef = useRef(callback);
  const inFlightRef = useRef(false);

  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled || !intervalMs || intervalMs <= 0) {
      return;
    }

    function runPoll() {
      if (document.visibilityState === "hidden" || inFlightRef.current) {
        return;
      }

      inFlightRef.current = true;
      Promise.resolve(callbackRef.current()).finally(() => {
        inFlightRef.current = false;
      });
    }

    const intervalId = window.setInterval(runPoll, intervalMs);

    if (!runOnFocus) {
      return () => {
        window.clearInterval(intervalId);
      };
    }

    function handleVisibilityOrFocus() {
      if (document.visibilityState === "visible") {
        runPoll();
      }
    }

    document.addEventListener("visibilitychange", handleVisibilityOrFocus);
    window.addEventListener("focus", handleVisibilityOrFocus);

    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener(
        "visibilitychange",
        handleVisibilityOrFocus,
      );
      window.removeEventListener("focus", handleVisibilityOrFocus);
    };
  }, [enabled, intervalMs, runOnFocus]);
}
