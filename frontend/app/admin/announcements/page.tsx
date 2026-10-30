"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiMutate, asItems, fmt } from "../../lib/admin";
import { Empty, ErrorBox, Feedback, Loading, PageHeader, Pagination, Panel, TableWrap, tableClass, tdClass, thClass } from "../components/ui";

type Item = {
  id: number;
  title?: string;
  category?: string;
  source_id?: string | number | null;
  published_at?: string | null;
  canonical_url?: string;
};

export default function AnnouncementsPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pageSize = 20;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (category) q.set("category", category);
      if (search) q.set("search", search);
      const data = await apiFetch(`/api/announcements?${q.toString()}`);
      const r = asItems<Item>(data);
      setItems(r.items);
      setTotal(r.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load announcements.");
    } finally {
      setLoading(false);
    }
  }, [page, category, search]);

  useEffect(() => {
    void load();
  }, [load]);

  async function collect() {
    setBusy(true);
    setFeedback(null);
    try {
      const data = await apiMutate<Record<string, unknown>>("/api/announcements/collect", "POST");
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
      <PageHeader
        title="Announcements"
        description="Binance announcements collected by the monitor."
        actions={
          <button className="btn btn-primary" disabled={busy} onClick={collect}>
            {busy ? "Collecting…" : "Run collection"}
          </button>
        }
      />
      <Feedback message={feedback} />
      <Panel className="mb-4">
        <div className="flex flex-wrap gap-2">
          <input className="field !w-64" placeholder="Filter by category" value={category} onChange={(e) => { setPage(1); setCategory(e.target.value); }} />
          <input className="field !w-64" placeholder="Search" value={search} onChange={(e) => { setPage(1); setSearch(e.target.value); }} />
          <button className="btn" onClick={() => void load()}>Apply</button>
        </div>
      </Panel>
      {loading ? <Loading /> : error ? <ErrorBox message={error} /> : items.length === 0 ? <Empty /> : (
        <>
          <Panel><TableWrap><table className={tableClass}>
            <thead><tr><th className={thClass}>Title</th><th className={thClass}>Category</th><th className={thClass}>Published</th></tr></thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id}>
                  <td className={tdClass}>{it.canonical_url ? <a className="text-sky-400 underline" href={it.canonical_url} target="_blank" rel="noreferrer">{it.title ?? `Announcement ${it.id}`}</a> : (it.title ?? `Announcement ${it.id}`)}</td>
                  <td className={tdClass}>{it.category ?? "—"}</td>
                  <td className={tdClass}>{fmt(it.published_at)}</td>
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
