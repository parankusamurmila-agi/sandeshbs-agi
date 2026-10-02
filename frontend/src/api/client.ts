import type { Correspondence, CorrespondenceSummary, HaRequest, AuditEntry } from "../types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, init);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.json() as Promise<T>;
}

export function uploadCorrespondence(file: File): Promise<Correspondence> {
  const formData = new FormData();
  formData.append("file", file);
  return request<Correspondence>("/correspondence", { method: "POST", body: formData });
}

export function listCorrespondence(): Promise<CorrespondenceSummary[]> {
  return request<CorrespondenceSummary[]>("/correspondence");
}

export function getCorrespondence(id: string): Promise<Correspondence> {
  return request<Correspondence>(`/correspondence/${id}`);
}

export function generateDraft(
  correspondenceId: string,
  requestId: string,
  direction: string | null,
): Promise<HaRequest> {
  return request<HaRequest>(`/correspondence/${correspondenceId}/requests/${requestId}/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ direction }),
  });
}

export function updateDraft(
  correspondenceId: string,
  requestId: string,
  body: { text?: string; action?: "edit" | "approve"; actor: string },
): Promise<HaRequest> {
  return request<HaRequest>(`/correspondence/${correspondenceId}/requests/${requestId}/draft`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getAudit(correspondenceId: string, requestId: string): Promise<AuditEntry[]> {
  return request<AuditEntry[]>(`/correspondence/${correspondenceId}/requests/${requestId}/audit`);
}
