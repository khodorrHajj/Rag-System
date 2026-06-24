import { titleCaseStatus } from "../lib/format";

type StatusBadgeProps = {
  status: string;
};

const toneByStatus: Record<string, string> = {
  uploaded: "status-badge--uploaded",
  queued: "status-badge--queued",
  processing: "status-badge--processing",
  parsed: "status-badge--processing",
  chunked: "status-badge--processing",
  indexed: "status-badge--indexed",
  failed: "status-badge--failed",
  deleted: "status-badge--deleted",
};

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span className={`status-badge ${toneByStatus[status] ?? "status-badge--default"}`}>
      {titleCaseStatus(status)}
    </span>
  );
}
