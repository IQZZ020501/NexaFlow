# OpenSandbox execution host

NexaFlow's API, database, Celery Worker and execution host are separate trust
boundaries. Do not give the business containers a Docker socket or run arbitrary
programs on the business host. The Worker talks to an authenticated OpenSandbox
control plane. Python tools, Workflow code, artifact renderers, Skill scripts
and bash commands reuse a database-backed Run-private sandbox so
approved dependencies survive subsequent script calls; it is explicitly destroyed
when the Run reaches a terminal state and still has a native expiry as fallback.

## Pinned runtime

- Server: `opensandbox-server==0.2.3`.
- Backend SDK: `opensandbox==0.1.16` (locked in `backend/uv.lock`).
- Bootstrap: `opensandbox/execd:v1.0.22`.
- Egress sidecar: `opensandbox/egress:v1.1.7`, **`dns+nft`** mode, IPv6 disabled.
- Build the execution image separately from the business image:

```bash
docker build -f deploy/dockerfiles/sandbox.Dockerfile \
  -t nexaflow/execution:local .
```

The image includes Python, Node.js/npm/npx, the four fixed renderers and their
locked dependencies. It is a standalone image: build, publish, pull, and pin it
independently of the NexaFlow business image. OpenSandbox creates short-lived
execution containers from this image; the API and Worker never run its code
locally and never mount business data into it. Production must publish this image
through the normal authorized release process and use an immutable image digest.
Skill uploads cannot select an image, mount a host directory, provide setup
commands or execute `requirements.txt`/`package.json` installation. An Agent may
request exact-version PyPI or npm packages through the built-in dependency
installer. Every request is recorded in the unified Tool ledger and requires user
approval; Python source builds and npm lifecycle scripts are disabled. Bake fixed
renderer dependencies and reviewed MCP programs into a versioned execution image.

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
OPENSANDBOX_MAX_SANDBOXES=20
OPENSANDBOX_MAX_SANDBOXES_PER_CONSUMER=2
OPENSANDBOX_MAX_SANDBOXES_PER_WORKSPACE=2
ARTIFACT_SANDBOX_TIMEOUT_SECONDS=30
```

Production requires `OPENSANDBOX_MAX_SANDBOXES` to be a positive host limit and
`OPENSANDBOX_URL` to use `https`: the control-plane key travels with every
request. A loopback control plane may opt out of TLS with
`OPENSANDBOX_ALLOW_INSECURE_HTTP=1`.

The API/Worker must be able to reach this origin. Container `127.0.0.1` is not
the developer host: use a reachable private origin (for local Docker Desktop,
an explicitly bound development endpoint via `host.docker.internal`). Configure
the reverse proxy/listening address deliberately; do not bind the control plane
to all interfaces without network protection.

Python programs, renderers and imported Skill scripts have no external network.
The approval-backed Skill installer temporarily enables only its required package
registry domains, and restores default-deny before any Skill script runs. Enable
`pypi.org,files.pythonhosted.org` for Python installs and/or `registry.npmjs.org`
for Node installs in `OPENSANDBOX_EGRESS_DOMAINS`; leaving them out disables that
installer. For stdio MCP, the registration's `egress_domains` must be an exact
subset of the same deployment allowlist (lowercase domain patterns, not URLs/IPs).
Requests always deny private, loopback ranges and metadata addresses. Guest-local
loopback remains usable for helper processes; it is not business-host loopback.
MCP receives only its encrypted registration environment, never business secrets.

`dns`-only upstream mode does not block direct IP access. The adapter reads the
effective sidecar policy and refuses execution **before staging code/secrets**
unless `dns+nft`, default-deny and the private-range denies are active. Validate
this on the chosen execution host; do not substitute DNS filtering or gVisor
for this tested networking profile. The upstream nft NAT profile currently
requires a compatible Linux network stack.

The adapter reconciles the guest's allow list before each command: a rule left
behind by a worker that died is removed, and a missing rule is granted. A
leftover rule therefore no longer costs the Run its workspace, and the guest
still holds exactly the requested egress while the command runs.

Cold creation, command execution and cleanup share the caller's overall deadline.
Set Agent/Workflow tool deadlines to accommodate a cold sandbox; pre-pull the
locked images on the execution host. Before command dispatch, a timeout is a
confirmed failure. Once dispatched, a missing response is recorded as `uncertain`
in the unified Tool ledger, including when the outer Tool deadline expires.
Cleanup cannot replace a confirmed result, and an unconfirmed destroy retains
its capacity reservation until reconciliation or native expiry. Never silently
retry uncertain execution or MCP writes.

Set `OPENSANDBOX_MAX_SANDBOXES` in the business `.env` to the number of live
sandboxes this host can carry. Workers reserve a slot in Redis before creating a
sandbox and free it after a confirmed destroy; a slot left by a crashed worker
expires with the sandbox's native TTL. A request that finds no slot within five
seconds is requeued with its Run instead of failing, and nothing is created
while Redis is unavailable.

Capacity is booked on three dimensions: the deployment-wide host limit, the
external consumer of a public or API Run
(`OPENSANDBOX_MAX_SANDBOXES_PER_CONSUMER`) and the workspace that owns the Run
(`OPENSANDBOX_MAX_SANDBOXES_PER_WORKSPACE`). The workspace bound applies to
console Runs as well, so one tenant cannot occupy the whole deployment.
`0` for the host limit keeps the previous unbounded behaviour and no Redis
dependency; production rejects it. A warm pool without a host limit is rejected
as well, because it would bypass capacity accounting entirely.

`OPENSANDBOX_WARM_POOL_SIZE` defaults to `0`. When enabled, the SDK's Redis-backed
pools share a deployment-wide idle quota across small/standard/heavy resources.
Each guest passes dns+nft verification before entering the pool and receives Run
labels on acquisition. Set the host limit above the pool size: on-demand capacity
is `OPENSANDBOX_MAX_SANDBOXES - OPENSANDBOX_WARM_POOL_SIZE`.

`execution_sessions` persists sandbox IDs, staged packages, dependency locks and
short command leases. A worker reconnects by ID; the command watchdog renews the
15-second holder every two seconds and checks the Run worker identity. On stale
takeover it stops the previous command's processes before starting work. Native
TTL follows the Run deadline plus 60 seconds. Terminal/cancelled Runs close their
guests; minute-level maintenance recovers expired, orphaned and pending cleanup.
Standalone Tool tests and stdio discovery keep using ephemeral guests. Within a
Run each stdio registration uses a separate authenticated Streamable HTTP bridge;
the service starts once and closes with the MCP session or after 60 seconds idle.

`OPENSANDBOX_WARM_POOL_SIZE` defaults to `0`. When enabled, the SDK's Redis-backed
pools share a deployment-wide idle quota across small/standard/heavy resources.
Each guest passes dns+nft verification before entering the pool and receives Run
labels on acquisition. Set the host limit above the pool size: on-demand capacity
is `OPENSANDBOX_MAX_SANDBOXES - OPENSANDBOX_WARM_POOL_SIZE`. Public/API consumers
also share a two-guest limit, including their stdio hosts.

New Agent Runs automatically include bash, hidden from Tool catalogs and manual
bindings, and default to 24 turns, 64 tool calls and 900 seconds;
`AGENT_SHELL_MAX_TURNS`, `AGENT_SHELL_MAX_TOOL_CALLS` and
`AGENT_SHELL_RUN_TIMEOUT_SECONDS` are advanced deployment overrides. A command
may run for 1–300 seconds, returns nonzero exits/timeouts as ordinary results,
and streams up to eight generated files of 5 MiB each. Its trusted supervisor
stays root inside the guest to stop all UID 65532 processes after the command;
the model's shell and all of its descendants run as UID 65532. Authorized Skills
are root-owned read-only files under `/skills/`.

Guest storage is bounded inside the guest: the shell workspace is capped at
512 MiB and 20 000 files, and a program that keeps growing it is stopped with
exit code 125 instead of filling the execution host. A Python or Skill job may
write at most 256 MiB and 8 192 files in its temporary directory. Export
directories are reclaimed once they fall outside a small retention window. The
execution host must still carry a filesystem quota for the guest data root:
these bounds limit one guest, not the host.

Resource sizes are provisional: small = 1 CPU / 512 MiB, standard = 1 CPU / 1 GiB,
heavy = 2 CPU / 2 GiB. A shared Run guest uses the largest profile required by
its frozen tools/Skills; standalone jobs select by task type. Production Kata
cold-start, memory and concurrency measurements remain pending. Local runc
functional validation does not establish those production characteristics.

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
Add `--redis-url redis://127.0.0.1:<test-port>/0` only for an explicit isolated
Redis instance to test the SDK warm pool, deducted host capacity and visitor
limits. The smoke uses an isolated SQLite Run store rather than the business DB.

