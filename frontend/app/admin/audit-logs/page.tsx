"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, asItems, fmt } from "../../lib/admin";
import { Empty, ErrorBox, Loading, PageHeader, Pagination, Panel, TableWrap, tableClass, tdClass, thClass } from "../components/ui";

type Item = { id: number | string; admin_user_id?: number | string | null; actor?: string | null; action?: string; entity?: string | null; entity_id?: string | number | null; outcome?: string | null; correlation_id?: string | null; ip_address?: string | null; created_at?: string | null; details?: unknown };

export default function AuditLogsPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pageSize = 20;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (action) q.set("action", action);
      if (actor) q.set("actor", actor);
      if (dateFrom) q.set("date_from", dateFrom);
      if (dateTo) q.set("date_to", dateTo);
      const data = await apiFetch(`/api/admin/audit-logs?${q.toString()}`);
      const r = asItems<Item>(data);
      setItems(r.items);
      setTotal(r.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit logs.");
    } finally {
      setLoading(false);
    }
  }, [page, action, actor, dateFrom, dateTo]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div>
      <PageHeader title="Audit Logs" description="Admin actions recorded by the backend." />
      <Panel className="mb-4">
        <div className="flex flex-wrap gap-2">
          <input className="field !w-48" placeholder="Action filter" value={action} onChange={(e) => { setPage(1); setAction(e.target.value); }} />
          <input className="field !w-48" placeholder="Actor filter" value={actor} onChange={(e) => { setPage(1); setActor(e.target.value); }} />
          <input className="field !w-48" type="date" value={dateFrom} onChange={(e) => { setPage(1); setDateFrom(e.target.value); }} />
          <input className="field !w-48" type="date" value={dateTo} onChange={(e) => { setPage(1); setDateTo(e.target.value); }} />
        </div>
      </Panel>
      {loading ? <Loading /> : error ? <ErrorBox message={error} /> : items.length === 0 ? <Empty /> : (
        <>
          <Panel><TableWrap><table className={tableClass}>
            <thead><tr><th className={thClass}>When</th><th className={thClass}>Actor</th><th className={thClass}>Action</th><th className={thClass}>Entity</th><th className={thClass}>Outcome</th><th className={thClass}>IP</th></tr></thead>
            <tbody>
              {items.map((it) => (
                <tr key={String(it.id)}>
                  <td className={tdClass}>{fmt(it.created_at)}</td>
                  <td className={tdClass}>{it.actor ?? it.admin_user_id ?? "—"}</td>
                  <td className={tdClass}>{it.action ?? "—"}</td>
                  <td className={tdClass}>{it.entity ?? "—"} {it.entity_id ?? ""}</td>
                  <td className={tdClass}>{it.outcome ?? "—"}</td>
                  <td className={tdClass}>{it.ip_address ?? "—"}</td>
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
