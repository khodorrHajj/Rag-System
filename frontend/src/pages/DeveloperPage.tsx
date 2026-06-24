import { useDeferredValue, useEffect, useState } from "react";

import {
  getDeveloperDashboard,
  getEvaluationResults,
  runEvaluations,
} from "../api";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { usePolling } from "../hooks/usePolling";
import { formatTimestamp } from "../lib/format";
import type {
  DeveloperDashboardResponse,
  EvaluationRunResponse,
} from "../types/api";

function formatLatency(value: number | null): string {
  if (value === null) {
    return "N/A";
  }

  return `${Math.round(value)} ms`;
}

function matchesSearch(
  searchTerm: string,
  values: Array<string | number | null | undefined>,
): boolean {
  if (!searchTerm) {
    return true;
  }

  return values.some((value) =>
    String(value ?? "")
      .toLowerCase()
      .includes(searchTerm),
  );
}

function summarizeMetadata(metadata: Record<string, unknown>): string | null {
  const preview = Object.entries(metadata)
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" | ");

  return preview || null;
}

function DeveloperPageSkeleton() {
  return (
    <div className="page-stack" aria-hidden="true">
      <div className="skeleton skeleton--header" />
      <div className="metrics-grid">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="panel panel--metric">
            <div className="skeleton skeleton--metric-label" />
            <div className="skeleton skeleton--metric-value" />
          </div>
        ))}
      </div>
      <div className="panel-grid panel-grid--developer">
        {Array.from({ length: 4 }).map((_, index) => (
          <section key={index} className="panel panel--section">
            <div className="skeleton skeleton--card-title" />
            <div className="skeleton skeleton--line" />
            <div className="skeleton skeleton--line" />
            <div className="skeleton skeleton--line short" />
          </section>
        ))}
      </div>
    </div>
  );
}

