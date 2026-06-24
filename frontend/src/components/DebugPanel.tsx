import type { ChatDebugInfo } from "../types/api";

type DebugPanelProps = {
  debug: ChatDebugInfo;
  retrievalPassed: boolean;
};

export function DebugPanel({ debug, retrievalPassed }: DebugPanelProps) {
  return (
    <details className="debug-disclosure">
      <summary className="debug-disclosure__summary">
        <span>Debug retrieval details</span>
        <span className={`debug-panel__state ${retrievalPassed ? "debug-panel__state--pass" : "debug-panel__state--fail"}`}>
          {retrievalPassed ? "retrieval passed" : "retrieval low confidence"}
        </span>
      </summary>

      <section className="debug-panel">
        <div className="debug-panel__header">
          <div>
            <p className="debug-panel__eyebrow">Developer Debug</p>
            <h2>Grounded Retrieval Snapshot</h2>
          </div>
        </div>

        <dl className="debug-panel__metrics">
          <div>
            <dt>Original question</dt>
            <dd>{debug.original_question}</dd>
          </div>
          <div>
            <dt>Retrieval query</dt>
            <dd>{debug.retrieval_query}</dd>
          </div>
          <div>
            <dt>History rewrite used</dt>
            <dd>{debug.history_used_for_rewrite ? "Yes" : "No"}</dd>
          </div>
          <div>
            <dt>Top K</dt>
            <dd>{debug.retrieval.top_k}</dd>
          </div>
          <div>
            <dt>Threshold</dt>
            <dd>{debug.retrieval.threshold ?? "n/a"}</dd>
          </div>
          <div>
            <dt>Latency</dt>
            <dd>{debug.retrieval.latency_ms} ms</dd>
          </div>
        </dl>

        <div className="debug-panel__chunks">
          {debug.chunks.map((chunk) => (
            <article key={chunk.chunk_id} className="debug-panel__chunk">
              <div className="debug-panel__chunk-header">
                <p>{chunk.source_file}</p>
                <span>{chunk.combined_score.toFixed(2)}</span>
              </div>
              <p className="debug-panel__chunk-meta">
                {chunk.section_title ?? "Untitled section"}
                {chunk.vector_score != null ? ` | vector ${chunk.vector_score.toFixed(2)}` : ""}
                {chunk.keyword_score != null ? ` | keyword ${chunk.keyword_score.toFixed(2)}` : ""}
              </p>
              <pre>{chunk.content_preview}</pre>
            </article>
          ))}
        </div>
      </section>
    </details>
  );
}
