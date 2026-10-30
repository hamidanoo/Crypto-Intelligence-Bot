"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiMutate, asItems, fmt } from "../../lib/admin";
import { Empty, ErrorBox, Feedback, Loading, PageHeader, Pagination, Panel, TableWrap, tableClass, tdClass, thClass } from "../components/ui";

type Settings = { global_enabled?: boolean; categories?: Record<string, boolean>; thresholds?: Record<string, unknown>; cooldown_minutes?: number };
type Hist = { id: number | string; entity_type?: string; entity_id?: string | number | null; notification_type?: string; status?: string; sent_at?: string | null };

export default function NotificationsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [globalEnabled, setGlobalEnabled] = useState(true);
  const [categories, setCategories] = useState<Record<string, boolean>>({});
  const [cooldown, setCooldown] = useState(0);
  const [history, setHistory] = useState<Hist[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pageSize = 20;

  const loadHist = useCallback(async () => {
    try {
      const data = await apiFetch(`/api/admin/notifications/history?page=${page}&page_size=${pageSize}`);
      const r = asItems<Hist>(data);
      setHistory(r.items);
      setTotal(r.total);
    } catch { /* history is secondary; settings error is shown instead */ }
  }, [page]);

  useEffect(() => {
    apiFetch<Settings>("/api/admin/notifications")
      .then((d) => {
        setSettings(d);
        setGlobalEnabled(d.global_enabled ?? true);
        setCategories(d.categories ?? {});
        setCooldown(d.cooldown_minutes ?? 0);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load notification settings."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { void loadHist(); }, [loadHist]);

  async function save() {
    setBusy(true);
    try {
      const d = await apiMutate<Settings>("/api/admin/notifications", "PATCH", {
        global_enabled: globalEnabled,
        categories,
        cooldown_minutes: cooldown,
      });
      setSettings(d);
      setFeedback("Notification settings saved.");
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;

  return (
    <div>
      <PageHeader title="Notification Settings" description="Global switch, per-category switches, cooldown, and delivery history." />
      <Feedback message={feedback} />
      <Panel className="mb-4">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={globalEnabled} onChange={(e) => setGlobalEnabled(e.target.checked)} /> Globally enabled</label>
        <div className="mt-3">
          <p className="text-sm text-slate-400">Categories</p>
          {Object.keys(categories).length === 0 ? <p className="text-sm text-slate-400">No categories reported by the backend.</p> : Object.entries(categories).map(([k, v]) => (
            <label key={k} className="mr-4 inline-flex items-center gap-2 text-sm">
              <input type="checkbox" checked={v} onChange={(e) => setCategories({ ...categories, [k]: e.target.checked })} /> {k}
            </label>
          ))}
        </div>
        <label className="mt-3 block text-sm">
          <span className="text-slate-400">Cooldown (minutes)</span>
          <input className="field mt-1 !w-48" type="number" value={cooldown} onChange={(e) => setCooldown(Number(e.target.value))} />
        </label>
        {settings?.thresholds && <p className="mt-3 text-sm text-slate-400">Thresholds: {JSON.stringify(settings.thresholds)}</p>}
        <button className="btn btn-primary mt-3" disabled={busy} onClick={save}>Save settings</button>
      </Panel>
      <Panel>
        <h2 className="mb-2 font-semibold">History</h2>
        {history.length === 0 ? <Empty /> : (
          <>
            <TableWrap><table className={tableClass}>
              <thead><tr><th className={thClass}>Entity</th><th className={thClass}>Type</th><th className={thClass}>Status</th><th className={thClass}>Sent at</th></tr></thead>
              <tbody>
                {history.map((h) => (
                  <tr key={String(h.id)}>
                    <td className={tdClass}>{h.entity_type ?? "—"} {h.entity_id ?? ""}</td>
                    <td className={tdClass}>{h.notification_type ?? "—"}</td>
                    <td className={tdClass}>{h.status ?? "—"}</td>
                    <td className={tdClass}>{fmt(h.sent_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table></TableWrap>
            <Pagination page={page} total={total} pageSize={pageSize} onPage={setPage} />
          </>
        )}
      </Panel>
    </div>
  );
}
