"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiMutate, asItems, fmt } from "../../lib/admin";
import { Empty, ErrorBox, Feedback, Loading, PageHeader, Pagination, Panel, TableWrap, tableClass, tdClass, thClass } from "../components/ui";

type Comp = { id: number; competition_name?: string; name?: string };
type Interval = Record<string, unknown>;
type Summary = { competition_id?: number; competition_name?: string; status?: string; official_eligible_volume?: string | null; per_pair?: { trading_pair: string; cumulative_public_base_volume?: string | null; cumulative_public_quote_volume?: string | null; interval_count?: number }[]; last_collection_at?: string | null; last_collection_status?: string | null } | null;
const str = (v: unknown) => (v === null || v === undefined ? "—" : String(v));

export default function VolumePage() {
  const [comps, setComps] = useState<Comp[]>([]);
  const [compId, setCompId] = useState<string>("");
  const [pair, setPair] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [items, setItems] = useState<Interval[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [summary, setSummary] = useState<Summary>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pageSize = 20;

  useEffect(() => {
    apiFetch("/api/competitions?page_size=100")
      .then((d) => {
        const r = asItems<Comp>(d);
        setComps(r.items);
        if (r.items.length > 0) setCompId(String(r.items[0].id));
      })
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (compId) q.set("competition_id", compId);
      if (pair) q.set("trading_pair", pair);
      if (statusFilter) q.set("data_status", statusFilter);
      const data = await apiFetch(`/api/competition-volume?${q.toString()}`);
      const r = asItems<Interval>(data);
      setItems(r.items);
      setTotal(r.total);
      if (compId) {
        const s = await apiFetch<Summary>(`/api/competition-volume/${compId}/summary`).catch(() => null);
        setSummary(s);
      } else setSummary(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load volume intervals.");
    } finally {
      setLoading(false);
    }
  }, [page, compId, pair, statusFilter]);

  useEffect(() => { void load(); }, [load]);

  async function collect() {
    setBusy(true);
    try {
      const data = await apiMutate<Record<string, unknown>>("/api/competition-volume/collect", "POST");
      const msg = data.message ?? data.detail ?? data.status;
      setFeedback(typeof msg === "string" ? msg : "Collection request completed.");
      void load();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Collection failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader title="Competition Volume" description="30-minute public volume intervals. Official eligible volume is shown only when the backend reports it; it is never derived from public volume here." actions={<button className="btn btn-primary" disabled={busy} onClick={collect}>{busy ? "Collecting…" : "Run collection"}</button>} />
      <Feedback message={feedback} />
      <Panel className="mb-4">
        <div className="flex flex-wrap gap-2">
          <select className="field !w-64" value={compId} onChange={(e) => { setPage(1); setCompId(e.target.value); }}>
            <option value="">All competitions</option>
            {comps.map((c) => <option key={c.id} value={c.id}>{c.competition_name ?? c.name ?? c.id}</option>)}
          </select>
          <input className="field !w-48" placeholder="Trading pair, e.g. BTCUSDT" value={pair} onChange={(e) => { setPage(1); setPair(e.target.value); }} />
          <input className="field !w-48" placeholder="Data status filter" value={statusFilter} onChange={(e) => { setPage(1); setStatusFilter(e.target.value); }} />
        </div>
      </Panel>
      {summary && (
        <Panel className="mb-4">
          <h2 className="font-semibold">Summary — {summary.competition_name ?? summary.competition_id ?? ""}</h2>
          <p className="mt-1 text-sm">Status: {summary.status ?? "—"}; official eligible volume: {summary.official_eligible_volume ?? "Unavailable"}; last collection: {fmt(summary.last_collection_at)} ({summary.last_collection_status ?? "—"})</p>
          {(summary.per_pair ?? []).map((p) => (
            <p key={p.trading_pair} className="mt-1 text-sm">{p.trading_pair}: cumulative public {p.cumulative_public_base_volume ?? "—"} / {p.cumulative_public_quote_volume ?? "—"} ({p.interval_count ?? 0} intervals)</p>
          ))}
        </Panel>
      )}
      {loading ? <Loading /> : error ? <ErrorBox message={error} /> : items.length === 0 ? <Empty message="No volume intervals found for the selected filters." /> : (
        <>
          <Panel><TableWrap><table className={tableClass}>
            <thead><tr><th className={thClass}>Pair</th><th className={thClass}>Interval start</th><th className={thClass}>Public base</th><th className={thClass}>Public quote</th><th className={thClass}>Official eligible</th><th className={thClass}>Status</th></tr></thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={str(it.id ?? i)}>
                  <td className={tdClass}>{str(it.trading_pair)}</td>
                  <td className={tdClass}>{fmt(it.interval_start as string | null)}</td>
                  <td className={tdClass}>{str(it.public_base_volume)}</td>
                  <td className={tdClass}>{str(it.public_quote_volume)}</td>
                  <td className={tdClass}>{str(it.official_eligible_volume)}</td>
                  <td className={tdClass}>{str(it.data_status)}</td>
                </tr>
              ))}
            </tbody>
          </table></TableWrap></Panel>
          <Pagination page={page} total={total} pageSize={pageSize} onPage={setPage} />
        </>
      )}
    </div>
  );
}
