"use client";

import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{children}</section>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <p className="py-6 text-sm text-slate-400">{label}</p>;
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <p role="alert" className="panel mb-4 border-red-500/50 p-3 text-sm text-red-400">
      {message}
    </p>
  );
}

export function Empty({ message = "No records found." }: { message?: string }) {
  return <p className="py-4 text-sm text-slate-400">{message}</p>;
}

export function Feedback({ message }: { message: string | null }) {
  if (!message) return null;
  return <p className="mb-3 text-sm text-slate-300">{message}</p>;
}

export function Pagination({
  page,
  total,
  pageSize,
  onPage,
}: {
  page: number;
  total: number;
  pageSize: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
  if (total <= 0) return null;
  return (
    <div className="mt-4 flex items-center gap-3 text-sm">
      <button className="btn" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span className="text-slate-400">
        Page {page} of {pages} ({total} total)
      </span>
      <button className="btn" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </div>
  );
}

export function TableWrap({ children }: { children: ReactNode }) {
  return <div className="overflow-x-auto">{children}</div>;
}

export const tableClass = "w-full text-left text-sm";
export const thClass = "px-2 py-2 text-slate-400";
export const tdClass = "border-t border-slate-800 px-2 py-2 align-top";
