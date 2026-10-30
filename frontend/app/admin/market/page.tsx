"use client";

import { useEffect, useState } from "react";
import { apiFetch, apiMutate, asItems } from "../../lib/admin";
import { Empty, ErrorBox, Feedback, Loading, PageHeader, Panel, TableWrap, tableClass, tdClass, thClass } from "../components/ui";

type Row = Record<string, unknown>;
const str = (v: unknown) => (v === null || v === undefined ? "—" : String(v));

function Rows({ rows, cols }: { rows: Row[]; cols: [string, string][] }) {
  if (rows.length === 0) return <Empty />;
  return (
    <TableWrap><table className={tableClass}>
      <thead><tr>{cols.map(([h]) => <th key={h} className={thClass}>{h}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={str(r.symbol ?? r.id ?? i)}>
            {cols.map(([, k]) => <td key={k} className={tdClass}>{str(r[k])}</td>)}
          </tr>
        ))}
      </tbody>
    </table></TableWrap>
  );
}

export default function MarketPage() {
  const [overview, setOverview] = useState<Row[]>([]);
  const [gainers, setGainers] = useState<Row[]>([]);
  const [losers, setLosers] = useState<Row[]>([]);
  const [watchlist, setWatchlist] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([
      apiFetch("/api/market/overview").then((d) => asItems<Row>(d).items).catch(() => []),
      apiFetch("/api/market/gainers").then((d) => {
        const r = d as { gainers?: Row[] };
        return r.gainers ?? asItems<Row>(d).items;
      }).catch(() => []),
      apiFetch("/api/market/losers").then((d) => {
        const r = d as { losers?: Row[] };
        return r.losers ?? asItems<Row>(d).items;
      }).catch(() => []),
      apiFetch("/api/market/watchlist").then((d) => asItems<Row>(d).items).catch(() => []),
    ])
      .then(([o, g, l, w]) => { setOverview(o); setGainers(g); setLosers(l); setWatchlist(w); })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load market data."))
      .finally(() => setLoading(false));
  }, []);

  async function collect() {
    setBusy(true);
    try {
      const data = await apiMutate<Record<string, unknown>>("/api/market/collect", "POST");
      const msg = data.message ?? data.detail ?? data.status;
      setFeedback(typeof msg === "string" ? msg : "Collection request completed.");
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Collection failed.");
    } finally {
      setBusy(false);
    }
  }

  const cols: [string, string][] = [
    ["Symbol", "symbol"],
    ["Price", "price"],
    ["24h change %", "price_change_percent_24h"],
    ["24h quote volume", "quote_volume_24h"],
  ];

  return (
    <div>
      <PageHeader title="Market Intelligence" description="Spot market snapshots, gainers, losers and watchlist." actions={<button className="btn btn-primary" disabled={busy} onClick={collect}>{busy ? "Collecting…" : "Run collection"}</button>} />
      <Feedback message={feedback} />
      {loading ? <Loading /> : error ? <ErrorBox message={error} /> : (
        <div className="space-y-4">
          <Panel><h2 className="mb-2 font-semibold">Overview</h2><Rows rows={overview} cols={cols} /></Panel>
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel><h2 className="mb-2 font-semibold">Top gainers</h2><Rows rows={gainers} cols={cols} /></Panel>
            <Panel><h2 className="mb-2 font-semibold">Top losers</h2><Rows rows={losers} cols={cols} /></Panel>
          </div>
          <Panel><h2 className="mb-2 font-semibold">Watchlist</h2><Rows rows={watchlist} cols={cols} /></Panel>
        </div>
      )}
    </div>
  );
}
