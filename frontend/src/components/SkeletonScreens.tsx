type RouteSkeletonProps = {
  variant: "app" | "auth";
};

export function RouteSkeleton({ variant }: RouteSkeletonProps) {
  if (variant === "auth") {
    return (
      <main className="auth-page">
        <section className="auth-card auth-card--centered skeleton-card" aria-hidden="true">
          <div className="auth-card__intro">
            <div className="skeleton skeleton--eyebrow" />
            <div className="skeleton skeleton--title-auth" />
            <div className="skeleton skeleton--text" />
            <div className="skeleton skeleton--text skeleton--text-medium" />
          </div>

          <div className="skeleton-form">
            {Array.from({ length: 3 }).map((_, index) => (
              <div key={index} className="skeleton-form__field">
                <div className="skeleton skeleton--label" />
                <div className="skeleton skeleton--input" />
              </div>
            ))}
            <div className="skeleton skeleton--button skeleton--button-full" />
          </div>
        </section>
      </main>
    );
  }

  return (
    <div className="workspace-shell skeleton-shell" aria-hidden="true">
      <aside className="workspace-shell__sidebar">
        <div className="brand-lockup">
          <div className="skeleton skeleton--eyebrow" />
          <div className="skeleton skeleton--sidebar-title" />
          <div className="skeleton skeleton--text skeleton--text-medium" />
          <div className="skeleton skeleton--text skeleton--text-short" />
        </div>

        <div className="workspace-nav">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="skeleton skeleton--nav-item" />
          ))}
        </div>

        <div className="panel panel--sidebar skeleton-card">
          <div className="skeleton skeleton--eyebrow" />
          <div className="skeleton skeleton--section-title" />
          <div className="skeleton skeleton--text skeleton--text-medium" />
          <div className="skeleton skeleton--text skeleton--text-short" />
        </div>

        <div className="workspace-shell__account skeleton-card">
          <div className="skeleton skeleton--label" />
          <div className="skeleton skeleton--text skeleton--text-medium" />
          <div className="skeleton skeleton--button skeleton--button-full" />
        </div>
      </aside>

      <main className="workspace-shell__main">
        <div className="page-stack">
          <div className="dashboard-skeleton__header">
            <div className="dashboard-skeleton__header-copy">
              <div className="skeleton skeleton--eyebrow" />
              <div className="skeleton skeleton--title-lg" />
              <div className="skeleton skeleton--title-md" />
            </div>
            <div className="skeleton skeleton--button" />
          </div>

          <section className="status-grid">
            {Array.from({ length: 4 }).map((_, index) => (
              <article key={index} className="status-card dashboard-skeleton__card">
                <div className="skeleton skeleton--eyebrow" />
                <div className="skeleton skeleton--value" />
              </article>
            ))}
          </section>
        </div>
      </main>
    </div>
  );
}

