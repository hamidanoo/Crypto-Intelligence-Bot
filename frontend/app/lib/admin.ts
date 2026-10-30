"use client";

import { useCallback, useEffect, useState } from "react";

export type Me = {
  id: number | string;
  username: string;
  email?: string | null;
  role?: string | null;
  permissions?: string[];
  is_superuser?: boolean;
  is_active?: boolean;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const part = document.cookie
    .split(";")
    .map((c) => c.trim())
    .find((c) => c.startsWith("admin_csrf="));
  if (!part) return null;
  try {
    return decodeURIComponent(part.slice("admin_csrf=".length));
  } catch {
    return part.slice("admin_csrf=".length);
  }
}

function errorMessage(data: unknown, status: number): string {
  if (data && typeof data === "object") {
    const d = data as Record<string, unknown>;
    const detail = d.detail ?? d.message ?? d.error;
    if (typeof detail === "string" && detail) return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      if (typeof first === "string") return first;
      if (first && typeof first === "object") {
        const m = (first as Record<string, unknown>).msg;
        if (typeof m === "string") return m;
      }
    }
  }
  return `Request failed (${status})`;
}

export async function apiFetch<T>(
  path: string,
  options?: { method?: string; body?: unknown; csrf?: boolean | string }
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  let csrf: string | null = null;
  if (options?.csrf === true) csrf = getCsrfToken();
  else if (typeof options?.csrf === "string") csrf = options.csrf;
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const res = await fetch(path, {
    method: options?.method ?? "GET",
    credentials: "include",
    headers,
    body: options?.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  let data: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    if (res.status === 401) throw new ApiError(401, "Not signed in or session expired.");
    if (res.status === 403)
      throw new ApiError(403, "You do not have permission for this action.");
    throw new ApiError(res.status, errorMessage(data, res.status));
  }
  return data as T;
}

/** POST/PUT/PATCH/DELETE with the CSRF token read from the admin_csrf cookie. */
export function apiMutate<T>(path: string, method: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, { method, body, csrf: true });
}

export function hasPermission(me: Me | null, perm: string): boolean {
  if (!me) return false;
  if (me.is_superuser) return true;
  return (me.permissions ?? []).includes(perm);
}

export function useMe() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<number | null>(null);
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<Me>("/api/auth/me");
      setMe(data);
      setStatus(200);
    } catch (e) {
      setMe(null);
      setStatus(e instanceof ApiError ? e.status : 0);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  return { me, loading, status, refresh };
}

export type PageResult<T> = { items: T[]; total: number; page: number; page_size: number };

/** Tolerate both paginated {items,total,...} and bare-array responses. */
export function asItems<T>(data: unknown): PageResult<T> {
  if (Array.isArray(data)) {
    return { items: data as T[], total: data.length, page: 1, page_size: data.length || 20 };
  }
  if (data && typeof data === "object") {
    const d = data as Record<string, unknown>;
    const items = Array.isArray(d.items) ? (d.items as T[]) : [];
    return {
      items,
      total: typeof d.total === "number" ? d.total : items.length,
      page: typeof d.page === "number" ? d.page : 1,
      page_size: typeof d.page_size === "number" ? d.page_size : 20,
    };
  }
  return { items: [], total: 0, page: 1, page_size: 20 };
}

export function fmt(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString();
}

export function short(value: string | null | undefined, max = 80): string {
  if (!value) return "—";
  return value.length > max ? `${value.slice(0, max)}…` : value;
}
