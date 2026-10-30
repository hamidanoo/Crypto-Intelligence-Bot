"use client";

import { useEffect, useState } from "react";
import { apiFetch, apiMutate, asItems } from "../../lib/admin";
import { Empty, ErrorBox, Feedback, Loading, PageHeader, Panel, TableWrap, tableClass, tdClass, thClass } from "../components/ui";

type Summary = { availability?: string; symbols?: number; highest_funding?: { symbol: string; funding_rate?: string | null } | null; lowest_funding?: { symbol: string; funding_rate?: string | null } | null; last_collection_status?: string | null };
type Row = Record<string, unknown>;
const str = (v: unknown) => (v === null || v === undefined ? "—" : String(v));

export default function FuturesPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [funding, setFunding] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([
      apiFetch<Summary>("/api/futures/summary").catch(() => null),
      apiFetch("/api/futures/funding").then((d) => asItems<Row>(d).items).catch(() => []),
    ])
      .then(([s, f]) => { setSummary(s); setFunding(f); })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load futures data."))
      .finally(() => setLoading(false));
  }, []);

  async function collect() {
    setBusy(true);
    try {
      const data = await apiMutate<Record<string, unknown>>("/api/futures/collect", "POST");
      const msg = data.message ?? data.detail ?? data.status;
      setFeedback(typeof msg === "string" ? msg : "Collection request completed.");
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Collection failed.");
    } finally {
      setBusy(false);
    }
  }

  const unavailable = summary && summary.availability && summary.availability.toLowerCase() !== "available";

  return (
    <div>
      <PageHeader title="Futures Intelligence" description="Funding rates and futures market summary." actions={<button className="btn btn-primary" disabled={busy} onClick={collect}>{busy ? "Collecting…" : "Run collection"}</button>} />
      <Feedback message={feedback} />
      {unavailable && (
        <p className="panel mb-4 border-amber-500/50 p-3 text-sm text-amber-400">
          Futures data is currently unavailable ({summary?.availability}). Spot data is unaffected.
        </p>
      )}
      {loading ? <Loading /> : error ? <ErrorBox message={error} /> : (
        <>
          <Panel className="mb-4">
            {summary ? (
              <dl className="space-y-1 text-sm">
                <div><dt className="inline text-slate-400">Availability: </dt><dd className="inline">{summary.availability ?? "—"}</dd></div>
                <div><dt className="inline text-slate-400">Symbols: </dt><dd className="inline">{summary.symbols ?? "—"}</dd></div>
                <div><dt className="inline text-slate-400">Highest funding: </dt><dd className="inline">{summary.highest_funding ? `${summary.highest_funding.symbol}: ${summary.highest_funding.funding_rate ?? "—"}` : "—"}</dd></div>
                <div><dt className="inline text-slate-400">Lowest funding: </dt><dd className="inline">{summary.lowest_funding ? `${summary.lowest_funding.symbol}: ${summary.lowest_funding.funding_rate ?? "—"}` : "—"}</dd></div>
                <div><dt className="inline text-slate-400">Last collection: </dt><dd className="inline">{summary.last_collection_status ?? "—"}</dd></div>
              </dl>
            ) : <Empty message="Futures summary unavailable." />}
          </Panel>
          <Panel>
            <h2 className="mb-2 font-semibold">Funding rates</h2>
            {funding.length === 0 ? <Empty /> : (
              <TableWrap><table className={tableClass}>
                <thead><tr><th className={thClass}>Symbol</th><th className={thClass}>Funding rate</th><th className={thClass}>Open interest</th><th className={thClass}>Mark price</th></tr></thead>
                <tbody>
                  {funding.map((r, i) => (
                    <tr key={str(r.symbol ?? r.id ?? i)}>
                      <td className={tdClass}>{str(r.symbol)}</td>
                      <td className={tdClass}>{str(r.funding_rate ?? r.last_funding_rate)}</td>
                      <td className={tdClass}>{str(r.open_interest)}</td>
                      <td className={tdClass}>{str(r.mark_price ?? r.price)}</td>
                    </tr>
                  ))}
                </tbody>
              </table></TableWrap>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
