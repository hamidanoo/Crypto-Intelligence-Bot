"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Health = {
  status: string;
  service: string;
  environment: string;
  timestamp: string;
};

type AnnouncementItem = {
  id: number;
  title: string;
  category: string;
  category_confidence: string;
  published_at: string | null;
  canonical_url: string;
};

type AlphaItem = {
  id: number;
  token_name: string;
  token_symbol: string | null;
  announcement_url: string;
};

type AirdropItem = {
  id: number;
  campaign_name: string;
  status: string;
  official_url: string;
};

type PrimeItem = {
  id: number;
  token_name: string;
  status: string;
  official_url: string;
};

type CompetitionItem = {
  id: number;
  competition_name: string;
  competition_type: string;
  status: string;
  official_url: string;
};

type VolumeInterval = {
  id: number;
  trading_pair: string;
  base_asset: string | null;
  quote_asset: string | null;
  interval_start: string;
  interval_end: string;
  public_base_volume: string | null;
  public_quote_volume: string | null;
  estimated_eligible_volume: string | null;
  official_eligible_volume: string | null;
  calculation_method: string | null;
  data_status: string;
  recalculated: boolean;
  collected_at: string;
};

type VolumePairSummary = {
  trading_pair: string;
  base_asset: string | null;
  quote_asset: string | null;
  latest_interval: VolumeInterval | null;
  cumulative_public_base_volume: string | null;
  cumulative_public_quote_volume: string | null;
  cumulative_estimated_eligible_volume: string | null;
  interval_count: number;
};

type VolumeSummary = {
  competition_id: number;
  competition_name: string;
  status: string;
  official_eligible_volume: string | null;
  per_pair: VolumePairSummary[];
  last_collection_at: string | null;
  last_collection_status: string | null;
};

type MarketItem = {
  symbol: string;
  price: string | null;
  price_change_percent_24h: string | null;
  quote_volume_24h: string | null;
  collected_at: string | null;
  is_stale: boolean;
};

type NewsItem = {
  id: number;
  headline: string;
  summary: string;
  category: string;
  publisher: string;
  published_at: string | null;
  original_url: string;
};

type FuturesSummary = {
  availability: string;
  symbols: number;
  highest_funding: { symbol: string; funding_rate: string | null } | null;
  lowest_funding: { symbol: string; funding_rate: string | null } | null;
  last_collection_status: string | null;
};

type VolumePairOption = {
  pair: string;
  base_asset: string | null;
  quote_asset: string | null;
  tracking_enabled: boolean;
};

function formatUtc(value: string | null): string {
  if (!value) return "Unavailable";
  return `${value.replace("T", " ").slice(0, 16)} UTC`;
}

function formatPkt(value: string | null): string {
  if (!value) return "Unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  return (
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Karachi",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date) + " PKT"
  );
}

