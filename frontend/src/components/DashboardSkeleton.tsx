export function DashboardSkeleton() {
  return (
    <>
      <div className="dashboard-skeleton" aria-busy="true" aria-hidden="true">
        <section className="dashboard-skeleton__header">
          <div className="dashboard-skeleton__header-copy">
            <div className="skeleton skeleton--eyebrow" />
            <div className="skeleton skeleton--title-lg" />
            <div className="skeleton skeleton--title-md" />
            <div className="skeleton skeleton--text" />
          </div>
          <div className="skeleton skeleton--button" />
        </section>

        <section className="status-grid">
          {Array.from({ length: 4 }).map((_, index) => (
            <article key={index} className="status-card dashboard-skeleton__card">
              <div className="skeleton skeleton--eyebrow" />
              <div className="skeleton skeleton--value" />
            </article>
          ))}
        </section>

        <section className="quick-links">
          {Array.from({ length: 2 }).map((_, index) => (
            <article key={index} className="quick-link dashboard-skeleton__panel">
              <div className="skeleton skeleton--text" />
              <div className="skeleton skeleton--text skeleton--text-short" />
            </article>
          ))}
        </section>

        <section className="dashboard-grid">
          {Array.from({ length: 2 }).map((_, index) => (
            <article key={index} className="panel dashboard-skeleton__panel">
              <div className="dashboard-skeleton__panel-header">
                <div>
                  <div className="skeleton skeleton--eyebrow" />
                  <div className="skeleton skeleton--section-title" />
                </div>
                <div className="skeleton skeleton--link" />
              </div>

              <div className="dashboard-skeleton__list">
                {Array.from({ length: 4 }).map((_, rowIndex) => (
                  <div key={rowIndex} className="dashboard-skeleton__list-row">
                    <div className="dashboard-skeleton__list-copy">
                      <div className="skeleton skeleton--text skeleton--text-medium" />
                      <div className="skeleton skeleton--text skeleton--text-short" />
                    </div>
                    <div className="skeleton skeleton--badge" />
                  </div>
                ))}
              </div>
            </article>
          ))}
        </section>
      </div>

      <div className="visually-hidden" role="status" aria-live="polite">
        Loading workspace summary...
      </div>
    </>
  );
}
