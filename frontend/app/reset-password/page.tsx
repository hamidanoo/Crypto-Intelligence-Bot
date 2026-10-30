"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { apiFetch } from "../lib/admin";

function ResetForm() {
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setMessage("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await apiFetch("/api/auth/reset-password", {
        method: "POST",
        body: { token, new_password: password },
        csrf: true,
      });
      setMessage("Password reset successfully. You can now log in.");
    } catch {
      setMessage("Reset failed. The link may be invalid or expired.");
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <main className="mx-auto max-w-md p-8">
        <h1 className="text-2xl font-bold">Reset password</h1>
        <p className="mt-3 text-sm text-red-400">No reset token was provided. Use the link sent to you.</p>
        <p className="mt-4 text-sm"><Link href="/login" className="text-sky-400 underline">Back to login</Link></p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-md p-8">
      <h1 className="text-2xl font-bold">Reset password</h1>
      {message && <p className="mt-3 text-sm text-slate-300">{message}</p>}
      <form onSubmit={submit} className="panel mt-4 space-y-3">
        <label className="block text-sm">
          <span className="text-slate-400">New password</span>
          <input className="field mt-1" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="new-password" />
        </label>
        <label className="block text-sm">
          <span className="text-slate-400">Confirm new password</span>
          <input className="field mt-1" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required autoComplete="new-password" />
        </label>
        <button className="btn btn-primary" disabled={busy} type="submit">
          {busy ? "Resetting…" : "Reset password"}
        </button>
      </form>
      <p className="mt-4 text-sm"><Link href="/login" className="text-sky-400 underline">Back to login</Link></p>
    </main>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<main className="p-8 text-sm text-slate-400">Loading…</main>}>
      <ResetForm />
    </Suspense>
  );
}