export function DeveloperPage() {
  const [dashboard, setDashboard] = useState<DeveloperDashboardResponse | null>(
    null,
  );
  const [evaluationRuns, setEvaluationRuns] = useState<EvaluationRunResponse[]>(
    [],
  );
  const [loading, setLoading] = useState(true);
  const [runningEvaluations, setRunningEvaluations] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const deferredSearchQuery = useDeferredValue(searchQuery);

  async function loadDeveloperData(options?: { background?: boolean }) {
    const background = options?.background ?? false;
    if (!background) {
      setLoading(true);
    }

    try {
      const [dashboardResponse, evalResults] = await Promise.all([
        getDeveloperDashboard(),
        getEvaluationResults(),
      ]);
      setDashboard(dashboardResponse);
      setEvaluationRuns(evalResults);
      setPageError(null);
    } catch (loadError) {
      setPageError(
        loadError instanceof Error
          ? loadError.message
          : "Could not load developer monitoring data.",
      );
    } finally {
      if (!background) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    void loadDeveloperData();
  }, []);

  usePolling(() => loadDeveloperData({ background: true }), 20000, {
    enabled: !loading,
  });

  async function handleRunEvaluations() {
    setRunningEvaluations(true);
    setPageError(null);

    try {
      const run = await runEvaluations({ run_all: true });
      setEvaluationRuns((currentRuns) => [run, ...currentRuns]);
      await loadDeveloperData({ background: true });
    } catch (runError) {
      setPageError(
        runError instanceof Error
          ? runError.message
          : "Could not run evaluation cases.",
      );
    } finally {
      setRunningEvaluations(false);
    }
  }

  if (loading) {
    return <DeveloperPageSkeleton />;
  }

  if (!dashboard) {
    return (
      <div className="page-stack">
        <PageHeader eyebrow="Developer view" title="Monitoring and quality" />
        {pageError ? (
          <div className="alert alert--error">{pageError}</div>
        ) : null}
      </div>
    );
  }

  const normalizedSearchQuery = deferredSearchQuery.trim().toLowerCase();
  const filteredRetrievalLogs = dashboard.recent_retrieval_logs.filter((log) =>
    matchesSearch(normalizedSearchQuery, [
      log.query,
      log.original_question,
      log.user_email,
      log.user_id,
      log.retrieved_chunk_count,
      log.latency_ms,
      log.top_k,
      log.threshold,
    ]),
  );
  const filteredAuditLogs = dashboard.recent_audit_logs.filter((log) =>
    matchesSearch(normalizedSearchQuery, [
      log.action,
      log.user_email,
      log.user_id,
      log.resource_type,
      log.resource_id,
      log.ip_address,
      summarizeMetadata(log.metadata),
    ]),
  );
  const filteredFeedback = dashboard.recent_feedback.filter((feedback) =>
    matchesSearch(normalizedSearchQuery, [
      feedback.rating,
      feedback.user_email,
      feedback.user_id,
      feedback.comment,
    ]),
  );
  const filteredEvaluationRuns = evaluationRuns.filter((run) =>
    matchesSearch(normalizedSearchQuery, [
      run.run_mode,
      run.created_at,
      run.case_count,
      run.passed_count,
      ...run.results.flatMap((result) => [
        result.case_name,
        result.question,
        result.expected_source_file,
        result.answer_preview,
        result.latency_ms,
      ]),
    ]),
  );
  const feedbackTotal =
    dashboard.metrics.positive_feedback + dashboard.metrics.negative_feedback;
  const latestEvaluationRun = evaluationRuns[0] ?? null;
  const totalSearchMatches =
    filteredRetrievalLogs.length +
    filteredAuditLogs.length +
    filteredFeedback.length +
    filteredEvaluationRuns.length;

  return (
    <div className="page-stack developer-page">
      <PageHeader
        actions={
          <div className="button-row developer-header__actions">
            <label className="field developer-search">
              <span className="visually-hidden">Search developer data</span>
              <input
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search queries, events, users, feedback, evaluations"
                type="search"
                value={searchQuery}
              />
            </label>
            {searchQuery.trim() ? (
              <button
                className="button button--ghost button--compact"
                onClick={() => setSearchQuery("")}
                type="button"
              >
                Clear
              </button>
            ) : null}
            <button
              className="button button--primary button--developer-action"
              disabled={runningEvaluations}
              onClick={() => void handleRunEvaluations()}
              type="button"
            >
              {runningEvaluations ? "Running..." : "Run evaluation suite"}
            </button>
          </div>
        }
        eyebrow="Developer view"
        title="Monitoring and quality"
      />

      {pageError ? <div className="alert alert--error">{pageError}</div> : null}

      <section className="panel developer-hero">
        <div className="developer-hero__grid">
          <article className="developer-spotlight developer-spotlight--signal">
            <p className="panel__eyebrow">Search quality</p>
            <h2>Retrieval confidence watch</h2>
            <p className="developer-spotlight__value">
              {dashboard.metrics.low_confidence_retrievals} low-confidence
              retrieval
              {dashboard.metrics.low_confidence_retrievals === 1 ? "" : "s"}
            </p>
            <p className="developer-spotlight__meta">
              Average latency{" "}
              {formatLatency(dashboard.metrics.average_retrieval_latency_ms)}
            </p>
          </article>

          <article className="developer-spotlight developer-spotlight--ops">
            <p className="panel__eyebrow">System activity</p>
            <h2>Indexing and storage</h2>
            <p className="developer-spotlight__value">
              {dashboard.metrics.indexed_documents} indexed docs ·{" "}
              {dashboard.metrics.total_chunks} chunks
            </p>
            <p className="developer-spotlight__meta">
              {dashboard.metrics.failed_indexing_jobs} failed indexing job
              {dashboard.metrics.failed_indexing_jobs === 1 ? "" : "s"}
            </p>
          </article>

          <article className="developer-spotlight developer-spotlight--feedback">
            <p className="panel__eyebrow">Human signal</p>
            <h2>Feedback and evaluations</h2>
            <p className="developer-spotlight__value">
              {feedbackTotal
                ? `${dashboard.metrics.positive_feedback} positive · ${dashboard.metrics.negative_feedback} negative`
                : "No feedback yet"}
            </p>
            <p className="developer-spotlight__meta">
              {latestEvaluationRun
                ? `Latest suite: ${latestEvaluationRun.passed_count}/${latestEvaluationRun.case_count} passed`
                : "Run the evaluation suite to create a baseline"}
            </p>
          </article>
        </div>
      </section>

      <section className="panel developer-toolbar">
        <div className="developer-toolbar__row">
          <div>
            <p className="panel__eyebrow">Browse diagnostics</p>
            <h2>Focused sections</h2>
          </div>
          <div className="developer-anchor-row">
            <a className="developer-anchor" href="#developer-retrievals">
              Retrievals
            </a>
            <a className="developer-anchor" href="#developer-events">
              Events
            </a>
            <a className="developer-anchor" href="#developer-feedback">
              Feedback
            </a>
            <a className="developer-anchor" href="#developer-evaluations">
              Evaluations
            </a>
          </div>
        </div>

        <div className="developer-toolbar__summary">
          <p className="inline-detail">
            {normalizedSearchQuery
              ? `Showing ${totalSearchMatches} search match${totalSearchMatches === 1 ? "" : "es"} across all sections for "${searchQuery.trim()}".`
              : ""}
          </p>
        </div>
      </section>

      <section className="metrics-grid">
        <article className="panel panel--metric">
          <p className="panel__eyebrow">Indexed documents</p>
          <strong>{dashboard.metrics.indexed_documents}</strong>
        </article>
        <article className="panel panel--metric">
          <p className="panel__eyebrow">Stored chunks</p>
          <strong>{dashboard.metrics.total_chunks}</strong>
        </article>
        <article className="panel panel--metric">
          <p className="panel__eyebrow">Low-confidence retrievals</p>
          <strong>{dashboard.metrics.low_confidence_retrievals}</strong>
        </article>
        <article className="panel panel--metric">
          <p className="panel__eyebrow">Failed indexing jobs</p>
          <strong>{dashboard.metrics.failed_indexing_jobs}</strong>
        </article>
        <article className="panel panel--metric">
          <p className="panel__eyebrow">Feedback split</p>
          <strong>
            {dashboard.metrics.positive_feedback} /{" "}
            {dashboard.metrics.negative_feedback}
          </strong>
        </article>
        <article className="panel panel--metric">
          <p className="panel__eyebrow">Avg retrieval latency</p>
          <strong>
            {formatLatency(dashboard.metrics.average_retrieval_latency_ms)}
          </strong>
        </article>
      </section>

      <section className="panel-grid panel-grid--developer panel-grid--developer-enhanced">
        <article id="developer-retrievals" className="panel panel--section">
          <div className="panel__header">
            <div>
              <p className="panel__eyebrow">Recent retrievals</p>
              <h2>Search diagnostics</h2>
            </div>
            <span className="developer-count-pill">
              {filteredRetrievalLogs.length} shown
            </span>
          </div>
          <p className="panel__description">
            Review what users asked, how many chunks were returned, and whether
            latency or threshold settings need attention.
          </p>
          {filteredRetrievalLogs.length ? (
            <div className="developer-list">
              {filteredRetrievalLogs.map((log) => (
                <div key={log.log_id} className="developer-list__item">
                  <p className="developer-list__title">
                    {log.original_question ?? log.query}
                  </p>
                  {log.original_question &&
                  log.original_question !== log.query ? (
                    <p className="developer-list__body">
                      Retrieval query: {log.query}
                    </p>
                  ) : null}
                  <p className="developer-list__meta">
                    {log.user_email ?? log.user_id} |{" "}
                    {log.retrieved_chunk_count} chunks |{" "}
                    {formatLatency(log.latency_ms)}
                  </p>
                  <p className="developer-list__meta">
                    Top K {log.top_k} | Threshold {log.threshold ?? "default"} |{" "}
                    {formatTimestamp(log.created_at)}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              title={
                normalizedSearchQuery
                  ? "No retrieval matches"
                  : "No retrieval logs yet"
              }
              description={
                normalizedSearchQuery
                  ? "Try a broader search term to find retrieval activity."
                  : "Retrieval activity will appear here."
              }
            />
          )}
        </article>

        <article id="developer-events" className="panel panel--section">
          <div className="panel__header">
            <div>
              <p className="panel__eyebrow">Recent audit logs</p>
              <h2>System events</h2>
            </div>
            <span className="developer-count-pill">
              {filteredAuditLogs.length} shown
            </span>
          </div>
          <p className="panel__description">
            Keep an eye on chat lifecycle events, indexing operations, and
            activity trails grouped by user and resource.
          </p>
          {filteredAuditLogs.length ? (
            <div className="developer-list">
              {filteredAuditLogs.map((log) => (
                <div key={log.log_id} className="developer-list__item">
                  <p className="developer-list__title">{log.action}</p>
                  <p className="developer-list__meta">
                    {log.user_email ?? log.user_id ?? "system"} |{" "}
                    {log.resource_type ?? "resource"} |{" "}
                    {formatTimestamp(log.created_at)}
                  </p>
                  {summarizeMetadata(log.metadata) ? (
                    <p className="developer-list__body">
                      {summarizeMetadata(log.metadata)}
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              title={
                normalizedSearchQuery ? "No event matches" : "No audit logs yet"
              }
              description={
                normalizedSearchQuery
                  ? "Try another keyword to surface matching system events."
                  : "System events will appear here."
              }
            />
          )}
        </article>

        <article id="developer-feedback" className="panel panel--section">
          <div className="panel__header">
            <div>
              <p className="panel__eyebrow">Recent feedback</p>
              <h2>Answer ratings</h2>
            </div>
            <span className="developer-count-pill">
              {filteredFeedback.length} shown
            </span>
          </div>
          <p className="panel__description">
            Read the latest positive and negative signals to understand where
            the assistant is earning trust or missing the mark.
          </p>
          {filteredFeedback.length ? (
            <div className="developer-list">
              {filteredFeedback.map((feedback) => (
                <div
                  key={feedback.feedback_id}
                  className="developer-list__item"
                >
                  <div className="developer-list__split">
                    <p className="developer-list__title">
                      {feedback.rating === "positive" ? "Positive" : "Negative"}{" "}
                      feedback
                    </p>
                    <span
                      className={`developer-tone-pill ${
                        feedback.rating === "positive"
                          ? "developer-tone-pill--positive"
                          : "developer-tone-pill--negative"
                      }`}
                    >
                      {feedback.rating}
                    </span>
                  </div>
                  <p className="developer-list__meta">
                    {feedback.user_email ?? feedback.user_id} |{" "}
                    {formatTimestamp(feedback.created_at)}
                  </p>
                  {feedback.comment ? (
                    <p className="developer-list__body">{feedback.comment}</p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              title={
                normalizedSearchQuery
                  ? "No feedback matches"
                  : "No feedback yet"
              }
              description={
                normalizedSearchQuery
                  ? "Try a broader term to find matching feedback comments or users."
                  : "Answer ratings will appear here."
              }
            />
          )}
        </article>

        <article id="developer-evaluations" className="panel panel--section">
          <div className="panel__header">
            <div>
              <p className="panel__eyebrow">Evaluation runs</p>
              <h2>RAG quality checks</h2>
            </div>
            <span className="developer-count-pill">
              {filteredEvaluationRuns.length} shown
            </span>
          </div>
          <p className="panel__description">
            Track how your evaluation suite is trending and spot cases where
            retrieval or answers are still failing.
          </p>
          {filteredEvaluationRuns.length ? (
            <div className="developer-list">
              {filteredEvaluationRuns.map((run) => (
                <div key={run.run_id} className="developer-list__item">
                  <div className="developer-list__split">
                    <p className="developer-list__title">
                      {run.passed_count}/{run.case_count} cases passed
                    </p>
                    <span className="developer-count-pill">{run.run_mode}</span>
                  </div>
                  <p className="developer-list__meta">
                    {formatTimestamp(run.created_at)}
                  </p>
                  {run.results.slice(0, 3).map((result) => (
                    <p key={result.result_id} className="developer-list__body">
                      {result.case_name ?? result.question} | retrieval{" "}
                      {result.retrieval_passed ? "passed" : "failed"} | latency{" "}
                      {result.latency_ms} ms
                    </p>
                  ))}
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              title={
                normalizedSearchQuery
                  ? "No evaluation matches"
                  : "No evaluation runs yet"
              }
              description={
                normalizedSearchQuery
                  ? "Search by case name, question text, or source file to find a run."
                  : "Run the evaluation suite to populate results."
              }
            />
          )}
        </article>
      </section>
    </div>
  );
}
