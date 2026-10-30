"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { apiFetch } from "../lib/admin";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const expired = params.get("expired") === "1";
  const next = params.get("next") || "/admin";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await apiFetch("/api/auth/login", {
        method: "POST",
        body: { username, password },
        csrf: true,
      });
      router.replace(next.startsWith("/") ? next : "/admin");
    } catch (err) {
      const status = (err as { status?: number }).status;
      if (status === 401) setError("Invalid username or password");
      else setError(err instanceof Error ? err.message : "Login failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-md p-8">
      <h1 className="text-2xl font-bold">Admin login</h1>
      {expired && (
        <p className="mt-3 text-sm text-amber-400">Session expired, please log in again.</p>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-400">
          {error}
        </p>
      )}
      <form onSubmit={submit} className="panel mt-4 space-y-3">
        <label className="block text-sm">
          <span className="text-slate-400">Username</span>
          <input className="field mt-1" value={username} onChange={(e) => setUsername(e.target.value)} required autoComplete="username" />
        </label>
        <label className="block text-sm">
          <span className="text-slate-400">Password</span>
          <input className="field mt-1" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
        </label>
        <button className="btn btn-primary" disabled={busy} type="submit">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="mt-4 text-sm">
        <Link href="/forgot-password" className="text-sky-400 underline">
          Forgot password?
        </Link>
      </p>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<main className="p-8 text-sm text-slate-400">Loading…</main>}>
      <LoginForm />
    </Suspense>
  );
}
