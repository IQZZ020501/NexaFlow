const assert = require("node:assert/strict")
const { spawn } = require("node:child_process")
const http = require("node:http")
const path = require("node:path")
const { once } = require("node:events")
const { createInterface } = require("node:readline")
const { test } = require("node:test")

// Use Next's real rewrite proxy in a preloaded child. The upstream stays in
// this process so its incoming headers aren't normalized a second time.
async function fixture(t, trustedProxy = "") {
  const upstream = http.createServer((req, res) => {
    res.end(JSON.stringify({ client: req.headers["x-forwarded-for"] }))
  })
  upstream.listen(0, "127.0.0.1")
  await once(upstream, "listening")
  const child = spawn(process.execPath, [
    "--require", path.join(__dirname, "forwarded-peer.cjs"), "-e",
    `const http = require("node:http")
     const { parse } = require("node:url")
     const { proxyRequest } = require("next/dist/server/lib/router-utils/proxy-request")
     const server = http.createServer((req, res) => {
       if (req.url && req.url.startsWith("/simulate-handler-error")) {
         console.error("\\x1b[31m\\x1b[1m⨯\\x1b[22m\\x1b[39m Failed to handle request for " + req.url)
         const err = Object.assign(new Error("Failure for http://127.0.0.1:8000" + req.url), { code: "ECONNRESET" })
         console.error(err)
         res.statusCode = 500
         res.end("Internal Server Error")
         return
       }
       proxyRequest(req, res, parse(process.env.FIXTURE_UPSTREAM + req.url, true)).catch((err) => {
         // Mirror Next.js router-server.js secondary console.error(err)
         console.error(err)
       })
     })
     server.listen(0, "::", () => console.log(server.address().port))`,
  ], {
    cwd: path.join(__dirname, ".."),
    env: {
      ...process.env,
      NEXAFLOW_TRUSTED_PROXY_IP: trustedProxy,
      FIXTURE_UPSTREAM: `http://127.0.0.1:${upstream.address().port}`,
    },
    stdio: ["ignore", "pipe", "pipe"],
  })
  let errors = ""
  child.stderr.on("data", (data) => { errors = (errors + data).slice(-16384) })
  t.after(async () => {
    const exited = once(child, "exit")
    child.kill()
    await exited
    upstream.closeAllConnections()
    await new Promise((resolve) => upstream.close(resolve))
  })
  const lines = createInterface({ input: child.stdout })
  const [line] = await once(lines, "line")
  lines.close()
  const port = Number(line)
  assert.ok(port > 0, errors)
  return { port, upstream, errors: () => errors }
}

async function request(port, headers = {}, host = "127.0.0.1", route = "/api/test") {
  return new Promise((resolve, reject) => {
    const req = http.get({ host, port, path: route, headers }, (res) => {
      let data = ""
      res.setEncoding("utf8")
      res.on("data", (chunk) => { data += chunk })
      res.on("end", () => resolve({ status: res.statusCode, data }))
    })
    req.on("error", reject)
  })
}

test("direct callers cannot spoof the address and distinct peers stay distinct", { timeout: 10000 }, async (t) => {
  const { port } = await fixture(t)
  const ipv4 = await request(port, { "x-forwarded-for": "203.0.113.10" })
  assert.equal(ipv4.status, 200)
  assert.equal(JSON.parse(ipv4.data).client, "127.0.0.1")
  const ipv6 = await request(port, { "x-forwarded-for": "203.0.113.10" }, "::1")
  assert.equal(JSON.parse(ipv6.data).client, "::1")
})

test("only an explicitly trusted peer can supply one valid address", { timeout: 10000 }, async (t) => {
  const { port } = await fixture(t, "127.0.0.1")
  const valid = await request(port, { "x-forwarded-for": "203.0.113.10" })
  assert.equal(JSON.parse(valid.data).client, "203.0.113.10")
  for (const value of ["203.0.113.10, 203.0.113.11", ["203.0.113.10", "203.0.113.11"], "invalid"]) {
    const response = await request(port, { "x-forwarded-for": value })
    assert.equal(JSON.parse(response.data).client, "127.0.0.1")
  }
  const otherPeer = await request(port, { "x-forwarded-for": "203.0.113.10" }, "::1")
  assert.equal(JSON.parse(otherPeer.data).client, "::1")
})

test("upstream failure and subsequent handler error logs omit signed paths and query values", { timeout: 10000 }, async (t) => {
  const { port, upstream, errors } = await fixture(t)
  await new Promise((resolve) => upstream.close(resolve))
  const marker = "synthetic-credential-marker"
  const response = await request(port, {}, "127.0.0.1", `/api/artifacts/${marker}?code=${marker}`)
  assert.equal(response.status, 500)
  const secondary = await request(port, {}, "127.0.0.1", `/simulate-handler-error/${marker}?token=${marker}`)
  assert.equal(secondary.status, 500)
  assert.match(errors(), /API proxy request failed/)
  assert.match(errors(), /Frontend request failed/)
  assert.match(errors(), /Error \[ECONNRESET\]/)
  assert.ok(!errors().includes(marker), errors())
})
