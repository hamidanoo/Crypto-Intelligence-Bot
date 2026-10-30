"use client";

import Link from "next/link";
import { useState } from "react";
import { apiFetch } from "../lib/admin";

export default function ForgotPasswordPage() {
  const [value, setValue] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const data = await apiFetch<{ message?: string }>("/api/auth/forgot-password", {
        method: "POST",
        body: { username_or_email: value },
        csrf: true,
      });
      setMessage(data.message ?? "If an account exists, a reset link has been sent.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Request failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-md p-8">
      <h1 className="text-2xl font-bold">Forgot password</h1>
      <p className="mt-2 text-sm text-slate-400">
        Enter your username or email. If an account exists, you will receive reset instructions.
      </p>
      {message && <p className="mt-3 text-sm text-slate-300">{message}</p>}
      <form onSubmit={submit} className="panel mt-4 space-y-3">
        <label className="block text-sm">
          <span className="text-slate-400">Username or email</span>
          <input className="field mt-1" value={value} onChange={(e) => setValue(e.target.value)} required />
        </label>
        <button className="btn btn-primary" disabled={busy} type="submit">
          {busy ? "Sending…" : "Send reset link"}
        </button>
      </form>
      <p className="mt-4 text-sm">
        <Link href="/login" className="text-sky-400 underline">Back to login</Link>
      </p>
    </main>
  );
}
