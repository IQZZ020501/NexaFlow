# Execution host placement

The default Compose deployment remains one OpenSandbox control plane and one execution host. Optional `OPENSANDBOX_HOSTS` configures up to sixteen operator-owned control-plane origins. It does not scale the combined `app` container, add another Beat or change the execution port. Each origin must represent an independent capacity domain; two URLs for the same underlying host would double-count its capacity and must not be registered.

Example advanced process configuration:

```json
[
  {"id":"east","url":"https://execution-east.example.com","api_key_env":"EXECUTION_EAST_KEY","max_sandboxes":4,"memory_budget_mib":4096,"cpu_budget":4},
  {"id":"west","url":"https://execution-west.example.com","api_key_env":"EXECUTION_WEST_KEY","max_sandboxes":4,"memory_budget_mib":4096,"cpu_budget":4}
]
```

The JSON contains credential environment references, not keys. Supply those variables privately to every API/Worker process that uses the execution plane. In Compose, explicitly add the catalog and referenced variables to the backend process environment; the root local-development `.env` is not automatically injected into deployment containers. Keep the same catalog across workers. The frontend receives none of these values. HTTP remains subject to the existing production TLS policy. Resource values above are illustrative limits, not calibrated capacity recommendations.

The first actual guest request chooses a host with low reserved occupancy and atomically admits the Run's complete resource bundle. PostgreSQL serializes host placement and persists it before any guest creation. Redis enforces host guest/CPU/memory limits, workspace round-robin admission and shared workspace/consumer quotas across all hosts. A Run's code guest and its single concurrent stdio guest use the same host. The native guest TTL remains the Run deadline plus sixty seconds.

`execution_placements` records the selected host, control-plane fingerprint, frozen non-secret execution profile, resources and expiry. `execution_sessions` records the same host binding for each guest. The profile freezes the catalog, image and network policy, while credential rotation does not alter it. Reconnection, export reads and cleanup use the original host. Reusing a host ID for another origin is rejected. The adapter's in-memory capacity handles and orphan reconciliation are scoped to that control plane.

An unavailable or removed host cannot cause an existing Run to execute elsewhere. Unknown creates retain their reservation until confirmed cleanup or native expiry. A failed request never establishes that an external guest or command did not exist. This is explicit static placement with recovery, not transparent host failover or automatic host discovery. New-host health checks and live migration are not provided. Drain active Runs and guests before changing the host catalog or enabling it over a legacy single-host installation. Legacy rows without a host fingerprint are not guessed onto a fleet host.

Ephemeral jobs also persist creation reservations, including in single-host deployments. Redis loss reconstructs those reservations before admission. Confirmed destruction releases the ledger entry; uncertain creation keeps it until native TTL. Released ephemeral entries are pruned after one day. A capacity release sends a debounced Celery wake notification to the original waiting Runs/invocations. The wake does not reserve capacity, reset attempt/deadline budgets or bypass leases; the existing periodic recovery covers missed notifications. Cancellation removes obsolete queue entries.

Warm pools must remain disabled in fleet mode. Single-host warm-pool behavior is unchanged. CPU/memory profiles remain provisional, especially for Kata. Physical host failure, storage reliability and production load require deployment-specific validation; two local control planes do not establish those properties.

## Validation

Redis and SQL suites cover sticky host placement, shared quotas, reconstruction after Redis loss, uncertain creation, cancellation and release notifications. `tests.execution.placement_smoke` additionally exercises real guests on two isolated OpenSandbox control planes, including reconnecting to the original host after a control-plane interruption. Local control planes do not establish physical multi-host reliability, Kata isolation or calibrated capacity.

Run Redis checks only against an explicitly isolated test instance:

```sh
cd backend
NEXAFLOW_TEST_REDIS_URL=redis://127.0.0.1:6379/15 uv run python -m tests.execution.reservations
NEXAFLOW_TEST_REDIS_URL=redis://127.0.0.1:6379/15 uv run python -m tests.execution.placement
NEXAFLOW_TEST_REDIS_URL=redis://127.0.0.1:6379/15 uv run python -m tests.execution.admissions
NEXAFLOW_TEST_REDIS_URL=redis://127.0.0.1:6379/15 uv run python -m tests.execution.load
uv run python -m tests.execution.wakeup
```

The PostgreSQL concurrency suite additionally requires `NEXAFLOW_TEST_DATABASE_URL=postgresql+psycopg://...` pointing at a separately migrated disposable database. Run it with `uv run python -m tests.execution.placement_postgres`; it creates and removes its own fixture rows. Never point these checks at business PostgreSQL or Redis.

Migration `202611160006` adds host binding and reservation records. Stop execution before downgrading; removing these records while guests remain can discard their accounting and cleanup identity.
