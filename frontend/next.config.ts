import type { NextConfig } from "next"

// Dev proxy target; production deployments route /api through a reverse proxy.
const BACKEND_ORIGIN = process.env.NEXAFLOW_API_PROXY ?? "http://localhost:8000"

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Next dev proxies rewrite bodies through a 10MB clone buffer by default
  // (DEFAULT_BODY_CLONE_SIZE_LIMIT in next/dist/server/body-streams.js); larger
  // uploads stall the proxy until proxyTimeout and surface as HTTP 500.
  // Backend allows up to 100MB per document, so keep the proxy at 101MB
  // (multipart overhead included).
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
