import type { Ticket, Report } from "@/types";

// Local dev: set VITE_TICKET_SERVICE_URL + VITE_TICKET_API_KEY to hit Lambda directly.
// Production: empty → relative URLs routed through CloudFront.
const TICKET_URL = (import.meta.env.VITE_TICKET_SERVICE_URL as string) ?? "";
const API_KEY = (import.meta.env.VITE_TICKET_API_KEY as string) ?? "";

function ticketHeaders(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (API_KEY) h["x-api-key"] = API_KEY;
  return h;
}

function ticketBase(): string {
  return TICKET_URL ? `${TICKET_URL}/tickets` : "/api/tickets";
}

const FETCH_TIMEOUT_MS = 20_000;
const MAX_RETRIES = 1;

async function fetchWithRetry(url: string, options: RequestInit, retries = MAX_RETRIES): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const resp = await fetch(url, { ...options, signal: controller.signal });
    return resp;
  } catch (err) {
    if (retries > 0 && err instanceof DOMException && err.name === "AbortError") {
      return fetchWithRetry(url, options, retries - 1);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function listTickets(filters?: {
  status?: string;
  category?: string;
  limit?: number;
}): Promise<Ticket[]> {
  const params = new URLSearchParams();
  if (filters?.status) params.set("status", filters.status);
  if (filters?.category) params.set("category", filters.category);
  if (filters?.limit) params.set("limit", String(filters.limit));
  const qs = params.toString();
  const resp = await fetchWithRetry(`${ticketBase()}${qs ? `?${qs}` : ""}`, {
    headers: ticketHeaders(),
  });
  if (!resp.ok) throw new Error(`Ticket Service error: ${resp.status}`);
  return resp.json() as Promise<Ticket[]>;
}

export async function getTicket(id: string): Promise<Ticket> {
  const resp = await fetch(`${ticketBase()}/${id}`, {
    headers: ticketHeaders(),
  });
  if (!resp.ok) throw new Error(`Ticket not found: ${id}`);
  return resp.json() as Promise<Ticket>;
}

const REPORTS_URL = (import.meta.env.VITE_REPORTS_SERVICE_URL as string) ?? "";
const REPORTS_API_KEY = (import.meta.env.VITE_REPORTS_API_KEY as string) ?? "";

function reportsHeaders(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (REPORTS_API_KEY) h["x-api-key"] = REPORTS_API_KEY;
  return h;
}

function reportsBase(): string {
  return REPORTS_URL ? `${REPORTS_URL}/reports` : "/api/reports";
}

export async function listReports(filters?: {
  type?: string;
  limit?: number;
}): Promise<Report[]> {
  const params = new URLSearchParams();
  if (filters?.type) params.set("type", filters.type);
  if (filters?.limit) params.set("limit", String(filters.limit));
  const qs = params.toString();
  const resp = await fetchWithRetry(`${reportsBase()}${qs ? `?${qs}` : ""}`, {
    headers: reportsHeaders(),
  });
  if (!resp.ok) throw new Error(`Reports Service error: ${resp.status}`);
  return resp.json() as Promise<Report[]>;
}

export async function getReport(id: string): Promise<Report> {
  const resp = await fetchWithRetry(`${reportsBase()}/${id}`, {
    headers: reportsHeaders(),
  });
  if (!resp.ok) throw new Error(`Report not found: ${id}`);
  return resp.json() as Promise<Report>;
}

export async function sendChat(
  message: string,
  userId: string,
  sessionId: string
): Promise<string> {
  // Production: CloudFront routes /api/chat → chat-proxy Lambda (OAC-protected).
  // Local dev: Vite proxy forwards /api/chat → proxy.py on localhost:8001.
  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, userId, sessionId }),
  });
  if (!resp.ok) throw new Error(`Chat error: ${resp.status}`);
  const data = (await resp.json()) as { response: string };
  return data.response;
}
