# Trusted extension contracts

`backend/packages/extension-api` is the independent `nexaflow-extension-api` package. It contains the existing `AgentExtension`, `AgentToolResult` and pause/busy/uncertain exceptions, with no third-party or application dependencies. Message and tool types are generic: the application host uses LangChain, while `examples/trusted_host.py` demonstrates a second host using ordinary strings.

The application imports the same classes through compatibility facades. Identity checks, exception handling and existing extension constructors continue to work. `ExtensionRuntime` remains in the application: it checks the API major, rejects duplicate names, runs context/before/after hooks and exposes tools through the existing capability registry. Schema validation, authorization, approvals, immutable snapshots, budgets, execution and the unified tool ledger remain host responsibilities.

Contract major `API_VERSION = 1` and distribution version `1.0.0` are distinct from an extension's own `version`. Existing constructors default to API major 1. A host must call `require_api_version` before registration; unsupported majors are rejected before hooks run. Breaking public contract changes require a new major and an explicit host compatibility change. The backend dependency is bounded to `<2.0.0`, installed from the checked-in local package and included in the application image.

Only deployment-owned trusted code may register extensions. This package provides no upload, discovery, auto-installation, dynamic import, marketplace or permission grant. Hooks execute in the host process and therefore have its trust level. User Skill scripts and MCP tools keep their existing isolated execution and authorization models. Autonomous subagents are outside this change.

Validation:

```sh
cd backend
uv run python -m tests.agents.extensions
uv run python -m tests.agents.harness
uv build packages/extension-api --out-dir /tmp/nexaflow-extension-dist
```

Install the produced wheel into a fresh virtual environment, then run `packages/extension-api/examples/trusted_host.py` with `python -I`. That verifies installation and operation without the backend source or LangChain. The contract test checks standard-library-only imports, class identity, incompatible versions, exception compatibility and host hook behavior. No package is published by this workflow.