For the remaining Tools redesign, run the phase-zero probe **on an isolated
execution host** with the locked execution, execd and egress images already
available. Set `OPENSANDBOX_URL`, `OPENSANDBOX_IMAGE`, `OPENSANDBOX_API_KEY` and
`OPENSANDBOX_PROBE_REDIS_URL` in the host's private environment, then run from
`backend/`:

```bash
uv run python -m tests.execution.opensandbox_probe \
  --url "$OPENSANDBOX_URL" --image "$OPENSANDBOX_IMAGE" \
  > /tmp/nexaflow-tools-phase0.json
```

The probe reads no business `.env` or database. It checks the sandbox's actual
Docker runtime before staging code, verifies effective dns+nft policy, measures
creation and the first command, reconnects by ID, renews, tests metadata filters
and filesystem writes, streams through the server proxy for 70 seconds, and
tests two SDK pool clients sharing a private Redis namespace. It cleans up only
its tagged sandboxes and Redis namespace and emits JSON without credentials.
`--allow-development` explicitly enables ordinary Docker functionality checks;
these reports always keep `phase_zero_complete=false`.

Server 0.2.3 strips `Authorization` and the control-plane API key from proxied
requests. Guest bridge authentication must use an application header such as
`X-NexaFlow-MCP-Token: Bearer <token>`, which the probe tests. Newly generated
server configuration caps sandbox TTL at 1860 seconds, covering
the maximum 1800-second Run budget plus 60 seconds. SDK pools explicitly use a
240-second idle timeout rather than the 24-hour default. Existing execution-host
configuration is operator-managed and is never rewritten automatically: raise
its TTL limit before enabling the longer shell budgets.
