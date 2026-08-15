import type { NextConfig } from "next"

// Dev proxy target; production deployments route /api through a reverse proxy.
// Use 127.0.0.1, not localhost: the dev backend binds IPv4 only, and Node's
// happy-eyeballs may pick ::1 for `localhost`, making proxied requests fail
// with ECONNRESET/500.
const BACKEND_ORIGIN = process.env.NEXAFLOW_API_PROXY ?? "http://127.0.0.1:8000"

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Keep the proxy request-body ceiling aligned with the backend upload limit.
  experimental: {
    middlewareClientMaxBodySize: "100mb",
    proxyTimeout: 120_000,
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` },
      { source: "/docs", destination: `${BACKEND_ORIGIN}/docs` },
      {
        source: "/openapi.json",
        destination: `${BACKEND_ORIGIN}/openapi.json`,
      },
      { source: "/health", destination: `${BACKEND_ORIGIN}/health` },
    ]
  },
}

export default nextConfig
