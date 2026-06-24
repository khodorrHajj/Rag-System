import { Fragment, type ReactNode } from "react";

type SafeMarkdownTextProps = {
  text: string;
};

function renderInlineMarkdown(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /\*\*(.+?)\*\*|\*(.+?)\*/g;
  let lastIndex = 0;
  let matchIndex = 0;

  for (const match of text.matchAll(pattern)) {
    const matchStart = match.index ?? 0;

    if (matchStart > lastIndex) {
      nodes.push(text.slice(lastIndex, matchStart));
    }

    if (match[1]) {
      nodes.push(<strong key={`bold-${matchIndex}`}>{match[1]}</strong>);
    } else if (match[2]) {
      nodes.push(<em key={`italic-${matchIndex}`}>{match[2]}</em>);
    }

    lastIndex = matchStart + match[0].length;
    matchIndex += 1;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}

export function SafeMarkdownText({ text }: SafeMarkdownTextProps) {
  const lines = text.split("\n");

  return (
    <>
      {lines.map((line, index) => (
        <Fragment key={`line-${index}`}>
          {renderInlineMarkdown(line)}
          {index < lines.length - 1 ? <br /> : null}
        </Fragment>
      ))}
    </>
  );
}
