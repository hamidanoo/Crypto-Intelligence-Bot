"use client";

import { useEffect, useState } from "react";

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

const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [announcements, setAnnouncements] = useState<AnnouncementItem[]>([]);

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
  }, []);

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
    </main>
  );
}
