# Frontend image: Next.js standalone server.
FROM oven/bun:1 AS deps
WORKDIR /app
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile

FROM oven/bun:1 AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
# next.config.ts reads NEXAFLOW_API_PROXY at build time (rewrites are baked
# into routes-manifest.json), so the proxy target must be a build arg.
ARG NEXAFLOW_API_PROXY
ENV NEXAFLOW_API_PROXY=$NEXAFLOW_API_PROXY
# Next.js telemetry pings the network during builds; disable to avoid
# stalls in offline/restricted Docker builds.
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/ ./
RUN bun run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
