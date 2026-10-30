"use client";

import { useEffect, useState } from "react";
import { apiFetch, apiMutate } from "../../lib/admin";
import { ErrorBox, Feedback, Loading, PageHeader, Panel } from "../components/ui";

type Config = {
  bot_configured?: boolean;
  bot_username?: string | null;
  group_chat_id?: string | null;
  group_title?: string | null;
  notifications_enabled?: boolean;
  categories?: Record<string, boolean>;
};

export default function TelegramPage() {
  const [cfg, setCfg] = useState<Config | null>(null);
  const [groupId, setGroupId] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [categories, setCategories] = useState<Record<string, boolean>>({});
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiFetch<Config>("/api/admin/telegram")
      .then((d) => {
        setCfg(d);
        setGroupId(d.group_chat_id ?? "");
        setEnabled(d.notifications_enabled ?? true);
        setCategories(d.categories ?? {});
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load Telegram settings."))
      .finally(() => setLoading(false));
  }, []);

  async function save() {
    setBusy(true);
    try {
      const d = await apiMutate<Config>("/api/admin/telegram", "PATCH", {
        group_chat_id: groupId || null,
        notifications_enabled: enabled,
        categories,
      });
      setCfg(d);
      setFeedback("Telegram settings saved.");
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    try {
      const d = await apiMutate<Record<string, unknown>>("/api/admin/telegram/test-message", "POST", {
        message: message || undefined,
      });
      const msg = d.message ?? d.detail ?? d.status;
      setFeedback(typeof msg === "string" ? msg : "Test message request completed.");
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Test message failed.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;

  return (
    <div>
      <PageHeader title="Telegram Management" description="Bot and group configuration. Test messages are only sent when you press the button." />
      <Feedback message={feedback} />
      <Panel className="mb-4">
        <p className="text-sm">Bot configured: {cfg?.bot_configured ? "Yes" : "No"}; bot username: {cfg?.bot_username ?? "—"}; group: {cfg?.group_title ?? cfg?.group_chat_id ?? "—"}</p>
        <div className="mt-3 space-y-3">
          <label className="block text-sm">
            <span className="text-slate-400">Group chat ID</span>
            <input className="field mt-1" value={groupId} onChange={(e) => setGroupId(e.target.value)} placeholder="e.g. -1001234567890" />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Notifications enabled
          </label>
          <div>
            <p className="text-sm text-slate-400">Categories</p>
            {Object.keys(categories).length === 0 ? (
              <p className="text-sm text-slate-400">No categories reported by the backend.</p>
            ) : (
              Object.entries(categories).map(([k, v]) => (
                <label key={k} className="mr-4 inline-flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={v} onChange={(e) => setCategories({ ...categories, [k]: e.target.checked })} />
                  {k}
                </label>
              ))
            )}
          </div>
          <button className="btn btn-primary" disabled={busy} onClick={save}>Save settings</button>
        </div>
      </Panel>
      <Panel>
        <h2 className="font-semibold">Send test message</h2>
        <p className="mt-1 text-sm text-slate-400">Only sent when you press the button below.</p>
        <input className="field mt-3" value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Optional test message" />
        <button className="btn btn-primary mt-3" disabled={busy} onClick={test}>Send test message</button>
      </Panel>
    </div>
  );
}
