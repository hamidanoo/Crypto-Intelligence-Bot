"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiFetch, apiMutate, hasPermission, useMe } from "../lib/admin";

type NavItem = { href: string; label: string; perm: string };

const NAV: NavItem[] = [
  { href: "/admin", label: "Overview", perm: "dashboard.view" },
  { href: "/admin/announcements", label: "Announcements", perm: "announcements.view" },
  { href: "/admin/alpha", label: "Alpha Tokens", perm: "intelligence.view" },
  { href: "/admin/airdrops", label: "Airdrops", perm: "intelligence.view" },
  { href: "/admin/prime-sales", label: "Prime Sales", perm: "intelligence.view" },
  { href: "/admin/competitions", label: "Competitions", perm: "competitions.view" },
  { href: "/admin/volume", label: "Competition Volume", perm: "volume.view" },
  { href: "/admin/market", label: "Market Intelligence", perm: "market.view" },
  { href: "/admin/futures", label: "Futures Intelligence", perm: "market.view" },
  { href: "/admin/news", label: "News", perm: "news.view" },
  { href: "/admin/telegram", label: "Telegram Management", perm: "telegram.view" },
  { href: "/admin/integrations", label: "API Integrations", perm: "integrations.view" },
  { href: "/admin/notifications", label: "Notification Settings", perm: "notifications.view" },
  { href: "/admin/scheduler", label: "Scheduler", perm: "scheduler.view" },
  { href: "/admin/administrators", label: "Administrators", perm: "users.view" },
  { href: "/admin/audit-logs", label: "Audit Logs", perm: "audit.view" },
  { href: "/admin/health", label: "System Health", perm: "dashboard.view" },
  { href: "/admin/settings", label: "Settings", perm: "settings.view" },
];

type Overview = {
  announcements_new?: number;
  latest_collection_errors?: unknown[];
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { me, loading, status } = useMe();
  const router = useRouter();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("dark");
  const [notifyCount, setNotifyCount] = useState<number | null>(null);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && status === 401) {
      router.replace("/login?next=/admin&expired=1");
    }
  }, [loading, status, router]);

  useEffect(() => {
    const stored = window.localStorage.getItem("ci-theme");
    const initial = stored === "light" ? "light" : "dark";
    setTheme(initial);
    document.documentElement.dataset.theme = initial;
  }, []);

  useEffect(() => {
    if (!me) return;
    if (!hasPermission(me, "dashboard.view")) return;
    apiFetch<Overview>("/api/admin/dashboard/overview")
      .then((data) => {
        const errors = Array.isArray(data.latest_collection_errors)
          ? data.latest_collection_errors.length
          : 0;
        setNotifyCount((data.announcements_new ?? 0) + errors);
      })
      .catch(() => setNotifyCount(null));
  }, [me]);

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    window.localStorage.setItem("ci-theme", next);
  }

  async function logout() {
    setLogoutError(null);
    try {
      await apiMutate("/api/auth/logout", "POST");
    } catch {
      // Even if the server call fails, the session cookie cannot be
      // cleared from here; still send the user to login.
      setLogoutError("Logout request failed; please try again or close the session.");
      return;
    }
    router.replace("/login");
  }

  if (loading) {
    return (
      <main className="mx-auto max-w-3xl p-8">
        <p className="text-sm text-slate-400">Loading admin session…</p>
      </main>
    );
  }
  if (!me) {
    return (
      <main className="mx-auto max-w-3xl p-8">
        <p className="text-sm text-slate-400">Redirecting to login…</p>
      </main>
    );
  }

  const visibleNav = NAV.filter((item) => hasPermission(me, item.perm));
  const crumbs = pathname
    .split("/")
    .filter(Boolean)
    .map((seg) => seg.replace(/-/g, " "));

  const sidebar = (
    <nav className="space-y-1 p-3 text-sm">
      {visibleNav.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          onClick={() => setMobileOpen(false)}
          className={`block rounded px-3 py-2 ${
            pathname === item.href
              ? "bg-sky-700 text-white"
              : "text-slate-300 hover:bg-slate-800"
          }`}
        >
          {item.label}
        </Link>
      ))}
      {visibleNav.length === 0 && (
        <p className="px-3 py-2 text-slate-400">No admin sections available for this account.</p>
      )}
    </nav>
  );

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      {!collapsed && (
        <aside className="panel !rounded-none hidden w-64 shrink-0 md:block">{sidebar}</aside>
      )}
      {/* Mobile sidebar */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <aside className="panel !rounded-none w-64 shrink-0">{sidebar}</aside>
          <button
            aria-label="Close menu"
            className="flex-1 bg-black/50"
            onClick={() => setMobileOpen(false)}
          />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <header className="panel !rounded-none flex flex-wrap items-center gap-3 !border-x-0 !border-t-0">
          <button className="btn md:hidden" onClick={() => setMobileOpen(true)}>
            Menu
          </button>
          <button className="btn hidden md:inline-block" onClick={() => setCollapsed(!collapsed)}>
            {collapsed ? "Show sidebar" : "Hide sidebar"}
          </button>
          <nav aria-label="Breadcrumb" className="min-w-0 flex-1 truncate text-sm text-slate-400">
            {crumbs.map((c, i) => (
              <span key={i}>
                {i > 0 && " / "}
                {i === crumbs.length - 1 ? <span className="text-slate-200">{c}</span> : c}
              </span>
            ))}
          </nav>
          <button className="btn" onClick={toggleTheme} aria-label="Toggle theme">
            {theme === "dark" ? "Light theme" : "Dark theme"}
          </button>
          {notifyCount !== null && notifyCount > 0 && (
            <span className="rounded-full bg-sky-700 px-2 py-1 text-xs text-white" title="New announcements plus latest collection errors">
              🔔 {notifyCount}
            </span>
          )}
          <div className="relative">
            <button className="btn" onClick={() => setMenuOpen(!menuOpen)}>
              {me.username} ({me.role ?? "admin"})
            </button>
            {menuOpen && (
              <div className="panel absolute right-0 z-50 mt-2 w-56 space-y-2 text-sm">
                <p className="text-slate-400">{me.email ?? ""}</p>
                <Link href="/admin/change-password" className="block text-sky-400 underline" onClick={() => setMenuOpen(false)}>
                  Change password
                </Link>
                <Link href="/admin/settings" className="block text-sky-400 underline" onClick={() => setMenuOpen(false)}>
                  Settings
                </Link>
                <button className="btn btn-danger" onClick={logout}>
                  Log out
                </button>
                {logoutError && <p className="text-red-400">{logoutError}</p>}
              </div>
            )}
          </div>
        </header>
        <main className="p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
