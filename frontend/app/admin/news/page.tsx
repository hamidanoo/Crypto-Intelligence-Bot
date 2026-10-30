"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiMutate, asItems, fmt } from "../../lib/admin";
import { Empty, ErrorBox, Feedback, Loading, PageHeader, Pagination, Panel, TableWrap, tableClass, tdClass, thClass } from "../components/ui";

type Item = Record<string, unknown>;
const str = (v: unknown) => (v === null || v === undefined ? "—" : String(v));

export default function NewsPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState("");
  const [section, setSection] = useState<"all" | "listings" | "delistings">("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pageSize = 20;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const path = section === "all" ? "/api/news" : `/api/news/${section}`;
      const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (category) q.set("category", category);
      const data = await apiFetch(`${path}?${q.toString()}`);
      const r = asItems<Item>(data);
      setItems(r.items);
      setTotal(r.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load news.");
    } finally {
      setLoading(false);
    }
  }, [page, category, section]);

  useEffect(() => { void load(); }, [load]);

  async function collect() {
    setBusy(true);
    try {
      const data = await apiMutate<Record<string, unknown>>("/api/news/collect", "POST");
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
      <PageHeader title="News" description="News built from official announcements, with listings and delistings sections." actions={<button className="btn btn-primary" disabled={busy} onClick={collect}>{busy ? "Collecting…" : "Run collection"}</button>} />
      <Feedback message={feedback} />
      <Panel className="mb-4">
        <div className="flex flex-wrap gap-2">
          <select className="field !w-48" value={section} onChange={(e) => { setPage(1); setSection(e.target.value as typeof section); }}>
            <option value="all">All news</option>
            <option value="listings">Listings</option>
            <option value="delistings">Delistings</option>
          </select>
          <input className="field !w-64" placeholder="Filter by category" value={category} onChange={(e) => { setPage(1); setCategory(e.target.value); }} />
        </div>
      </Panel>
      {loading ? <Loading /> : error ? <ErrorBox message={error} /> : items.length === 0 ? <Empty /> : (
        <>
          <Panel><TableWrap><table className={tableClass}>
            <thead><tr><th className={thClass}>Headline</th><th className={thClass}>Category</th><th className={thClass}>Publisher</th><th className={thClass}>Published</th></tr></thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={str(it.id ?? i)}>
                  <td className={tdClass}>{it.original_url ? <a className="text-sky-400 underline" href={str(it.original_url)} target="_blank" rel="noreferrer">{str(it.headline ?? it.title)}</a> : str(it.headline ?? it.title)}</td>
                  <td className={tdClass}>{str(it.category)}</td>
                  <td className={tdClass}>{str(it.publisher ?? it.source)}</td>
                  <td className={tdClass}>{fmt(it.published_at as string | null)}</td>
                </tr>
              ))}
            </tbody>
          </table></TableWrap></Panel>
          <Pagination page={page} total={total} pageSize={pageSize} onPage={setPage} />
        </>
      )}
      <NewsSourcesPanel />
    </div>
  );
}

function NewsSourcesPanel() {
  const [sources, setSources] = useState<Item[]>([]);
  const [name, setName] = useState("");
  const [feedUrl, setFeedUrl] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch("/api/admin/news-sources");
      setSources(asItems<Item>(data).items);
    } catch { /* shown only if the section is usable */ }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiMutate("/api/admin/news-sources", "POST", { name, feed_url: feedUrl || undefined, enabled: true });
      setFeedback("News source added.");
      setName("");
      setFeedUrl("");
      void load();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Add failed.");
    }
  }

  async function toggleSrc(s: Item) {
    const enabled = s.enabled as boolean | undefined;
    if (enabled && !window.confirm(`Disable news source ${str(s.name)}?`)) return;
    try {
      await apiMutate(`/api/admin/news-sources/${s.id}`, "PATCH", { enabled: !enabled });
      setFeedback(`News source ${!enabled ? "enabled" : "disabled"}.`);
      void load();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Update failed.");
    }
  }

  async function testSrc(s: Item) {
    try {
      const d = await apiMutate<Record<string, unknown>>(`/api/admin/news-sources/${s.id}/test`, "POST");
      const msg = d.detail ?? d.status ?? d.message;
      setFeedback(typeof msg === "string" ? `Test (${str(s.name)}): ${msg}` : `Test (${str(s.name)}) ok: ${d.ok ? "yes" : "no"}.`);
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Test failed.");
    }
  }

  return (
    <Panel className="mt-4">
      <h2 className="font-semibold">News sources</h2>
      <Feedback message={feedback} />
      {sources.length === 0 ? (
        <p className="mt-2 text-sm text-slate-400">No news sources configured, or the endpoint is unavailable.</p>
      ) : (
        <TableWrap><table className={tableClass}>
          <thead><tr><th className={thClass}>Name</th><th className={thClass}>Type</th><th className={thClass}>Feed URL</th><th className={thClass}>Enabled</th><th className={thClass}>Last error</th><th className={thClass}>Actions</th></tr></thead>
          <tbody>
            {sources.map((s, i) => (
              <tr key={str(s.id ?? i)}>
                <td className={tdClass}>{str(s.name)}</td>
                <td className={tdClass}>{str(s.source_type)}</td>
                <td className={tdClass}>{str(s.feed_url)}</td>
                <td className={tdClass}>{(s.enabled as boolean | undefined) ? "Yes" : "No"}</td>
                <td className={tdClass}>{str(s.last_error)}</td>
                <td className={tdClass}>
                  <div className="flex flex-wrap gap-2">
                    <button className="btn" onClick={() => toggleSrc(s)}>{(s.enabled as boolean | undefined) ? "Disable" : "Enable"}</button>
                    <button className="btn" onClick={() => testSrc(s)}>Test</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table></TableWrap>
      )}
      <form onSubmit={add} className="mt-3 flex flex-wrap gap-2">
        <input className="field !w-48" placeholder="Source name" value={name} onChange={(e) => setName(e.target.value)} required />
        <input className="field !w-64" placeholder="Feed URL (optional)" value={feedUrl} onChange={(e) => setFeedUrl(e.target.value)} />
        <button className="btn btn-primary" type="submit">Add source</button>
      </form>
    </Panel>
  );
}