export function DocumentsPageSkeleton() {
  return (
    <div className="page-stack dashboard-skeleton" aria-hidden="true">
      <div className="dashboard-skeleton__header">
        <div className="dashboard-skeleton__header-copy">
          <div className="skeleton skeleton--eyebrow" />
          <div className="skeleton skeleton--title-lg" />
          <div className="skeleton skeleton--text" />
        </div>
        <div className="skeleton skeleton--button" />
      </div>

      <section className="status-grid status-grid--compact">
        {Array.from({ length: 3 }).map((_, index) => (
          <article key={index} className="status-card dashboard-skeleton__card">
            <div className="skeleton skeleton--eyebrow" />
            <div className="skeleton skeleton--value" />
          </article>
        ))}
      </section>

      <section className="panel skeleton-card skeleton-panel">
        <div className="panel__header">
          <div>
            <div className="skeleton skeleton--eyebrow" />
            <div className="skeleton skeleton--section-title" />
          </div>
        </div>

        <div className="skeleton skeleton--text" />
        <div className="skeleton skeleton--text skeleton--text-medium" />
        <div className="upload-dropzone skeleton-dropzone">
          <div className="skeleton skeleton--label" />
          <div className="skeleton skeleton--text skeleton--text-medium" />
          <div className="skeleton skeleton--input" />
        </div>
        <div className="button-row">
          <div className="skeleton skeleton--button" />
          <div className="skeleton skeleton--text skeleton--text-medium" />
        </div>
      </section>

      <section className="panel skeleton-card skeleton-panel">
        <div className="panel__header">
          <div>
            <div className="skeleton skeleton--eyebrow" />
            <div className="skeleton skeleton--section-title" />
          </div>
        </div>

        <div className="document-list">
          {Array.from({ length: 3 }).map((_, index) => (
            <article key={index} className="document-card skeleton-card">
              <div className="document-card__topline">
                <div className="dashboard-skeleton__list-copy">
                  <div className="skeleton skeleton--text skeleton--text-medium" />
                  <div className="skeleton skeleton--text skeleton--text-short" />
                </div>
                <div className="skeleton skeleton--badge" />
              </div>
              <div className="document-card__details skeleton-metrics">
                {Array.from({ length: 3 }).map((__, detailIndex) => (
                  <div key={detailIndex}>
                    <div className="skeleton skeleton--label" />
                    <div className="skeleton skeleton--text skeleton--text-short" />
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

export function ConversationSkeleton() {
  return (
    <div className="message-thread" aria-hidden="true">
      {Array.from({ length: 3 }).map((_, index) => (
        <article
          key={index}
          className={`message-bubble ${index % 2 === 0 ? "message-bubble--assistant" : "message-bubble--user"}`}
        >
          <div className="message-bubble__header">
            <div className="dashboard-skeleton__list-copy">
              <div className="skeleton skeleton--label" />
              <div className="skeleton skeleton--text skeleton--text-short" />
            </div>
            <div className="skeleton skeleton--badge" />
          </div>

          <div className="dashboard-skeleton__list-copy">
            <div className="skeleton skeleton--text" />
            <div className="skeleton skeleton--text skeleton--text-medium" />
            <div className="skeleton skeleton--text skeleton--text-short" />
          </div>
        </article>
      ))}
    </div>
  );
}

export function ChatPageSkeleton() {
  return (
    <div className="page-stack dashboard-skeleton" aria-hidden="true">
      <div className="dashboard-skeleton__header">
        <div className="dashboard-skeleton__header-copy">
          <div className="skeleton skeleton--eyebrow" />
          <div className="skeleton skeleton--title-lg" />
          <div className="skeleton skeleton--text" />
          <div className="skeleton skeleton--text skeleton--text-medium" />
        </div>
        <div className="button-row">
          <div className="skeleton skeleton--toggle" />
          <div className="skeleton skeleton--button" />
        </div>
      </div>

      <section className="chat-layout">
        <aside className="chat-sidebar panel panel--section skeleton-card">
          <div className="panel__header">
            <div>
              <div className="skeleton skeleton--eyebrow" />
              <div className="skeleton skeleton--section-title" />
            </div>
          </div>

          <div className="session-list">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="skeleton skeleton--session-item" />
            ))}
          </div>

          <div className="document-filter">
            <div className="skeleton skeleton--eyebrow" />
            <div className="skeleton skeleton--text skeleton--text-short" />
            <div className="skeleton skeleton--text skeleton--text-medium" />
            <div className="dashboard-skeleton__list">
              {Array.from({ length: 3 }).map((_, index) => (
                <div key={index} className="skeleton skeleton--checkbox-row" />
              ))}
            </div>
          </div>
        </aside>

        <section className="chat-main">
          <article className="panel panel--section panel--chat-surface skeleton-card">
            <div className="panel__header">
              <div>
                <div className="skeleton skeleton--eyebrow" />
                <div className="skeleton skeleton--section-title" />
              </div>
            </div>
            <ConversationSkeleton />
          </article>

          <article className="panel panel--section chat-composer-panel skeleton-card">
            <div className="dashboard-skeleton__list-copy">
              <div className="skeleton skeleton--label" />
              <div className="skeleton skeleton--textarea" />
            </div>
            <div className="button-row">
              <div className="skeleton skeleton--button" />
              <div className="skeleton skeleton--text skeleton--text-medium" />
            </div>
          </article>
        </section>
      </section>
    </div>
  );
}
