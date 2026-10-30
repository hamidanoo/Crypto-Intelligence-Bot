"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiMutate, asItems, fmt } from "../../lib/admin";
import { Empty, ErrorBox, Feedback, Loading, PageHeader, Panel, TableWrap, tableClass, tdClass, thClass } from "../components/ui";

type Item = {
  id: number | string;
  provider?: string;
  base_url?: string | null;
  enabled?: boolean;
  api_key_masked?: string | null;
  last_success_at?: string | null;
  last_error?: string | null;
  last_checked_at?: string | null;
};

export default function IntegrationsPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [provider, setProvider] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [editing, setEditing] = useState<Item | null>(null);
  const [editBaseUrl, setEditBaseUrl] = useState("");
  const [editEnabled, setEditEnabled] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch("/api/admin/integrations");
      setItems(asItems<Item>(data).items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load integrations.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await apiMutate("/api/admin/integrations", "POST", {
        provider,
        base_url: baseUrl || undefined,
        api_key: apiKey || undefined,
        api_secret: apiSecret || undefined,
        enabled,
      });
      setFeedback("Integration added.");
      setProvider(""); setBaseUrl(""); setApiKey(""); setApiSecret(""); setEnabled(true);
      void load();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Add failed.");
    } finally {
      setBusy(false);
    }
  }

  async function saveEdit() {
    if (!editing) return;
    setBusy(true);
    try {
      await apiMutate(`/api/admin/integrations/${editing.id}`, "PATCH", {
        base_url: editBaseUrl || undefined,
        enabled: editEnabled,
      });
      setFeedback("Integration updated.");
      setEditing(null);
      void load();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Update failed.");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(it: Item) {
    if (!it.enabled && !window.confirm(`Disable integration ${it.provider}?`)) return;
    if (it.enabled && !window.confirm(`Disable integration ${it.provider}?`)) return;
    try {
      await apiMutate(`/api/admin/integrations/${it.id}`, "PATCH", { enabled: !it.enabled });
      setFeedback(`Integration ${!it.enabled ? "enabled" : "disabled"}.`);
      void load();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Toggle failed.");
    }
  }

  async function test(it: Item) {
    try {
      const d = await apiMutate<Record<string, unknown>>(`/api/admin/integrations/${it.id}/test-connection`, "POST");
      const msg = d.detail ?? d.status ?? d.message;
      setFeedback(typeof msg === "string" ? `Test (${it.provider}): ${msg}` : `Test (${it.provider}) completed with status ${d.status ?? "unknown"}.`);
      void load();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Test failed.");
    }
  }

  return (
    <div>
      <PageHeader title="API Integrations" description="External providers. Only masked keys are ever shown; full keys are never rendered." />
      <Feedback message={feedback} />
      {loading ? <Loading /> : error ? <ErrorBox message={error} /> : items.length === 0 ? <Empty /> : (
        <Panel className="mb-4"><TableWrap><table className={tableClass}>
          <thead><tr><th className={thClass}>Provider</th><th className={thClass}>Base URL</th><th className={thClass}>Key (masked)</th><th className={thClass}>Enabled</th><th className={thClass}>Last success</th><th className={thClass}>Last error</th><th className={thClass}>Actions</th></tr></thead>
          <tbody>
            {items.map((it) => (
              <tr key={String(it.id)}>
                <td className={tdClass}>{it.provider ?? "—"}</td>
                <td className={tdClass}>{it.base_url ?? "—"}</td>
                <td className={tdClass}>{it.api_key_masked ?? "—"}</td>
                <td className={tdClass}>{it.enabled ? "Yes" : "No"}</td>
                <td className={tdClass}>{fmt(it.last_success_at)}</td>
                <td className={tdClass}>{it.last_error ?? "—"}</td>
                <td className={tdClass}>
                  <div className="flex flex-wrap gap-2">
                    <button className="btn" onClick={() => { setEditing(it); setEditBaseUrl(it.base_url ?? ""); setEditEnabled(it.enabled ?? true); }}>Edit</button>
                    <button className="btn" onClick={() => toggle(it)}>{it.enabled ? "Disable" : "Enable"}</button>
                    <button className="btn" onClick={() => test(it)}>Test connection</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table></TableWrap></Panel>
      )}
      {editing && (
        <Panel className="mb-4">
          <h2 className="font-semibold">Edit {editing.provider}</h2>
          <div className="mt-3 space-y-3">
            <label className="block text-sm"><span className="text-slate-400">Base URL</span><input className="field mt-1" value={editBaseUrl} onChange={(e) => setEditBaseUrl(e.target.value)} /></label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={editEnabled} onChange={(e) => setEditEnabled(e.target.checked)} /> Enabled</label>
            <div className="flex gap-2"><button className="btn btn-primary" disabled={busy} onClick={saveEdit}>Save</button><button className="btn" onClick={() => setEditing(null)}>Cancel</button></div>
          </div>
        </Panel>
      )}
      <Panel>
        <h2 className="font-semibold">Add integration</h2>
        <form onSubmit={add} className="mt-3 space-y-3">
          <label className="block text-sm"><span className="text-slate-400">Provider</span><input className="field mt-1" value={provider} onChange={(e) => setProvider(e.target.value)} required /></label>
          <label className="block text-sm"><span className="text-slate-400">Base URL</span><input className="field mt-1" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} /></label>
          <label className="block text-sm"><span className="text-slate-400">API key (optional, never shown again)</span><input className="field mt-1" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} autoComplete="off" /></label>
          <label className="block text-sm"><span className="text-slate-400">API secret (optional, never shown again)</span><input className="field mt-1" type="password" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)} autoComplete="off" /></label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled</label>
          <button className="btn btn-primary" disabled={busy} type="submit">Add integration</button>
        </form>
      </Panel>
    </div>
  );
}
