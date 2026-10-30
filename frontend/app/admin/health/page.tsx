"use client";

import { useEffect, useState } from "react";
import { apiFetch, fmt } from "../../lib/admin";
import { Empty, ErrorBox, Loading, PageHeader, Panel, TableWrap, tableClass, tdClass, thClass } from "../components/ui";

type Service = { name?: string; status?: string; detail?: string | null; last_success_at?: string | null };

const color: Record<string, string> = {
  healthy: "text-emerald-400",
  degraded: "text-amber-400",
  unavailable: "text-red-400",
  unknown: "text-slate-400",
};

export default function HealthPage() {
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<{ services?: Service[] }>("/api/admin/dashboard/health")
      .then((d) => setServices(d.services ?? []))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load health."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <PageHeader title="System Health" description="Per-service status reported by the backend." />
      {loading ? <Loading /> : error ? <ErrorBox message={error} /> : services.length === 0 ? <Empty /> : (
        <Panel><TableWrap><table className={tableClass}>
          <thead><tr><th className={thClass}>Service</th><th className={thClass}>Status</th><th className={thClass}>Detail</th><th className={thClass}>Last success</th></tr></thead>
          <tbody>
            {services.map((s, i) => (
              <tr key={s.name ?? i}>
                <td className={tdClass}>{s.name ?? "—"}</td>
                <td className={`${tdClass} ${color[(s.status ?? "unknown").toLowerCase()] ?? color.unknown}`}>{s.status ?? "unknown"}</td>
                <td className={tdClass}>{s.detail ?? "—"}</td>
                <td className={tdClass}>{fmt(s.last_success_at)}</td>
              </tr>
            ))}
          </tbody>
        </table></TableWrap></Panel>
      )}
    </div>
  );
}
