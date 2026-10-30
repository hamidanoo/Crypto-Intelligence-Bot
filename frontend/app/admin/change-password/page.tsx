"use client";

import { useState } from "react";
import { apiMutate } from "../../lib/admin";
import { PageHeader, Panel } from "../components/ui";

export default function ChangePasswordPage() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== confirm) {
      setMessage("New passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await apiMutate("/api/auth/change-password", "POST", {
        current_password: current,
        new_password: next,
      });
      setMessage("Password changed successfully.");
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Password change failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader title="Change password" description="Update your own admin password." />
      {message && <p className="mb-3 text-sm text-slate-300">{message}</p>}
      <Panel className="max-w-md">
        <form onSubmit={submit} className="space-y-3">
          <label className="block text-sm">
            <span className="text-slate-400">Current password</span>
            <input className="field mt-1" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required autoComplete="current-password" />
          </label>
          <label className="block text-sm">
            <span className="text-slate-400">New password</span>
            <input className="field mt-1" type="password" value={next} onChange={(e) => setNext(e.target.value)} required autoComplete="new-password" />
          </label>
          <label className="block text-sm">
            <span className="text-slate-400">Confirm new password</span>
            <input className="field mt-1" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required autoComplete="new-password" />
          </label>
          <button className="btn btn-primary" disabled={busy} type="submit">
            {busy ? "Saving…" : "Change password"}
          </button>
        </form>
      </Panel>
    </div>
  );
}
