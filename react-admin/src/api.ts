// Typed client for the notification-hub API.
//
// Base URL defaults to "/api/v1" (dev-proxied by Vite to the backend); override
// with VITE_API_BASE. The bearer token, if present, is read from
// localStorage["notif_hub_token"] and multi-tenant callers may set a company id
// in localStorage["notif_hub_company_id"] (sent as X-Company-Id).

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  try {
    const token = localStorage.getItem("notif_hub_token");
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const company = localStorage.getItem("notif_hub_company_id");
    if (company) headers["X-Company-Id"] = company;
  } catch {
    // localStorage may be unavailable (private mode) — proceed unauthenticated.
  }
  return headers;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail ?? JSON.stringify(j);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ── Envelope + domain types ────────────────────────────────────────────────

/** List endpoints return { data: [...], count: N }. */
export interface ListEnvelope<T> {
  data: T[];
  count: number;
}

export interface DeliveryLog {
  id: string;
  status: string; // "sent" | "failed" | "pending" | ...
  channel: string;
  event_type: string;
  created_at: string;
  recipient?: string | null;
  error?: string | null;
}

export interface Rule {
  id: string;
  name: string;
  event_type?: string;
  is_active: boolean;
  priority: number;
  channel_ids: string[];
  recipient_strategy?: string;
  conditions?: RuleCondition[];
}

export interface RuleCondition {
  field: string;
  operator: string;
  value: unknown;
}

export interface Channel {
  id: string;
  name: string;
  type?: string;
}

export interface Preference {
  channel_id: string;
  channel: string;
  is_enabled: boolean;
  priority?: number;
}

// ── Endpoints ──────────────────────────────────────────────────────────────

export interface LogQuery {
  skip?: number;
  limit?: number;
  channel?: string;
  status?: string;
}

function qs(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  if (entries.length === 0) return "";
  return "?" + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");
}

export const api = {
  logs: (q: LogQuery = {}) =>
    request<ListEnvelope<DeliveryLog>>(
      "GET",
      `/logs${qs({ skip: q.skip, limit: q.limit, channel: q.channel, status: q.status })}`,
    ),

  rules: () => request<ListEnvelope<Rule>>("GET", "/rules"),
  createRule: (data: Partial<Rule>) => request<Rule>("POST", "/rules", data),
  updateRule: (id: string, data: Partial<Rule>) =>
    request<Rule>("PATCH", `/rules/${id}`, data),
  deleteRule: (id: string) => request<void>("DELETE", `/rules/${id}`),

  channels: () => request<ListEnvelope<Channel>>("GET", "/channels"),

  myPreferences: () => request<ListEnvelope<Preference>>("GET", "/preferences/me"),
  updatePreference: (channelId: string, data: Partial<Preference>) =>
    request<Preference>("PUT", `/preferences/me/${channelId}`, data),
};
