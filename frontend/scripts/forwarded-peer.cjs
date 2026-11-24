// Next rewrites preserve incoming forwarding headers. Establish the client
// address from the HTTP socket before Next or its proxy handles the request.
const { channel } = require("node:diagnostics_channel")
const { isIP } = require("node:net")

function canonicalAddress(value) {
  if (typeof value !== "string" || !isIP(value)) return undefined
  if (value.startsWith("::ffff:") && isIP(value.slice(7)) === 4) {
    return value.slice(7)
  }
  return value
}

const trustedProxy = canonicalAddress(process.env.NEXAFLOW_TRUSTED_PROXY_IP)

channel("http.server.request.start").subscribe(({ request, socket }) => {
  const peer = canonicalAddress(socket.remoteAddress)
  // An explicitly trusted ingress must overwrite X-Forwarded-For with a
  // single address. Ignore lists, duplicates and invalid values.
  const reported = canonicalAddress(request.headers["x-forwarded-for"])
  if (peer) {
    request.headers["x-forwarded-for"] =
      trustedProxy === peer && reported ? reported : peer
  } else {
    delete request.headers["x-forwarded-for"]
  }
})

// Next's rewrite proxy and request handlers can log full target/request URLs or
// upstream error payloads containing signed download, invitation, or OAuth
// credentials. Keep error classification, codes, and stack frames without raw
// URLs or untrusted error messages.
const ANSI_ESCAPE = /\x1b\[[0-9;]*m/g
const SAFE_CODE = /^[A-Z0-9_]+$/
const URL_OR_QUERY = /(?:https?:\/\/[^\s'"]+)|(?:\/[^\s'"]*\?[^\s'"]*)/g

function safeErrorCode(value) {
  const code = value && typeof value === "object" ? value.code : undefined
  return typeof code === "string" && SAFE_CODE.test(code) ? code : undefined
}

function sanitizeErrorObject(err) {
  const name =
    typeof err.name === "string" && /^[A-Za-z0-9_]+$/.test(err.name)
      ? err.name
      : "Error"
  const code = safeErrorCode(err)
  const header = code ? `${name} [${code}]` : name
  if (typeof err.stack !== "string") return header
  const frames = err.stack
    .split("\n")
    .filter((line) => /^\s+at\s/.test(line))
    .slice(0, 12)
  return frames.length ? `${header}\n${frames.join("\n")}` : header
}

function sanitizeLogArg(arg) {
  if (arg instanceof Error) {
    return sanitizeErrorObject(arg)
  }
  if (typeof arg === "string") {
    return arg.replace(URL_OR_QUERY, "<redacted-url>")
  }
  return arg
}

const originalError = console.error.bind(console)
console.error = (...args) => {
  if (typeof args[0] === "string") {
    const plain = args[0].replace(ANSI_ESCAPE, "")
    if (plain.includes("Failed to proxy ")) {
      originalError("API proxy request failed.", safeErrorCode(args[1]) || "UPSTREAM_ERROR")
      return
    }
    if (plain.includes("Failed to handle request for ")) {
      originalError("Frontend request failed.", safeErrorCode(args[1]) || "REQUEST_ERROR")
      return
    }
    if (plain.includes("Error handling upgrade request")) {
      originalError("Upgrade request failed.", safeErrorCode(args[1]) || "UPGRADE_ERROR")
      return
    }
  }
  originalError(...args.map(sanitizeLogArg))
}
