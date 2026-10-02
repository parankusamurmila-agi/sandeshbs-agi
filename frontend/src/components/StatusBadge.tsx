import type { RequestStatus } from "../types";

export default function StatusBadge({ status }: { status: RequestStatus }) {
  return <span className={`status-badge status-${status}`}>{status}</span>;
}
