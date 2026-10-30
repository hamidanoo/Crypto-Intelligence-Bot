import Link from "next/link";

export default function UnauthorizedPage() {
  return (
    <main className="mx-auto max-w-md p-8">
      <h1 className="text-2xl font-bold">Not authorized</h1>
      <p className="mt-3 text-sm text-slate-400">
        You do not have permission to view this section. If you believe this is an error,
        contact an administrator.
      </p>
      <p className="mt-4 text-sm">
        <Link href="/admin" className="text-sky-400 underline">Back to overview</Link>
        {" · "}
        <Link href="/login" className="text-sky-400 underline">Log in</Link>
      </p>
    </main>
  );
}
