// API client — thin typed wrapper over the backend's /api/v1 contract.
const BASE = "/api/v1";

let token: string | null = localStorage.getItem("secureupi.token");

export function setToken(t: string | null) {
  token = t;
  if (t) localStorage.setItem("secureupi.token", t);
  else localStorage.removeItem("secureupi.token");
}
export function getToken() {
  return token;
}

export async function api<T>(
  method: string,
  path: string,
  body?: unknown
): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = { error: res.statusText };
    }
    throw new ApiHttpError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export class ApiHttpError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(`API ${status}: ${JSON.stringify(detail)}`);
    this.status = status;
    this.detail = detail;
  }
}
