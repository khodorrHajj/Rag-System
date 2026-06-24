type CitationListItem = {
  chunkId: string;
  pageNumber: number | null;
  score?: number | null;
  sectionTitle: string | null;
  sourceFile: string;
  sourceNumber: number;
};

type CitationListProps = {
  items: CitationListItem[];
  showScores?: boolean;
};

export function CitationList({
  items,
  showScores = false,
}: CitationListProps) {
  if (!items.length) {
    return null;
  }

  return (
    <section className="citation-list">
      <p className="citation-list__title">Sources</p>
      <ul className="citation-list__items">
        {items.map((item) => (
          <li
            key={`${item.sourceNumber}-${item.chunkId}`}
            className="citation-list__item"
          >
            <div className="citation-list__row">
              <span className="citation-list__badge">
                Source {item.sourceNumber}
              </span>
              <p className="citation-list__file">{item.sourceFile}</p>
            </div>
            <p className="citation-list__meta">
              {item.pageNumber ? `Page ${item.pageNumber}` : "Page unavailable"}
              {item.sectionTitle ? ` | ${item.sectionTitle}` : ""}
              {showScores && item.score != null
                ? ` | score ${item.score.toFixed(2)}`
                : ""}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
