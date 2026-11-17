# NexaFlow extension API

An installable, standard-library-only contract for code-owned, trusted Agent
extensions. It does not load extension code, authorize capabilities, execute
tools or persist state. NexaFlow's host retains those responsibilities.

`AgentExtension` is generic over the host's message and tool types. The built-in
host uses LangChain messages and `StructuredTool`; independent hosts need not
install LangChain or the NexaFlow application. `AgentToolResult` and execution
pause exceptions keep the same identity through the application's compatibility
imports.

The package version is `1.0.0`; the contract major is `API_VERSION = 1`.
Extensions declare `api_version` (default 1 for existing integrations). Hosts
call `require_api_version` before registration and reject unsupported majors.
An extension's `version` identifies its own release and is independent of the
contract version. Breaking public contract changes require a new major.

Install locally with `python -m pip install .`. Run
`python examples/trusted_host.py` for a second, framework-free host. See the
repository's `docs/EXTENSIONS.md` for the application integration boundary.