const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [announcements, setAnnouncements] = useState<AnnouncementItem[]>([]);
  const [alphaTokens, setAlphaTokens] = useState<AlphaItem[]>([]);
  const [activeAirdrops, setActiveAirdrops] = useState<AirdropItem[]>([]);
  const [activePrimeSales, setActivePrimeSales] = useState<PrimeItem[]>([]);
  const [activeCompetitions, setActiveCompetitions] = useState<CompetitionItem[]>([]);
  const [upcomingCompetitions, setUpcomingCompetitions] = useState<CompetitionItem[]>([]);
  const [volumeCompetitionId, setVolumeCompetitionId] = useState<number | null>(null);
  const [volumePairs, setVolumePairs] = useState<VolumePairOption[]>([]);
  const [volumePair, setVolumePair] = useState<string | null>(null);
  const [volumeSummary, setVolumeSummary] = useState<VolumeSummary | null>(null);
  const [volumeHistory, setVolumeHistory] = useState<VolumeInterval[]>([]);
  const [volumeError, setVolumeError] = useState<string | null>(null);
  const [marketItems, setMarketItems] = useState<MarketItem[]>([]);
  const [gainers, setGainers] = useState<MarketItem[]>([]);
  const [losers, setLosers] = useState<MarketItem[]>([]);
  const [watchlist, setWatchlist] = useState<MarketItem[]>([]);
  const [futuresSummary, setFuturesSummary] = useState<FuturesSummary | null>(null);
  const [newsItems, setNewsItems] = useState<NewsItem[]>([]);
  const [listings, setListings] = useState<NewsItem[]>([]);
  const [phase7Error, setPhase7Error] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${apiBase}/health`)
      .then((response) => {
        if (!response.ok) throw new Error(`Backend returned ${response.status}`);
        return response.json();
      })
      .then(setHealth)
      .catch((err: Error) => setError(err.message));
    fetch(`${apiBase}/announcements?page_size=5`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data) setAnnouncements(data.items ?? []);
      })
      .catch(() => {});
    fetch(`${apiBase}/alpha/tokens?page_size=5`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data) setAlphaTokens(data.items ?? []);
      })
      .catch(() => {});
    fetch(`${apiBase}/airdrops/active?page_size=5`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data) setActiveAirdrops(data.items ?? []);
      })
      .catch(() => {});
    fetch(`${apiBase}/competitions/active?page_size=5`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data) setActiveCompetitions(data.items ?? []);
      })
      .catch(() => {});
    fetch(`${apiBase}/competitions/upcoming?page_size=5`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data) setUpcomingCompetitions(data.items ?? []);
      })
      .catch(() => {});
    fetch(`${apiBase}/prime-sales/active?page_size=5`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data) setActivePrimeSales(data.items ?? []);
      })
      .catch(() => {});
  }, []);

  // Competition Volume (Phase 6): only real backend data, no mock values.
  useEffect(() => {
    const options = [...activeCompetitions, ...upcomingCompetitions];
    if (volumeCompetitionId === null && options.length > 0) {
      setVolumeCompetitionId(options[0].id);
    }
  }, [activeCompetitions, upcomingCompetitions, volumeCompetitionId]);

  useEffect(() => {
    if (volumeCompetitionId === null) return;
    fetch(`${apiBase}/competition-volume/${volumeCompetitionId}/pairs`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data) {
          setVolumePairs(data.pairs ?? []);
          setVolumePair((data.pairs ?? [])[0]?.pair ?? null);
        }
      })
      .catch(() => setVolumeError("Volume pairs unavailable"));
    fetch(`${apiBase}/competition-volume/${volumeCompetitionId}/summary`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data) setVolumeSummary(data);
      })
      .catch(() => setVolumeError("Volume summary unavailable"));
  }, [volumeCompetitionId]);

  useEffect(() => {
    if (volumeCompetitionId === null || volumePair === null) return;
    fetch(
      `${apiBase}/competition-volume/${volumeCompetitionId}/history?trading_pair=${volumePair}&page_size=20`
    )
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data) setVolumeHistory(data.items ?? []);
      })
      .catch(() => setVolumeError("Volume history unavailable"));
  }, [volumeCompetitionId, volumePair]);

  // Market, Futures, and News (Phase 7): only real backend data.
  useEffect(() => {
    fetch(`${apiBase}/market/overview`)
      .then((response) => response.json())
      .then((data) => {
        if (data) setMarketItems(data.items ?? []);
      })
      .catch(() => setPhase7Error("Market overview unavailable"));
    fetch(`${apiBase}/market/gainers?limit=5`)
      .then((response) => response.json())
      .then((data) => {
        if (data) setGainers(data.gainers ?? []);
      })
      .catch(() => setPhase7Error("Top gainers unavailable"));
    fetch(`${apiBase}/market/losers?limit=5`)
      .then((response) => response.json())
      .then((data) => {
        if (data) setLosers(data.losers ?? []);
      })
      .catch(() => setPhase7Error("Top losers unavailable"));
    fetch(`${apiBase}/market/watchlist`)
      .then((response) => response.json())
      .then((data) => {
        if (data) setWatchlist(data.items ?? []);
      })
      .catch(() => setPhase7Error("Watchlist unavailable"));
    fetch(`${apiBase}/futures/summary`)
      .then((response) => response.json())
      .then((data) => {
        if (data) setFuturesSummary(data);
      })
      .catch(() => setPhase7Error("Futures summary unavailable"));
    fetch(`${apiBase}/news?page_size=5`)
      .then((response) => response.json())
      .then((data) => {
        if (data) setNewsItems(data.items ?? []);
      })
      .catch(() => setPhase7Error("News unavailable"));
    fetch(`${apiBase}/news/listings?page_size=5`)
      .then((response) => response.json())
      .then((data) => {
        if (data) setListings(data.items ?? []);
      })
      .catch(() => setPhase7Error("Listings unavailable"));
  }, []);
  const selectedPairSummary = volumeSummary?.per_pair.find(
    (item) => item.trading_pair === volumePair
  );
  const latestInterval = selectedPairSummary?.latest_interval ?? null;
  const chartData = [...volumeHistory]
    .reverse()
    .map((item) => ({
      label: item.interval_start.slice(11, 16),
      quoteVolume: item.public_quote_volume === null ? 0 : Number(item.public_quote_volume),
    }));

  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="text-3xl font-bold">Crypto Intelligence Admin</h1>
      <p className="mt-2 text-slate-400">
        Phase 1 foundation. The full dashboard pages arrive in Phase 8; this
        page verifies the frontend can reach the live backend health endpoint.
      </p>
      <section className="mt-6 rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="font-semibold">Backend health</h2>
        {health ? (
          <dl className="mt-2 space-y-1 text-sm">
            <div><dt className="inline text-slate-400">Status: </dt><dd className="inline">{health.status}</dd></div>
            <div><dt className="inline text-slate-400">Service: </dt><dd className="inline">{health.service}</dd></div>
            <div><dt className="inline text-slate-400">Environment: </dt><dd className="inline">{health.environment}</dd></div>
            <div><dt className="inline text-slate-400">Timestamp: </dt><dd className="inline">{health.timestamp}</dd></div>
          </dl>
        ) : error ? (
          <p className="mt-2 text-sm text-red-400">Backend unavailable: {error}</p>
        ) : (
          <p className="mt-2 text-sm text-slate-400">Checking backend…</p>
        )}
      </section>
      <section className="mt-6 rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="font-semibold">Latest announcements</h2>
        {announcements.length === 0 ? (
          <p className="mt-2 text-sm text-slate-400">No announcements collected yet.</p>
        ) : (
          <ul className="mt-2 space-y-2 text-sm">
            {announcements.map((item) => (
              <li key={item.id}>
                <a className="text-sky-400 underline" href={item.canonical_url} target="_blank" rel="noreferrer">
                  {item.title}
                </a>
                <span className="ml-2 text-slate-400">
                  {item.category} ({item.category_confidence})
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="mt-6 rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="font-semibold">Alpha, airdrops and Prime Sales</h2>
        <h3 className="mt-3 text-sm font-semibold text-slate-300">Latest Alpha tokens</h3>
        {alphaTokens.length === 0 ? (
          <p className="mt-1 text-sm text-slate-400">None recorded yet.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {alphaTokens.map((item) => (
              <li key={item.id}>
                <a className="text-sky-400 underline" href={item.announcement_url} target="_blank" rel="noreferrer">
                  {item.token_name}{item.token_symbol ? ` (${item.token_symbol})` : ""}
                </a>
              </li>
            ))}
          </ul>
        )}
        <h3 className="mt-3 text-sm font-semibold text-slate-300">Active airdrops</h3>
        {activeAirdrops.length === 0 ? (
          <p className="mt-1 text-sm text-slate-400">None recorded yet.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {activeAirdrops.map((item) => (
              <li key={item.id}>
                <a className="text-sky-400 underline" href={item.official_url} target="_blank" rel="noreferrer">
                  {item.campaign_name}
                </a>
                <span className="ml-2 text-slate-400">{item.status}</span>
              </li>
            ))}
          </ul>
        )}
        <h3 className="mt-3 text-sm font-semibold text-slate-300">Active Prime Sales</h3>
        {activePrimeSales.length === 0 ? (
          <p className="mt-1 text-sm text-slate-400">None recorded yet.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {activePrimeSales.map((item) => (
              <li key={item.id}>
                <a className="text-sky-400 underline" href={item.official_url} target="_blank" rel="noreferrer">
                  {item.token_name}
                </a>
                <span className="ml-2 text-slate-400">{item.status}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="mt-6 rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="font-semibold">Trading competitions</h2>
        <h3 className="mt-3 text-sm font-semibold text-slate-300">Active competitions</h3>
        {activeCompetitions.length === 0 ? (
          <p className="mt-1 text-sm text-slate-400">None recorded yet.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {activeCompetitions.map((item) => (
              <li key={item.id}>
                <a className="text-sky-400 underline" href={item.official_url} target="_blank" rel="noreferrer">
                  {item.competition_name}
                </a>
                <span className="ml-2 text-slate-400">{item.competition_type} — {item.status}</span>
              </li>
            ))}
          </ul>
        )}
        <h3 className="mt-3 text-sm font-semibold text-slate-300">Upcoming competitions</h3>
        {upcomingCompetitions.length === 0 ? (
          <p className="mt-1 text-sm text-slate-400">None recorded yet.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {upcomingCompetitions.map((item) => (
              <li key={item.id}>
                <a className="text-sky-400 underline" href={item.official_url} target="_blank" rel="noreferrer">
                  {item.competition_name}
                </a>
                <span className="ml-2 text-slate-400">{item.competition_type} — {item.status}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="mt-6 rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="font-semibold">Competition Volume (30-minute intervals)</h2>
        <p className="mt-2 text-sm text-slate-400">
          Public market volume comes from Binance public trade data
          (aggTrades). Estimated eligible volume appears only when a
          verified multiplier exists; official eligible volume is
          Unavailable in this phase — public volume is never presented
          as eligible volume. Official leaderboard data is not implemented.
        </p>
        {activeCompetitions.length + upcomingCompetitions.length === 0 ? (
          <p className="mt-2 text-sm text-slate-400">No active or upcoming competitions yet.</p>
        ) : (
          <>
            <div className="mt-3 flex flex-wrap gap-3 text-sm">
              <label>
                <span className="mr-2 text-slate-400">Competition:</span>
                <select
                  className="bg-slate-800 p-1"
                  value={volumeCompetitionId ?? ""}
                  onChange={(event) => setVolumeCompetitionId(Number(event.target.value))}
                >
                  {[...activeCompetitions, ...upcomingCompetitions].map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.competition_name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="mr-2 text-slate-400">Trading pair:</span>
                <select
                  className="bg-slate-800 p-1"
                  value={volumePair ?? ""}
                  onChange={(event) => setVolumePair(event.target.value)}
                >
                  {volumePairs.map((item) => (
                    <option key={item.pair} value={item.pair}>
                      {item.pair}
                      {item.tracking_enabled ? "" : " (tracking off)"}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {volumeError && <p className="mt-2 text-sm text-red-400">{volumeError}</p>}
            {selectedPairSummary && (
              <dl className="mt-3 space-y-1 text-sm">
                <div>
                  <dt className="inline text-slate-400">Latest completed 30-minute volume: </dt>
                  <dd className="inline">
                    {latestInterval?.public_base_volume ?? "Unavailable"}{" "}
                    {latestInterval?.base_asset ?? ""} /{" "}
                    {latestInterval?.public_quote_volume ?? "Unavailable"}{" "}
                    {latestInterval?.quote_asset ?? ""}
                    {latestInterval ? ` (${formatUtc(latestInterval.interval_start)} – ${formatUtc(latestInterval.interval_end)}; ${formatPkt(latestInterval.interval_start)} – ${formatPkt(latestInterval.interval_end)})` : ""}
                  </dd>
                </div>
                <div>
                  <dt className="inline text-slate-400">Data status: </dt>
                  <dd className="inline">
                    {latestInterval?.data_status ?? "Unavailable"}
                    {latestInterval?.recalculated ? " (recalculated)" : ""}
                  </dd>
                </div>
                <div>
                  <dt className="inline text-slate-400">Cumulative public volume: </dt>
                  <dd className="inline">
                    {selectedPairSummary.cumulative_public_base_volume ?? "Unavailable"} /{" "}
                    {selectedPairSummary.cumulative_public_quote_volume ?? "Unavailable"}
                    {` (${selectedPairSummary.interval_count} stored intervals)`}
                  </dd>
                </div>
                <div>
                  <dt className="inline text-slate-400">Estimated eligible volume (cumulative): </dt>
                  <dd className="inline">
                    {selectedPairSummary.cumulative_estimated_eligible_volume ?? "Unavailable"}
                  </dd>
                </div>
                <div>
                  <dt className="inline text-slate-400">Official eligible volume: </dt>
                  <dd className="inline">Unavailable</dd>
                </div>
                <div>
                  <dt className="inline text-slate-400">Last collection: </dt>
                  <dd className="inline">
                    {volumeSummary?.last_collection_at
                      ? `${formatUtc(volumeSummary.last_collection_at)} (${formatPkt(volumeSummary.last_collection_at)}; ${volumeSummary.last_collection_status ?? ""})`
                      : "Unavailable"}
                  </dd>
                </div>
              </dl>
            )}
            {volumeHistory.length > 0 && (
              <div className="mt-4 h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData}>
                    <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 12 }} />
                    <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} />
                    <Tooltip />
                    <Bar dataKey="quoteVolume" fill="#38bdf8" name="Public quote volume" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
            <h3 className="mt-4 text-sm font-semibold text-slate-300">Interval history</h3>
            {volumeHistory.length === 0 ? (
              <p className="mt-1 text-sm text-slate-400">No volume intervals collected yet.</p>
            ) : (
              <table className="mt-2 w-full text-left text-sm">
                <thead>
                  <tr className="text-slate-400">
                    <th>Interval (UTC)</th>
                    <th>Public volume</th>
                    <th>Estimated eligible</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {volumeHistory.map((item) => (
                    <tr key={item.id} className="border-t border-slate-800">
                      <td>{formatUtc(item.interval_start)} – {item.interval_end.slice(11, 16)}</td>
                      <td>
                        {item.public_base_volume ?? "Unavailable"} /{" "}
                        {item.public_quote_volume ?? "Unavailable"}
                      </td>
                      <td>{item.estimated_eligible_volume ?? "Unavailable"}</td>
                      <td>
                        {item.data_status}
                        {item.recalculated ? " (recalculated)" : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </section>
      <section className="mt-6 rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="font-semibold">Market</h2>
        <p className="mt-2 text-sm text-slate-400">
          Prices come from Binance Spot public data. Symbols below the
          minimum quote volume are excluded from gainers and losers, and
          stale data is labelled as stale. Price movements are not
          trading opportunities.
        </p>
        {phase7Error && <p className="mt-2 text-sm text-red-400">{phase7Error}</p>}
        {marketItems.length === 0 ? (
          <p className="mt-2 text-sm text-slate-400">No market snapshots collected yet.</p>
        ) : (
          <table className="mt-2 w-full text-left text-sm">
            <thead>
              <tr className="text-slate-400">
                <th>Symbol</th>
                <th>Price</th>
                <th>24h change</th>
                <th>24h quote volume</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {marketItems.map((item) => (
                <tr key={item.symbol} className="border-t border-slate-800">
                  <td>{item.symbol}</td>
                  <td>{item.price ?? "Unavailable"}</td>
                  <td>{item.price_change_percent_24h ?? "Unavailable"}%</td>
                  <td>{item.quote_volume_24h ?? "Unavailable"}</td>
                  <td>{item.is_stale ? "Stale" : "Fresh"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <h3 className="mt-4 text-sm font-semibold text-slate-300">Top gainers</h3>
        {gainers.length === 0 ? (
          <p className="mt-1 text-sm text-slate-400">No gainers yet.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {gainers.map((item) => (
              <li key={item.symbol}>
                {item.symbol}: {item.price} ({item.price_change_percent_24h}%)
              </li>
            ))}
          </ul>
        )}
        <h3 className="mt-4 text-sm font-semibold text-slate-300">Top losers</h3>
        {losers.length === 0 ? (
          <p className="mt-1 text-sm text-slate-400">No losers yet.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {losers.map((item) => (
              <li key={item.symbol}>
                {item.symbol}: {item.price} ({item.price_change_percent_24h}%)
              </li>
            ))}
          </ul>
        )}
        <h3 className="mt-4 text-sm font-semibold text-slate-300">Watchlist</h3>
        {watchlist.length === 0 ? (
          <p className="mt-1 text-sm text-slate-400">Watchlist is empty.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {watchlist.map((item) => (
              <li key={item.symbol}>
                {item.symbol}: {item.price ?? "Unavailable"}
                {item.is_stale ? " (stale)" : ""}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="mt-6 rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="font-semibold">Futures</h2>
        <p className="mt-2 text-sm text-slate-400">
          Funding rates and open interest come from Binance Futures
          public data. When Futures is restricted in this location, this
          section reports Unavailable instead of showing invented data.
          Open interest alone does not imply market direction.
        </p>
        {futuresSummary === null ? (
          <p className="mt-2 text-sm text-slate-400">Futures summary unavailable.</p>
        ) : (
          <dl className="mt-3 space-y-1 text-sm">
            <div>
              <dt className="inline text-slate-400">Availability: </dt>
              <dd className="inline">{futuresSummary.availability}</dd>
            </div>
            <div>
              <dt className="inline text-slate-400">Symbols tracked: </dt>
              <dd className="inline">{futuresSummary.symbols}</dd>
            </div>
            <div>
              <dt className="inline text-slate-400">Highest funding: </dt>
              <dd className="inline">
                {futuresSummary.highest_funding
                  ? `${futuresSummary.highest_funding.symbol}: ${futuresSummary.highest_funding.funding_rate ?? "Unavailable"}`
                  : "Unavailable"}
              </dd>
            </div>
            <div>
              <dt className="inline text-slate-400">Lowest funding: </dt>
              <dd className="inline">
                {futuresSummary.lowest_funding
                  ? `${futuresSummary.lowest_funding.symbol}: ${futuresSummary.lowest_funding.funding_rate ?? "Unavailable"}`
                  : "Unavailable"}
              </dd>
            </div>
          </dl>
        )}
      </section>
      <section className="mt-6 rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="font-semibold">News</h2>
        <p className="mt-2 text-sm text-slate-400">
          News is built from official Binance announcements. Summaries
          are unavailable when article bodies cannot be fetched; only
          the headline and the original link are shown then.
        </p>
        {newsItems.length === 0 ? (
          <p className="mt-2 text-sm text-slate-400">No news collected yet.</p>
        ) : (
          <ul className="mt-2 space-y-2 text-sm">
            {newsItems.map((item) => (
              <li key={item.id}>
                <span className="text-slate-400">[{item.category}] </span>
                {item.headline} — {item.publisher}
                {item.published_at ? ` (${formatUtc(item.published_at)}; ${formatPkt(item.published_at)})` : ""}
                <br />
                <a className="text-sky-400 underline" href={item.original_url}>
                  Read original
                </a>
              </li>
            ))}
          </ul>
        )}
        <h3 className="mt-4 text-sm font-semibold text-slate-300">Listings</h3>
        {listings.length === 0 ? (
          <p className="mt-1 text-sm text-slate-400">No listings yet.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {listings.map((item) => (
              <li key={item.id}>
                {item.headline} —{" "}
                <a className="text-sky-400 underline" href={item.original_url}>
                  Read original
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
