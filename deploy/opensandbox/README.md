# OpenSandbox execution host

NexaFlow's API, database, Celery Worker and execution host are separate trust
boundaries. Do not give the business containers a Docker socket or run arbitrary
programs on the business host. The Worker talks to an authenticated OpenSandbox
control plane; each Workflow code job, artifact renderer, Skill script and stdio
MCP request gets a fresh sandbox with a native expiry and explicit destruction.

## Pinned runtime

- Server: `opensandbox-server==0.2.3`.
- Backend SDK: `opensandbox==0.1.16` (locked in `backend/uv.lock`).
- Bootstrap: `opensandbox/execd:v1.0.22`.
- Egress sidecar: `opensandbox/egress:v1.1.7`, **`dns+nft`** mode, IPv6 disabled.
- Build the execution image separately:

```bash
docker build -f deploy/dockerfiles/app.Dockerfile --target sandbox-runtime \
  -t nexaflow/execution:local .
```

The image includes Python, Node.js/npm/npx, the four fixed renderers and their
locked dependencies. Production must publish this image through the normal
authorized release process and use an immutable image digest. Skill uploads
cannot select an image, install requirements or mount a host directory. Bake
additional reviewed dependencies/MCP programs into a versioned execution image.

## Dedicated Linux host

Install Docker and configure the `kata-runtime` runtime on the **execution
host** first. The production configuration requires Kata; missing Kata fails
creation rather than falling back to runc. Keep the OpenSandbox control plane
private and authenticated. Its API key grants execution-host control, not a
workspace permission; never expose it to browsers, MCP children or Skill code.

Set `OPENSANDBOX_API_KEY` securely in the execution-host environment. Do not copy
the business `.env` to this host. Generate a private configuration (the script
does not start or deploy anything):

```bash
python3 deploy/opensandbox/configure.py --state-dir /var/lib/nexaflow-opensandbox
uv tool run --from opensandbox-server==0.2.3 opensandbox-server \
  --config /var/lib/nexaflow-opensandbox/server.toml
```

Use an operator-owned directory with mode `0700`; generated `server.toml` has
mode `0600` and is never overwritten. The server binds loopback by default.
Expose it to the business network through a private TLS reverse proxy/firewall,
including the server-proxy routes; do not expose raw sandbox ports publicly.
Persist its SQLite metadata directory across server restarts so native expiry
recovery can reconcile unfinished executions. No business mounts or inherited
business environment are configured.

On a developer machine without Kata, `configure.py --development` is an explicit
ordinary-Docker profile for functionality checks, **not production isolation**.
It retains network filtering and process limits. Kata behavior still requires a
separate Linux/Kata validation; local Docker checks do not establish VM isolation.
Normal source development should use `make dev` at the repository root. It creates
the private development configuration and key when missing, builds the execution
image, starts the control plane and supervises the application processes. Use the
manual commands above for a dedicated execution host or focused diagnostics.

## NexaFlow configuration

Set in the existing root `.env`:

```dotenv
OPENSANDBOX_URL=https://execution.internal.example
OPENSANDBOX_API_KEY=<same private control-plane key>
OPENSANDBOX_IMAGE=<immutable execution image digest>
OPENSANDBOX_EGRESS_DOMAINS=
```

The API/Worker must be able to reach this origin. Container `127.0.0.1` is not
the developer host: use a reachable private origin (for local Docker Desktop,
an explicitly bound development endpoint via `host.docker.internal`). Configure
the reverse proxy/listening address deliberately; do not bind the control plane
to all interfaces without network protection.

Python programs, renderers and imported Skill scripts have no external network.
For stdio MCP, the registration's `egress_domains` must be an exact subset of
`OPENSANDBOX_EGRESS_DOMAINS` (lowercase domain patterns, not URLs/IPs). Requests
always deny private, loopback ranges and metadata addresses. Guest-local
loopback remains usable for helper processes; it is not business-host loopback.
MCP receives only its encrypted registration environment, never business secrets.

`dns`-only upstream mode does not block direct IP access. The adapter reads the
effective sidecar policy and refuses execution **before staging code/secrets**
unless `dns+nft`, default-deny and the private-range denies are active. Validate
this on the chosen execution host; do not substitute DNS filtering or gVisor
for this tested networking profile. The upstream nft NAT profile currently
requires a compatible Linux network stack.

Cold creation, command execution and cleanup share the caller's overall deadline.
Set Agent/Workflow tool deadlines to accommodate a cold sandbox; pre-pull the
locked images on the execution host. Never silently retry uncertain MCP writes;
the unified invocation ledger records approval, idempotency and uncertainty.

## Validation

```bash
uv run --project sandbox python -m sandbox.tests
bash sandbox/run_coverage.sh
docker run --rm --network none --read-only --user 65532:65532 \
  --cap-drop ALL --security-opt no-new-privileges:true --memory 512m --pids-limit 96 \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m,mode=1777 \
  --entrypoint /opt/nexaflow/.venv/bin/python nexaflow/execution:local \
  -I /opt/nexaflow/self_check.py
cd backend
uv run python -m tests.execution.unit
uv run python -m tests.execution.opensandbox_smoke \
  --url http://127.0.0.1:8088 --image nexaflow/execution:local
```

The live smoke requires the control-plane key in the environment. It creates and
destroys only its tagged temporary sandboxes. Run it only against the intended
test server. Verify private/public/metadata rejection, read-only staged packages,
timeouts, output limits and native expiry/cancellation on the production runtime.
