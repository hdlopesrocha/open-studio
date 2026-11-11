const API_BASE = import.meta.env.VITE_API_BASE || "/api";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export function encodePath(path: string): string {
  return path
    .split("/")
    .filter((part) => part.length > 0)
    .map(encodeURIComponent)
    .join("/");
}

export function fileUrl(path: string): string {
  return `${API_BASE}/files/raw/${encodePath(path)}`;
}

export function downloadUrl(path: string): string {
  return `${API_BASE}/files/download?path=${encodeURIComponent(path)}`;
}

export function artifactUrl(path: string): string {
  return fileUrl(path);
}

async function parseError(response: Response): Promise<ApiError> {
  let detail: unknown = null;
  let message = `${response.status} ${response.statusText}`;
  const text = await response.text().catch(() => "");
  if (text) {
    try {
      const body = JSON.parse(text);
      detail = body.detail ?? body;
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: any) => d.msg || String(d)).join("; ");
      else if (typeof body.error === "string") message = body.error;
      else if (body.error?.message) message = body.error.message;
      else message = text.slice(0, 500);
    } catch {
      message = text.slice(0, 500);
    }
  }
  return new ApiError(response.status, message, detail);
}

export async function request<T = any>(
  path: string,
  options: RequestInit & { raw?: boolean } = {},
): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (!(options.body instanceof FormData) && options.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...options,
    headers,
  });
  if (!response.ok) {
    const error = await parseError(response);
    if (response.status === 401) window.dispatchEvent(new CustomEvent("openstudio:unauthorized"));
    throw error;
  }
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") || "";
  if (options.raw || !type.includes("application/json")) {
    return (await response.blob()) as unknown as T;
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T = any>(path: string, options: RequestInit = {}) => request<T>(path, { ...options, method: "GET" }),
  post: <T = any>(path: string, body?: unknown, options: RequestInit = {}) =>
    request<T>(path, {
      ...options,
      method: "POST",
      body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
    }),
  put: <T = any>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T = any>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
  delete: <T = any>(path: string, body?: unknown) =>
    request<T>(path, { method: "DELETE", body: body === undefined ? undefined : JSON.stringify(body) }),
};

export function uploadFile(
  path: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<{ file: any; size: number }> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("path", path);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/files/upload`);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          resolve({ file: null, size: 0 });
        }
      } else {
        let message = `Upload failed (${xhr.status})`;
        try {
          message = JSON.parse(xhr.responseText).detail || message;
        } catch {}
        reject(new ApiError(xhr.status, message));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error while uploading"));
    xhr.send(form);
  });
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function formatDuration(seconds?: number | null): string {
  if (!seconds || seconds < 0) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

export function relativeTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const diff = Date.now() - date.getTime();
  const minutes = Math.round(diff / 60000);
  if (minutes < 0) {
    const ahead = Math.abs(minutes);
    if (ahead < 60) return `in ${ahead}m`;
    const aheadHours = Math.round(ahead / 60);
    if (aheadHours < 24) return `in ${aheadHours}h`;
    return `in ${Math.round(aheadHours / 24)}d`;
  }
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return date.toLocaleDateString();
}
