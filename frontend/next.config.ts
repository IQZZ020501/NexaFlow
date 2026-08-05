import type { NextConfig } from "next"

// Dev proxy target; production deployments route /api through a reverse proxy.
// Use 127.0.0.1, not localhost: the dev backend binds IPv4 only, and Node's
// happy-eyeballs may pick ::1 for `localhost`, making proxied requests fail
// with ECONNRESET/500.
const BACKEND_ORIGIN = process.env.NEXAFLOW_API_PROXY ?? "http://127.0.0.1:8000"

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Dev proxy clones rewrite bodies with a 10MB default cap
  // (DEFAULT_BODY_CLONE_SIZE_LIMIT in next/dist/server/body-streams.js);
  // backend allows 100MB per document, keep the proxy at 101MB and give
  // long-running synchronous parses room past the 30s default proxyTimeout.
  experimental: {
    middlewareClientMaxBodySize: "101mb",
    proxyTimeout: 120,
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` },
      { source: "/health", destination: `${BACKEND_ORIGIN}/health` },
    ]
  },
}

export default nextConfig
