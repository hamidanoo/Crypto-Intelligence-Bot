/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    // In development, and in the Docker frontend service, /api is
    // proxied to the backend, so the browser never needs to know
    // the backend host or port. In production behind Nginx, Nginx
    // already proxies /api/ to the backend, so this rewrite is a
    // fallback for direct Next.js serving.
    const backend = process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};
module.exports = nextConfig;
