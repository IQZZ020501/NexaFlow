import type { McpSourceCreatePayload, McpTransport } from "@/lib/api/tools"

export type McpForm = {
  name: string
  transport: McpTransport
  url: string
  bearerToken: string
  stdioConfig: string
}

export const EMPTY_MCP_FORM: McpForm = {
  name: "",
  transport: "streamable_http",
  url: "",
  bearerToken: "",
  stdioConfig: "",
}

const STDIO_ENV_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/
const STDIO_CONFIG_FIELDS = new Set([
  "command",
  "args",
  "cwd",
  "env",
  "transport",
])

function isPrivateIpv4(hostname: string) {
  const octets = hostname.split(".").map(Number)
  if (
    octets.length !== 4 ||
    octets.some((octet) => !Number.isInteger(octet) || octet < 0 || octet > 255)
  ) {
    return false
  }
  const [first, second] = octets
  return (
    first === 10 ||
    first === 127 ||
    first === 0 ||
    (first === 169 && second === 254) ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168)
  )
}

export const STDIO_CONFIG_EXAMPLE = `{
  "command": "/usr/local/bin/node",
  "args": ["server.js"],
  "cwd": "/srv/mcp",
  "env": {
    "API_KEY": "secret"
  }
}`

export function isPrivateMcpUrl(value: string) {
  let hostname: string
  try {
    hostname = new URL(value).hostname.toLowerCase().replace(/^\[|\]$/g, "")
  } catch {
    return false
  }
  const mappedIpv4 = /^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(
    hostname
  )
  if (mappedIpv4) {
    const high = Number.parseInt(mappedIpv4[1], 16)
    const low = Number.parseInt(mappedIpv4[2], 16)
    return isPrivateIpv4(
      `${high >> 8}.${high & 255}.${low >> 8}.${low & 255}`
    )
  }
  const isIpv6 = hostname.includes(":")

  if (
    hostname === "localhost" ||
    hostname.endsWith(".localhost") ||
    hostname.endsWith(".local") ||
    hostname === "0.0.0.0" ||
    hostname === "::" ||
    hostname === "::1" ||
    (isIpv6 &&
      (hostname.startsWith("fc") ||
        hostname.startsWith("fd") ||
        /^fe[89ab]/.test(hostname)))
  ) {
    return true
  }

  return isPrivateIpv4(hostname)
}

export function parseStdioConfig(
  value: string
):
  | Extract<McpSourceCreatePayload, { transport: "stdio" }>["stdio_config"]
  | null {
  if (!value.trim() || value.length > 65_536) return null
  let config: unknown
  try {
    config = JSON.parse(value)
  } catch {
    return null
  }
  if (!config || typeof config !== "object" || Array.isArray(config))
    return null

  const record = config as Record<string, unknown>
  if (Object.keys(record).some((key) => !STDIO_CONFIG_FIELDS.has(key)))
    return null
  if (record.transport !== undefined && record.transport !== "stdio")
    return null

  const command =
    typeof record.command === "string" ? record.command.trim() : ""
  const args = record.args ?? []
  const cwd = record.cwd
  const env = record.env ?? {}
  if (
    !command ||
    command.length > 1000 ||
    !Array.isArray(args) ||
    args.length > 64 ||
    args.some(
      (argument) => typeof argument !== "string" || argument.length > 2000
    ) ||
    (cwd !== undefined && cwd !== null && typeof cwd !== "string") ||
    !env ||
    typeof env !== "object" ||
    Array.isArray(env)
  ) {
    return null
  }

  const environment = Object.entries(env as Record<string, unknown>)
  if (
    environment.length > 32 ||
    environment.some(
      ([name, envValue]) =>
        name.length > 255 ||
        !STDIO_ENV_NAME.test(name) ||
        typeof envValue !== "string" ||
        envValue.length > 8000
    )
  ) {
    return null
  }

  const normalizedCwd = typeof cwd === "string" ? cwd.trim() : ""
  return {
    command,
    args: args as string[],
    ...(normalizedCwd ? { cwd: normalizedCwd } : {}),
    env: Object.fromEntries(environment) as Record<string, string>,
  }
}

export function buildMcpServerCreatePayload(
  form: McpForm
): McpSourceCreatePayload | null {
  const name = form.name.trim()
  if (!name) return null
  if (form.transport === "stdio") {
    const stdioConfig = parseStdioConfig(form.stdioConfig)
    if (!stdioConfig) return null
    return { name, transport: "stdio", stdio_config: stdioConfig }
  }
  const url = form.url.trim()
  if (!url) return null
  const bearerToken = form.bearerToken.trim()
  return {
    name,
    transport: form.transport,
    url,
    bearer_token: bearerToken || undefined,
  }
}
