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

type TaskLike = { task_id?: string; status?: string; task_status?: string; result?: unknown; error?: string | null };

/** Background work never blocks the UI: if the API answered "queued/running", poll the task until it finishes (up to ~2 minutes). */
export async function settle<T extends TaskLike>(r: T, onTick?: (progress: number) => void): Promise<T> {
  const st = r.task_status ?? r.status;
  if (!r.task_id || !["queued", "running"].includes(st ?? "")) return r;
  for (let i = 0; i < 120; i++) {
    await new Promise((res) => setTimeout(res, i < 5 ? 500 : 1000));
    const t = await api<{ status: string; progress: number; result: unknown; error: string | null }>(`/tasks/${r.task_id}`);
    onTick?.(t.progress);
    if (t.status === "done" || t.status === "failed") return { ...r, task_status: t.status, result: t.result, error: t.error };
  }
  return r;
}

export type Me = { id: string; email: string; display_name: string; role: string; email_verified: boolean };
