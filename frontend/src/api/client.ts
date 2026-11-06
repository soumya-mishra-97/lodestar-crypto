import type { Problem } from "./types";

/**
 * Fetch wrapper.
 * - Access token lives in memory only (never localStorage), so XSS can't read a long-lived credential.
 * - The refresh token is an HttpOnly cookie scoped to /api/v1/auth; on a 401 we refresh once
 *   (single-flight, so parallel requests share one refresh) and replay the request.
 * - In local (single-user) mode the API needs no token at all.
 */
export const BASE = "/api/v1";

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<(authed: boolean) => void>();

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem: Problem | null,
  ) {
    super(problem?.detail ?? `Request failed (${status})`);
  }
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  listeners.forEach((fn) => fn(token !== null));
}

export function onAuthChange(fn: (authed: boolean) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function authHeaders(): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export async function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const res = await fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "same-origin" });
      if (!res.ok) {
        setAccessToken(null);
        return false;
      }
      setAccessToken(((await res.json()) as { access_token: string }).access_token);
      return true;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

async function request(path: string, init: RequestInit, retry: boolean): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  for (const [k, v] of Object.entries(authHeaders())) headers.set(k, v);
  const res = await fetch(`${BASE}${path}`, { ...init, headers, credentials: "same-origin" });
  if (res.status === 401 && retry && !path.startsWith("/auth/") && (await refreshSession())) {
    return request(path, init, false);
  }
  if (!res.ok) {
    const problem = (await res.json().catch(() => null)) as Problem | null;
    throw new ApiError(res.status, problem);
  }
  return res;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await request(path, init, true);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Download an authenticated file (report exports) via a temporary object URL. */
export async function download(path: string): Promise<void> {
  const res = await request(path, {}, true);
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "lodestar-export";
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });
