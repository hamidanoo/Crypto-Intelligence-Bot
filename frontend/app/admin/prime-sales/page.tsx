"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiMutate, asItems, fmt } from "../../lib/admin";
import { Empty, ErrorBox, Feedback, Loading, PageHeader, Pagination, Panel, TableWrap, tableClass, tdClass, thClass } from "../components/ui";

type Item = Record<string, unknown>;
const str = (v: unknown) => (v === null || v === undefined ? "—" : String(v));

export default function PrimeSalesPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pageSize = 20;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/prime-sales?page=${page}&page_size=${pageSize}`);
      const r = asItems<Item>(data);
      setItems(r.items);
      setTotal(r.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load Prime Sales.");
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => { void load(); }, [load]);

  async function collect() {
    setBusy(true);
    try {
      const data = await apiMutate<Record<string, unknown>>("/api/prime-sales/collect", "POST");
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
      <PageHeader title="Prime Sales" description="Prime Sale events detected from announcements." actions={<button className="btn btn-primary" disabled={busy} onClick={collect}>{busy ? "Collecting…" : "Run collection"}</button>} />
      <Feedback message={feedback} />
      {loading ? <Loading /> : error ? <ErrorBox message={error} /> : items.length === 0 ? <Empty /> : (
        <>
          <Panel><TableWrap><table className={tableClass}>
            <thead><tr><th className={thClass}>Token</th><th className={thClass}>Status</th><th className={thClass}>Created</th></tr></thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={str(it.id ?? i)}>
                  <td className={tdClass}>{it.official_url ? <a className="text-sky-400 underline" href={str(it.official_url)} target="_blank" rel="noreferrer">{str(it.token_name ?? it.name)}</a> : str(it.token_name ?? it.name)}</td>
                  <td className={tdClass}>{str(it.status)}</td>
                  <td className={tdClass}>{fmt(it.created_at as string | null)}</td>
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
