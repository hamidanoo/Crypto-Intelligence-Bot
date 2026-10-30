"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiMutate, asItems, fmt } from "../../lib/admin";
import { Empty, ErrorBox, Feedback, Loading, PageHeader, Pagination, Panel, TableWrap, tableClass, tdClass, thClass } from "../components/ui";

type User = { id: number | string; username?: string; email?: string | null; role?: string | null; is_active?: boolean; is_superuser?: boolean; created_at?: string | null };
type Role = { id: number | string; name?: string; permissions?: string[] };

export default function AdministratorsPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [roles, setRoles] = useState<Role[]>([]);
  const [allPerms, setAllPerms] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [roleName, setRoleName] = useState("");
  const [rolePerms, setRolePerms] = useState<string[]>([]);
  const pageSize = 20;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/admin/users?page=${page}&page_size=${pageSize}`);
      const r = asItems<User>(data);
      setUsers(r.items);
      setTotal(r.total);
      const rolesData = await apiFetch("/api/admin/roles").catch(() => null);
      if (rolesData) setRoles(asItems<Role>(rolesData).items);
      const permsData = await apiFetch<{ permissions?: string[] }>("/api/admin/permissions").catch(() => null);
      if (permsData?.permissions) setAllPerms(permsData.permissions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load administrators.");
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => { void load(); }, [load]);

  async function createUser(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await apiMutate("/api/admin/users", "POST", { username, email, password, role, is_active: isActive });
      setFeedback("User created.");
      setUsername(""); setEmail(""); setPassword(""); setRole(""); setIsActive(true);
      void load();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Create failed.");
    } finally {
      setBusy(false);
    }
  }

  async function deactivate(u: User) {
    if (!window.confirm(`Deactivate user ${u.username}?`)) return;
    try {
      await apiMutate(`/api/admin/users/${u.id}/deactivate`, "POST");
      setFeedback(`User ${u.username} deactivated.`);
      void load();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Deactivate failed.");
    }
  }

  async function createRole(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await apiMutate("/api/admin/roles", "POST", { name: roleName, permissions: rolePerms });
      setFeedback("Role created.");
      setRoleName(""); setRolePerms([]);
      void load();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Create role failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader title="Administrators" description="Admin users and roles." />
      <Feedback message={feedback} />
      {loading ? <Loading /> : error ? <ErrorBox message={error} /> : (
        <>
          <Panel className="mb-4">
            <h2 className="mb-2 font-semibold">Users</h2>
            {users.length === 0 ? <Empty /> : (
              <>
                <TableWrap><table className={tableClass}>
                  <thead><tr><th className={thClass}>Username</th><th className={thClass}>Email</th><th className={thClass}>Role</th><th className={thClass}>Active</th><th className={thClass}>Superuser</th><th className={thClass}>Created</th><th className={thClass}>Actions</th></tr></thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={String(u.id)}>
                        <td className={tdClass}>{u.username ?? "—"}</td>
                        <td className={tdClass}>{u.email ?? "—"}</td>
                        <td className={tdClass}>{u.role ?? "—"}</td>
                        <td className={tdClass}>{u.is_active ? "Yes" : "No"}</td>
                        <td className={tdClass}>{u.is_superuser ? "Yes" : "No"}</td>
                        <td className={tdClass}>{fmt(u.created_at)}</td>
                        <td className={tdClass}>{u.is_active ? <button className="btn btn-danger" onClick={() => deactivate(u)}>Deactivate</button> : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table></TableWrap>
                <Pagination page={page} total={total} pageSize={pageSize} onPage={setPage} />
              </>
            )}
          </Panel>
          <Panel className="mb-4">
            <h2 className="font-semibold">Create user</h2>
            <form onSubmit={createUser} className="mt-3 space-y-3">
              <input className="field" placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} required />
              <input className="field" placeholder="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              <input className="field" placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="new-password" />
              <input className="field" placeholder="Role" value={role} onChange={(e) => setRole(e.target.value)} required />
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} /> Active</label>
              <button className="btn btn-primary" disabled={busy} type="submit">Create user</button>
            </form>
          </Panel>
          <Panel className="mb-4">
            <h2 className="mb-2 font-semibold">Roles</h2>
            {roles.length === 0 ? <Empty message="No roles found." /> : (
              <ul className="space-y-1 text-sm">
                {roles.map((r) => <li key={String(r.id)}>{r.name ?? r.id}: {(r.permissions ?? []).join(", ") || "—"}</li>)}
              </ul>
            )}
          </Panel>
          <Panel>
            <h2 className="font-semibold">Create role</h2>
            <form onSubmit={createRole} className="mt-3 space-y-3">
              <input className="field" placeholder="Role name" value={roleName} onChange={(e) => setRoleName(e.target.value)} required />
              <div>
                <p className="text-sm text-slate-400">Permissions</p>
                {allPerms.length === 0 ? <p className="text-sm text-slate-400">Permission list not returned by the backend; enter a role name and no permissions, or check /api/admin/permissions.</p> : allPerms.map((p) => (
                  <label key={p} className="mr-4 inline-flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={rolePerms.includes(p)} onChange={(e) => setRolePerms(e.target.checked ? [...rolePerms, p] : rolePerms.filter((x) => x !== p))} /> {p}
                  </label>
                ))}
              </div>
              <button className="btn btn-primary" disabled={busy} type="submit">Create role</button>
            </form>
          </Panel>
        </>
      )}
    </div>
  );
}
