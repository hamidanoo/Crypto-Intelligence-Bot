"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiMutate, asItems } from "../../lib/admin";
import { Empty, ErrorBox, Feedback, Loading, PageHeader, Panel, TableWrap, tableClass, tdClass, thClass } from "../components/ui";

type Item = { key: string; value?: unknown; description?: string | null };

export default function SettingsPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [editKey, setEditKey] = useState("");
  const [editValue, setEditValue] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch("/api/admin/system-settings");
      setItems(asItems<Item>(data).items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load system settings.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function save() {
    setBusy(true);
    try {
      // The API requires a JSON object value (Phase 9
      // audit): sending a plain string always failed
      // validation with 422. Accept JSON text, or a
      // bare string wrapped as {"value": ...}.
      let parsed: unknown;
      try {
        parsed = JSON.parse(editValue);
      } catch {
        parsed = { value: editValue };
      }
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        parsed = { value: parsed };
      }
      await apiMutate("/api/admin/system-settings", "PATCH", { key: editKey, value: parsed });
      setFeedback(`Setting ${editKey} updated.`);
      setEditKey("");
      setEditValue("");
      void load();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader title="Settings" description="System settings and account actions." />
      <Feedback message={feedback} />
      {loading ? <Loading /> : error ? <ErrorBox message={error} /> : items.length === 0 ? <Empty /> : (
        <Panel className="mb-4"><TableWrap><table className={tableClass}>
          <thead><tr><th className={thClass}>Key</th><th className={thClass}>Value</th><th className={thClass}>Description</th><th className={thClass}>Actions</th></tr></thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.key}>
                <td className={tdClass}>{it.key}</td>
                <td className={tdClass}>{it.value === null || it.value === undefined ? "—" : JSON.stringify(it.value)}</td>
                <td className={tdClass}>{it.description ?? "—"}</td>
                <td className={tdClass}><button className="btn" onClick={() => { setEditKey(it.key); setEditValue(it.value === null || it.value === undefined ? "" : JSON.stringify(it.value)); }}>Edit</button></td>
              </tr>
            ))}
          </tbody>
        </table></TableWrap></Panel>
      )}
      <Panel>
        <h2 className="font-semibold">Edit setting</h2>
        <div className="mt-3 space-y-3">
          <label className="block text-sm"><span className="text-slate-400">Key</span><input className="field mt-1" value={editKey} onChange={(e) => setEditKey(e.target.value)} placeholder="Setting key" /></label>
          <label className="block text-sm"><span className="text-slate-400">Value</span><input className="field mt-1" value={editValue} onChange={(e) => setEditValue(e.target.value)} placeholder="New value" /></label>
          <button className="btn btn-primary" disabled={busy || !editKey} onClick={save}>Save setting</button>
        </div>
        <p className="mt-4 text-sm">
          <Link href="/admin/change-password" className="text-sky-400 underline">Change your password →</Link>
        </p>
      </Panel>
    </div>
  );
}
