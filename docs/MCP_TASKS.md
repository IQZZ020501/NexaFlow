# Durable MCP connector tasks

HTTP and legacy SSE sources can explicitly map one submitted job to four MCP tools: submit, status, result and cancel. This is a NexaFlow connector contract, not an implementation of native MCP protocol tasks. A remote `task_id` or annotation alone never enables it. stdio sources retain short request semantics.

The source creator configures the mapping in the source's **Long tasks** dialog. Other workspace users and administrators cannot change it. For example:

```json
{
  "contracts": {
    "report_submit": {
      "status_tool": "report_status",
      "result_tool": "report_result",
      "cancel_tool": "report_cancel",
      "poll_seconds": 2
    }
  }
}
```

The submit tool receives its normal business arguments and the stable request identity in `_meta["nexaflow/idempotencyKey"]`. It must create at most one job for that identity. Submit, status, result and cancel return structured content containing the same `request_id`, a stable nonempty `task_id`, and `status` (`queued`, `running`, `succeeded`, `failed` or `cancelled`). Result can include additional content and data.

Control tools accept exactly the lifecycle arguments below. Before a submit receipt is available, status and cancel must support lookup by request identity with a null `task_id`. Status and result must be read-only; cancel must be idempotent. A connector that cannot satisfy these requirements must not be enabled as a durable task.

```json
{"request_id": "stable-request-key", "task_id": null}
```

The mapping and controller definition hashes become part of the frozen submit tool version. Configuring or changing them requires the normal tool policy review. Missing controllers make submission unavailable. One approval authorizes the mapped job lifecycle; it does not authorize unrelated control tools or bypass current source, user, workspace, binding or policy checks.

One `tool_invocations` row still owns execution and the full result. `mcp_remote_tasks` stores only durable remote identity, frozen contract, deadline, progress and cancellation intent. NexaFlow commits `submitting` before dispatch. After a worker crash, both a saved receipt and a lost receipt resume by status lookup; an uncertain submit is never blindly repeated. Reattachment preserves the original deadline and does not consume another submission attempt. Agent tasks use the frozen Run deadline; individual HTTP requests keep their transport timeout. No database transaction stays open while waiting on the remote service.

Canceling the Run queues cancellation in the same transaction. Timeout, lost ownership or uncertain execution also preserves cleanup intent. Beat retries bounded, leased cancellation batches independently of the original worker. Cancel responses must confirm the same job and a terminal state. Deleting a source can make remote cancellation impossible: the retained row records an unconfirmed orphan, rather than claiming success. Disconnecting credentials immediately prevents local use and may leave cancellation waiting for valid credentials. Provider-side cancellation and idempotency remain connector requirements.

Creator routes are GET/PUT `/api/v1/workspaces/{workspace_id}/mcp-servers/{server_id}/long-tasks`. Configurations are limited to 16 mappings and polling intervals from 1 to 30 seconds. Ordinary MCP tools and old Run snapshots retain their existing behavior; old snapshots cannot dispatch a tool newly configured as a durable job.

Validation uses an actual local Streamable HTTP MCP server: completion and result replay, reattachment with/without a receipt, exhausted-attempt recovery, timeout cancellation, ownership checks, changed-policy rejection and missing-controller behavior. Run `cd backend && uv run python -m tests.tools.remote_tasks`. `tests.tools.remote_task_process` requires an explicitly isolated PostgreSQL URL in `NEXAFLOW_TEST_DATABASE_URL`; it kills a worker with SIGKILL after remote submission and confirms one job/one submit after a replacement worker finishes it. Production connector idempotency, result lookup and cancellation require separate compatibility checks.
