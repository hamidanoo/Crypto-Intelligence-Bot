"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiMutate, asItems, fmt } from "../../lib/admin";
import { Empty, ErrorBox, Feedback, Loading, PageHeader, Panel, TableWrap, tableClass, tdClass, thClass } from "../components/ui";

type Job = { id: string | number; name?: string; interval_minutes?: number; next_run_time?: string | null; last_run_at?: string | null; last_status?: string | null; enabled?: boolean };

export default function SchedulerPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch("/api/admin/scheduler");
      setJobs(asItems<Job>(data).items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load scheduler jobs.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function act(job: Job, action: "pause" | "resume" | "trigger") {
    if (action === "pause" && !window.confirm(`Pause job ${job.name ?? job.id}?`)) return;
    try {
      const d = await apiMutate<Record<string, unknown>>(`/api/admin/scheduler/${job.id}/${action}`, "POST");
      const msg = d.status ?? d.message ?? d.detail;
      setFeedback(typeof msg === "string" ? `${action} (${job.name ?? job.id}): ${msg}` : `${action} request for ${job.name ?? job.id} completed.`);
      void load();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : `${action} failed.`);
    }
  }

  return (
    <div>
      <PageHeader title="Scheduler" description="Scheduled collection jobs: pause, resume, or trigger a run now." />
      <Feedback message={feedback} />
      {loading ? <Loading /> : error ? <ErrorBox message={error} /> : jobs.length === 0 ? <Empty /> : (
        <Panel><TableWrap><table className={tableClass}>
          <thead><tr><th className={thClass}>Job</th><th className={thClass}>Interval (min)</th><th className={thClass}>Next run</th><th className={thClass}>Last run</th><th className={thClass}>Last status</th><th className={thClass}>Enabled</th><th className={thClass}>Actions</th></tr></thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={String(j.id)}>
                <td className={tdClass}>{j.name ?? j.id}</td>
                <td className={tdClass}>{j.interval_minutes ?? "—"}</td>
                <td className={tdClass}>{fmt(j.next_run_time)}</td>
                <td className={tdClass}>{fmt(j.last_run_at)}</td>
                <td className={tdClass}>{j.last_status ?? "—"}</td>
                <td className={tdClass}>{j.enabled ? "Yes" : "No"}</td>
                <td className={tdClass}>
                  <div className="flex flex-wrap gap-2">
                    {j.enabled ? <button className="btn" onClick={() => act(j, "pause")}>Pause</button> : <button className="btn" onClick={() => act(j, "resume")}>Resume</button>}
                    <button className="btn btn-primary" onClick={() => act(j, "trigger")}>Trigger now</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table></TableWrap></Panel>
      )}
    </div>
  );
}
