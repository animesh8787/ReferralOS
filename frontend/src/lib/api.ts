export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function csrf(): string {
  const m = document.cookie.match(/(?:^|; )csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = opts.method ?? (opts.body === undefined ? "GET" : "POST");
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(method === "GET" ? {} : { "X-CSRF-Token": csrf() }) },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    const msg = typeof d.detail === "string" ? d.detail : Array.isArray(d.detail) ? d.detail.map((x: { msg: string }) => x.msg).join("; ") : res.statusText;
    throw new ApiError(res.status, msg);
  }
  return res.json();
}

export async function upload<T = unknown>(path: string, file: File): Promise<T> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`/api${path}`, { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": csrf() }, body: fd });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new ApiError(res.status, typeof d.detail === "string" ? d.detail : res.statusText);
  }
  return res.json();
}

export type Me = { id: string; email: string; display_name: string; role: string; email_verified: boolean };
