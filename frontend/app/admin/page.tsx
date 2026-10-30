"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiFetch } from "../lib/admin";
import { Empty, ErrorBox, Loading, PageHeader, Panel } from "./components/ui";

type Overview = {
  announcements_total?: number;
  announcements_new?: number;
  active_alpha_tokens?: number;
  active_airdrops?: number;
  upcoming_prime_sales?: number;
  active_competitions?: number;
  latest_competition_volume?: {
    competition_id?: number;
    trading_pair?: string;
    public_base_volume?: string | null;
    public_quote_volume?: string | null;
    interval_start?: string | null;
  } | null;
  market_status?: { status?: string; latest_snapshot_at?: string | null };
  futures_status?: { availability?: string; last_collection_status?: string | null };
  latest_news?: { id: number; headline: string; category?: string; published_at?: string | null; original_url?: string }[];
  telegram_status?: { configured?: boolean; group_configured?: boolean };
  scheduler_status?: { running?: boolean; job_count?: number };
  database_status?: string;
  redis_status?: string;
  latest_collection_errors?: { module?: string; error?: string; at?: string }[];
  dashboard_refresh_interval_seconds?: number;
};

type DayPoint = { date: string; count: number };
type Activity = {
  announcements_by_day?: DayPoint[];
  news_by_day?: DayPoint[];
  volume_by_day?: DayPoint[];
  notifications_by_day?: DayPoint[];
};

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Panel>
      <p className="text-sm text-slate-400">{label}</p>
      <p className="mt-1 text-2xl font-bold">{value ?? "—"}</p>
    </Panel>
  );
}

export default function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [activity, setActivity] = useState<Activity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiFetch<Overview>("/api/admin/dashboard/overview").catch((e) => {
        throw e;
      }),
      apiFetch<Activity>("/api/admin/dashboard/activity").catch(() => null),
    ])
      .then(([ov, act]) => {
        setData(ov);
        setActivity(act);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load overview."))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return <Empty />;

  const vol = data.latest_competition_volume;
  const chartData = (activity?.announcements_by_day ?? []).map((d) => ({
    date: d.date,
    announcements: d.count,
    news: (activity?.news_by_day ?? []).find((n) => n.date === d.date)?.count ?? 0,
  }));

  return (
    <div>
      <PageHeader
        title="Overview"
        description={
          data.dashboard_refresh_interval_seconds
            ? `Dashboard refresh interval: ${data.dashboard_refresh_interval_seconds}s`
            : undefined
        }
      />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Announcements total" value={data.announcements_total} />
        <Stat label="New announcements" value={data.announcements_new} />
        <Stat label="Active Alpha tokens" value={data.active_alpha_tokens} />
        <Stat label="Active airdrops" value={data.active_airdrops} />
        <Stat label="Upcoming Prime Sales" value={data.upcoming_prime_sales} />
        <Stat label="Active competitions" value={data.active_competitions} />
        <Stat
          label="Scheduler"
          value={
            data.scheduler_status
              ? `${data.scheduler_status.running ? "Running" : "Stopped"} (${data.scheduler_status.job_count ?? 0} jobs)`
              : "—"
          }
        />
        <Stat label="Database / Redis" value={`${data.database_status ?? "—"} / ${data.redis_status ?? "—"}`} />
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <Panel>
          <h2 className="font-semibold">Latest competition volume</h2>
          {vol ? (
            <p className="mt-2 text-sm">
              {vol.trading_pair ?? "—"} — base {vol.public_base_volume ?? "Unavailable"}, quote{" "}
              {vol.public_quote_volume ?? "Unavailable"}
              {vol.interval_start ? ` (from ${vol.interval_start})` : ""}
            </p>
          ) : (
            <p className="mt-2 text-sm text-slate-400">No competition volume recorded yet.</p>
          )}
          <h3 className="mt-4 font-semibold">Market / Futures</h3>
          <p className="mt-1 text-sm">
            Market: {data.market_status?.status ?? "—"}
            {data.market_status?.latest_snapshot_at ? ` (latest ${data.market_status.latest_snapshot_at})` : ""}
          </p>
          <p className="mt-1 text-sm">
            Futures: {data.futures_status?.availability ?? "—"}
            {data.futures_status?.last_collection_status ? ` (${data.futures_status.last_collection_status})` : ""}
          </p>
          <h3 className="mt-4 font-semibold">Telegram</h3>
          <p className="mt-1 text-sm">
            Configured: {data.telegram_status?.configured ? "Yes" : "No"}; group:{" "}
            {data.telegram_status?.group_configured ? "Yes" : "No"}
          </p>
        </Panel>
        <Panel>
          <h2 className="font-semibold">Latest collection errors</h2>
          {(data.latest_collection_errors ?? []).length === 0 ? (
            <p className="mt-2 text-sm text-slate-400">No recent collection errors.</p>
          ) : (
            <ul className="mt-2 space-y-2 text-sm">
              {data.latest_collection_errors!.map((e, i) => (
                <li key={i}>
                  <span className="text-slate-400">{e.module ?? "—"}: </span>
                  {e.error ?? "—"} {e.at ? `(${e.at})` : ""}
                </li>
              ))}
            </ul>
          )}
          <h2 className="mt-4 font-semibold">Latest news</h2>
          {(data.latest_news ?? []).length === 0 ? (
            <p className="mt-2 text-sm text-slate-400">No news yet.</p>
          ) : (
            <ul className="mt-2 space-y-1 text-sm">
              {data.latest_news!.map((n) => (
                <li key={n.id}>
                  {n.original_url ? (
                    <a className="text-sky-400 underline" href={n.original_url} target="_blank" rel="noreferrer">
                      {n.headline}
                    </a>
                  ) : (
                    n.headline
                  )}
                  <span className="ml-2 text-slate-400">{n.category ?? ""}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <Panel className="mt-4">
        <h2 className="font-semibold">Activity by day</h2>
        {chartData.length === 0 ? (
          <p className="mt-2 text-sm text-slate-400">No activity data yet.</p>
        ) : (
          <div className="mt-3 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fill: "#94a3b8", fontSize: 12 }} />
                <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="announcements" fill="#38bdf8" />
                <Bar dataKey="news" fill="#818cf8" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        {chartData.length > 0 && (
          <div className="mt-3 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fill: "#94a3b8", fontSize: 12 }} />
                <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} />
                <Tooltip />
                <Line type="monotone" dataKey="announcements" stroke="#38bdf8" />
                <Line type="monotone" dataKey="news" stroke="#818cf8" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </Panel>
    </div>
  );
}
