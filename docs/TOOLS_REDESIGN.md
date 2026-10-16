# 工具运行时重新设计：沙箱、MCP、Skill 与 bash

状态（2026-10-14）：用户暂缓 Kata 测试环境后，A–F 已实现并通过本地回归与隔离 OpenSandbox 功能验证；G 的三档选择已接入，规格暂定。Kata 冷启动、VM 隔离与生产资源校准仍待有执行主机后补验。

## 背景

Agent 的工具执行涉及三类能力：

- 沙箱代码：Workflow 代码节点、Python Tool、生成文件、四个固定渲染器、工作区 Skill 脚本。
- MCP：远程 Streamable HTTP / legacy SSE，以及跑在沙箱里的 stdio。
- Skill：工作区上传的 SKILL.md 包，经 `load_skill` / `read_skill_file` / `run_skill_script` 使用。

### 现状问题

以下记录重设计前的问题；当前实现与验证结果见“剩余工作的实施计划”。

沙箱：

- 按调用冷启动。没有 `execution_session` 的请求每次都创建沙箱、等待就绪（最长 30 秒）、校验 dns+nft 策略、上传、执行、读回、销毁（`backend/app/adapters/execution/opensandbox.py:68`）。除 Skill 脚本外的所有沙箱任务都走这条路，耗时计入工具调用的硬超时（默认 30 秒）。
- Run 会话只存在于进程内存。`OpenSandboxExecution._sessions` 是类变量（`opensandbox.py:50`）。审批暂停后恢复、租约接管、多个 `agent-worker` 副本都会让 Run 换进程：会话丢失，依赖要重新下载。旧沙箱只在 Run 终态时关闭（`backend/app/application/agents/runs/executor.py:1171`），否则等 TTL（Run 超时 + 60 秒）回收，等待审批超过这个时长也会让沙箱过期。
- 每次 Skill 脚本调用都重新上传整个包，并把本 Run 已装的每组依赖逐个重放一次（`backend/app/application/agent_skills/scripts.py:95`）。
- 资源规格固定为 1 CPU / 512Mi（`opensandbox.py:210`）。
- 没有容量控制。`sandbox_busy` → `ToolAdapterBusy` 的重排队路径是死代码：只有 `backend/app/infra/sandbox/client.py:121` 判断这个值，`sandbox/job.py` 从不返回它。

MCP：

- 远程 MCP 每次调用都新建 HTTP 客户端，重新做 DNS 校验、TLS 和 `initialize` 握手（`backend/app/adapters/mcp/client.py:176`）。同一 Run 内不复用，服务端会话状态无法跨调用保持。
- stdio MCP 每次 discover / call 都新建沙箱、启动服务进程、握手、调用、销毁（`client.py:381`、`sandbox/job.py:158`），全部受 30 秒限制。
- 失败归类过粗。任何 `McpClientError` 都让写类工具记为 uncertain（`backend/app/application/tools/runtime/adapters/mcp.py:48`），包括请求根本没发出（DNS 失败）和远端已执行但结果超长两种情况。

Skill：

- 固定渲染器（documents / pdf / pptx / spreadsheets）与工作区 SKILL.md 包共用 "Skill" 一词，契约不同。
- 使用一个工作区 Skill 需要多轮模型调用：`load_skill` →（工具多时）`activate_tools` → `run_skill_script` → 缺包时 `install_skill_dependencies`（每次审批）→ 重试。
- 只能执行包内的 `.py` / `.js`（`scripts.py:70`、`job.py:353`），没有 shell。

## 决策（2026-10-13）

- 做：Run 级持久沙箱、预热池与容量控制；MCP 连接化；bash 工具，对控制台、公开链接、API 访问都开放。
- 补充决策（2026-10-15）：bash 是 Agent 默认内置的基础能力，创建 Run 时自动注入，不在工具目录、工具选择器或 Agent 手动绑定列表里展示；控制台保留命令执行过程。
- 暂不做：Skill 发布时自动构建依赖（以及由谁批准依赖）；运行时经内网包镜像临时装包。现有逐次审批的 `install_skill_dependencies` 保持不变。
- 安全边界不变：Kata 虚机；写入代码前校验 dns+nft 默认拒绝已生效；拒绝私网、回环与元数据地址；不注入业务密钥、不挂载业务数据；UID 65532 执行；Run 冻结镜像与网络指纹；所有工具执行写入 `tool_invocations` 账本。

## 非目标

- bash 出网：bash 命令永远不能申请出网域名。
- Workflow 的 bash 节点。
- 依赖缓存（快照或包镜像）。

## 目标设计

### 1. 执行会话

- 新表 `execution_sessions`：`id`、`workspace_id`、`run_id`、`purpose`（`run` / `mcp`）、`owner_key`（MCP 会话为服务注册版本）、`sandbox_id`、`image`、执行指纹、`state`（creating / ready / closing / closed）、`expires_at`、`last_used_at`、已上传的 Skill 版本哈希、已安装依赖（`bootstrap_id` → `environment_hash`）。空闲预热沙箱由 SDK 池管理。
- 任何 worker 都通过 SDK 的 `Sandbox.connect(sandbox_id)` 接回同一台沙箱（锁定版本已提供，`opensandbox/sandbox.py:672`）。会话内的命令用数据库行锁或短租约串行，不再依赖进程内的 `asyncio.Lock`。进程内只缓存连接句柄，失效时重新 connect。
- 归属：
  - 一个 Agent Run 内的 Skill 脚本、Python Tool、生成文件、固定渲染器和 bash 共用一台 `run` 会话；Workflow Run 同理。
  - Tool 测试仍用一次性沙箱。
  - stdio MCP 使用独立的 `mcp` 会话，不与模型代码共用虚机，因为它持有注册时配置的密钥。
- 生命周期：
  - Run 进入终态时关闭。
  - Run 暂停（等待审批或输入）时保留；接回时按 Run 当前截止时间续期。
  - Beat 回收已终态、已过期、找不到对应 Run 的会话，并按 metadata 标签清扫遗留沙箱。
  - 沙箱丢失时自动重建，并在工具结果里告诉模型"工作区已重置"。
- 依赖：会话记录了已安装的环境哈希，同一台沙箱上不再重放；只有重建后才按账本重放（保留 `scripts.py` 现有的重放逻辑作为重建路径）。
- 镜像校验：接回会话时核对会话记录的执行指纹与 Run 冻结的一致，不一致就重建，沿用 `require_execution_profile` 的失败关闭语义。

### 2. 预热池与容量控制

- 预热池：使用 OpenSandbox SDK 自带的 `SandboxPoolAsync` + `AsyncRedisPoolStateStore`（锁定版本已包含），不自己实现。它在 Redis 里记录空闲沙箱、用主锁保证只有一个进程负责补池，`acquire()` 拿不到空闲沙箱时直接新建，取出的沙箱不会回池，正好满足"用过即毁"。按（镜像、资源档位）各建一个池，新配置 `OPENSANDBOX_WARM_POOL_SIZE` 默认为 0，即关闭。
- 容量：按执行主机承载能力设全局并发上限（Redis 租约信号量，新配置 `OPENSANDBOX_MAX_SANDBOXES`）。满了抛 busy，接入 `ToolAdapterBusy` 现有的重排队逻辑（`backend/app/application/tools/runtime/service.py:248`），同时删掉死掉的 `sandbox_busy` 分支。外部访问另设每个消费方的沙箱并发上限。
- 资源档位：small（代码节点、Python Tool）、standard（Skill 脚本、bash）、heavy（PPTX 等渲染、依赖安装），由适配器按任务类型选择。档位不是安全属性，重试时换档无害，因此不进入执行指纹。

### 3. bash 工具

- 内置 Tool `bash`：
  - 参数：`command`（不超过 8 KiB），可选 `timeout_seconds`（不超过 300，默认 60），有效超时受 Run 剩余时间约束。
  - 策略：`effect = pure`，`approval = auto`，`allowed_access_sources = console / public / api`，与 `run_skill_script` 一致（`backend/app/domain/tools/catalog/service.py:1633`）。`always_ask` 模式下 `pure` 工具不需要审批（`backend/app/domain/agents/approval.py:37`），其他模式按 `approval = auto` 同样不审批。
- 接入方式：创建 Agent Run 时自动解析并冻结工作区内置 bash 的版本与策略，无需绑定或新增开关。目录列表在分页前过滤，前端工具选择器同步隐藏；已有手动绑定在读取时隐藏、保存时移除。发布配置只保留可配置工具，实际 Run 快照包含 bash，重试和恢复仍使用冻结版本。
- 工作区布局（Run 会话内）：
  - `/workspace`：可写，工作目录跨命令保持。
  - `/skills/<名称>/`：Run 已授权的 Skill 版本，创建会话时上传，只读。
  - `/workspace/outputs/`：命令结束后，这里的新文件登记为生成物，沿用单文件 5 MiB 上限。
- 网络始终默认拒绝。
- 输出：stdout 与 stderr 合计最多 30 KiB 返回给模型，超出部分截断并标注。命令结束时杀掉整个进程组并清理该用户的所有进程，不保留后台进程。
- 每条命令是一次 ToolInvocation。worker 崩溃时记为失败，模型可以重试：影响只在沙箱内，不会出现 uncertain。
- 外部访问：
  - 事件投影沿用现有规则，访客看不到命令和输出，只能看到模型回答和生成物。
  - 由现有的 Agent 总量与消费方限流、新增的每消费方沙箱并发上限、单命令超时共同约束。
- 预算：命令计入 Run 的工具调用次数。新建 Agent Run 自动包含 bash，因此默认使用"命令行档"预算（部署级配置，默认 24 轮、64 次工具调用、900 秒），上限仍受 `max_turns <= 64`、`max_tool_calls <= 128`、`AGENT_RUN_TIMEOUT_SECONDS <= 1800` 约束。已有 Run 不重置冻结预算。按 Agent 单独设置预算留作后续。
- 依赖：由于暂不做发布时构建，API 访问没有审批路径，bash 和 Skill 脚本只能使用执行镜像内置的包；控制台和公开链接仍可走现有的审批安装。常用包需要预装进执行镜像。
- 与 Skill 的关系：
  - Skill 可以包含 `.sh` 脚本，模型通过默认 bash 能力执行 `bash /skills/x/scripts/run.sh` 或 `python /skills/x/scripts/a.py`。
  - `run_skill_script` 保留，提供有参数约束的脚本执行入口，并兼容没有 bash 快照的历史 Run。
  - `load_skill` 保留，负责授权检查和版本锁定。
- `sandbox/job.py` 新增命令执行模式，与依赖安装使用的 `shell` 字段区分开；沿用现有的 rlimit 限制和进程组清理。

### 4. MCP 连接化

- 远程 MCP：
  - 按（`run_id`、服务 ID、凭据版本）缓存会话，首次调用时建立，Run 结束或空闲 60 秒后关闭；不跨 Run 共享。
  - MCP SDK 基于 anyio，客户端必须在同一个任务内进入和退出。因此每个连接由一个常驻的属主任务持有，工具调用通过队列把请求交给它。
  - 缓存放在进程内即可：丢失只是重连一次。
  - 每次建连都做 DNS 校验，沿用固定解析地址的传输层。
- stdio MCP：
  - 在 `mcp` 会话沙箱里常驻 `mcp_bridge.py` 桥接进程：stdio 服务只启动一次，并在沙箱内端口上以 Streamable HTTP 暴露。
  - worker 经 OpenSandbox 服务端代理连接（与读取网络策略的代理是同一机制，`opensandbox.py:365`），之后与远程 MCP 走同一条客户端路径。
  - 会话粒度为"注册版本 × Run"。
  - MCP 服务程序预装进执行镜像，调用时不再用 npx 现场下载。
- 按失败阶段归类：
  - 连接或握手阶段失败：confirmed，请求没有执行。
  - 请求发出后失败：写类工具记为 uncertain。
  - 结果超过 20,000 字符：截断、加标记，按成功处理。
  - MCP 返回的 `isError` 文本内容限长后交给模型。

### 5. Skill 命名与轮次

- 四个固定渲染器保留 Tool 形态，只改前端展示名为按产物命名（生成 Word / PDF / PPT / Excel）。前端已经按 `function_name` 映射展示名（`frontend/src/lib/tool-display.ts:77`），所以后端定义不动，不产生定义哈希变化和迁移。
- `load_skill` 加载带脚本的 Skill 时，同一轮里自动激活已授权的 `run_skill_script`；Run 已有默认 bash 能力时，同时提示使用 `/skills/<名称>/` 路径。

## 分期

### 第一期：不改数据模型

状态（2026-10-13）：已实现第 1、2、4、5 项；第 3 项（资源档位）推迟到 Kata 实测之后，因为调低规格可能导致 OOM，调高又会挤占主机容量，没有实测数据就无法定档。

1. 容量信号量与 busy 重排队，替换死掉的 `sandbox_busy` 分支。新配置 `OPENSANDBOX_MAX_SANDBOXES`，默认 0（不限制）。
2. Skill 会话内已上传的 Skill 版本不再重复上传（记在进程内，第二期迁到会话表）；job 请求只携带包内文件名。依赖重放保留：它在同一会话内会复核环境哈希，脚本若改动了已装依赖能被发现。
3. 资源档位（推迟）。
4. MCP 按失败阶段归类、超长结果按字节截断、把我们自己的错误说明交给模型。
5. Streamable HTTP 的远程 MCP 按 Run 复用连接（属主任务模式，空闲 60 秒关闭）；legacy SSE 依赖长连接事件流，保持一次性连接。

### 剩余工作的实施计划

顺序：第 0 步 → A → B、C、D（都依赖 A）→ E（依赖 A 和代理实测）；F 随时可做；G 等实测数据。规模：A、D、E 大，C 中，B、F、G 小。

实施状态（2026-10-14）：用户明确暂缓 Kata 测试环境，继续后续实现。A–F 已完成本地实现；G 已接入按任务类型选择的三档资源，数值为暂定配置，生产 Kata 校准仍待有执行主机后进行。生产运行时的 Kata 要求保持不变。

本轮验证：19 个受影响后端套件通过；独立 PostgreSQL 上全量 Alembic 前滚、已有工作区 bash 补建、部分唯一索引并发冲突及降级/升级通过。独立 server 0.2.3/runc 上完整执行 smoke 通过，包括 ID 接回、工作区保留、短租约接管进程清理、bash 超时/非零退出/截断/出网拒绝/只读 Skill/流式生成物、stdio 连续两次调用复用同一进程、取消销毁和原生 TTL。另用独立 Redis 实测 SDK 预热复用、取出标签、池容量扣减和访客两台上限。前端相关 5 个测试文件 167 项及类型检查通过。

最后补充的所有权回归通过：暂存期间失去租约不会启动命令或 MCP 桥接，销毁按数据库当前沙箱 ID 执行；带时区的数据库截止时间不会延长原生 TTL。56 个改动 Python 文件的编译与项目 Ruff 检查通过，沙箱 14 项检查和重建镜像自检通过。最终代码再次通过隔离 OpenSandbox 的完整功能、预热池与容量 smoke。前端定向 lint、格式检查与生产构建通过。

补充验证（2026-10-15，bash 改为默认内置能力）：`tests.agents.harness`、`tests.agent_skills.api`、`tests.tools.tools`、`tests.tools.unit`、`tests.tools.shell_unit`、`tests.agents.unit`、`tests.agents.agents`、`tests.agents.agent_access`、`tests.agents.agent_services_coverage`、`tests.agents.agent_runtime_coverage`、`tests.infra.architecture` 共 11 个后端套件通过；覆盖无绑定 Agent 的真实 durable 执行链路（模拟模型和执行端口）、控制台/公开/API Run 自动注入、历史绑定隐藏与清理、大目录/Schema 预算/恢复后的持续可用。前端目录、选择器、时间线和展示名相关 4 个文件共 161 项测试、类型检查、定向 lint/格式检查及生产构建通过，后端编译与 Ruff 通过。本次未重跑执行主机实测，未部署。

提交前复核（2026-10-15）：后端全量 43 个功能套件、前端全量 1556 项测试、58 个改动 Python 文件的编译与 Ruff、前端类型检查/全仓 lint/改动文件格式检查/生产构建、沙箱 14 项测试全部通过。重新构建独立执行镜像并通过非特权自检，在独立 OpenSandbox 0.2.3/runc 与 Redis 上通过完整 smoke、SDK 池及容量检查；在独立 PostgreSQL 上再次通过全量迁移、已有工作区 bash 补建、唯一索引并发冲突和降级后再升级。三套 Compose 配置渲染及镜像列表、Celery 回收步骤注册通过。临时容器、数据库和测试镜像已清理；未部署，本次未重测全仓覆盖率或 Kata。

全仓覆盖率检查未通过 97% 门槛：本轮测量约 94%，隔离 HEAD 基线约 95%，不能视为 CI 全部通过。全套运行中的 `smoke.test_main` 曾因本机 Redis 认证配置返回 503；使用独立 Redis 重跑通过，未改业务配置。

#### 第 0 步：先完成的验证

- 第一期本地回归已通过：`tests.execution.unit`、`tests.tools.tools`、`tests.tools.unit`、`tests.infra.mcp_transports`、`tests.agent_skills.unit`、`tests.agent_skills.api`、`tests.agents.harness`、`tests.agents.agents`、`tests.workflows.workflows`、`tests.infra.infra_unit_coverage`，另有 `tests.infra.architecture`、编译检查和 Ruff 通过。
- 在执行主机上实测：
  - Kata 冷启动：创建到就绪、首条命令的耗时。
  - server 0.2.3 + Kata 下 `Sandbox.connect`、`renew` 是否可用。
  - `RunCommandOpts(background=True)` 启动的常驻进程能否存活，服务端代理 `/v1/sandboxes/{id}/proxy/{port}/...` 能否承载长连接 HTTP 流（E 需要）。
  - SDK 的 `SandboxPoolAsync` 在 0.2.3 上能否正常补池和取用（C 需要）。
  - `SandboxManager.list_sandbox_infos` 能否按 metadata 过滤（遗留清扫需要）。
  - 镜像根文件系统是否可写、`/tmp` 容量多大，决定工作区放 `/workspace` 还是 `/tmp` 下（D 需要）。

待验证项：尚无 Kata 执行主机。本机 OrbStack 只有 runc，本机功能验证不能替代 Kata 冷启动、VM 隔离或资源档位实测；第 0 步的 Kata 部分仍未完成。按用户 2026-10-14 的指示，这些测量不再阻止后续代码实现。

已提供 `backend/tests/execution/opensandbox_probe.py`。在已运行 server 0.2.3 的隔离执行主机上，先备齐执行镜像及固定版本的 execd/egress 镜像，并在私有环境里设置 `OPENSANDBOX_URL`、`OPENSANDBOX_IMAGE`、`OPENSANDBOX_API_KEY`、`OPENSANDBOX_PROBE_REDIS_URL`，然后执行：

```bash
cd backend
uv run python -m tests.execution.opensandbox_probe \
  --url "$OPENSANDBOX_URL" --image "$OPENSANDBOX_IMAGE" \
  > /tmp/nexaflow-tools-phase0.json
```

脚本不读取业务 `.env`、不访问业务数据库；在执行主机上用 Docker 核对测试沙箱的实际 runtime，在上传代码前复用现有 dns+nft 核验。它记录三次创建/首命令耗时、断开后按 ID 接回和文件保留、续期、标签正负过滤、文件系统、70 秒代理流，以及两个 SDK 池客户端共享 Redis 的取用/补池和 metadata 更新；最终清理本次标签的沙箱及独立 Redis 命名空间。结果为不含凭据的 JSON，失败或缺项会明确标记；普通 Docker 必须显式加 `--allow-development`，其 `phase_zero_complete` 始终为 false。探测脚本的 5 项单元检查通过，命令为 `uv run python -m tests.execution.probe_unit`。

本机隔离功能探测结果（server 0.2.3、SDK 0.1.16、OrbStack/runc、1 CPU / 512 MiB；不是 Kata 数据）：

| 检查 | 结果 |
| --- | --- |
| 创建至就绪，三次 | 2.538 / 1.810 / 1.674 秒；镜像已提前备齐 |
| 首条命令，三次 | 1.052 / 1.025 / 1.020 秒 |
| 按 ID 接回、文件保留、续期 | 通过；续期后的剩余有效期约 300 秒 |
| metadata 正负过滤 | 通过 |
| 文件系统 | 根文件系统以 root 可写，`/workspace` 以 UID 65532 可写；未发现独立 `/tmp` 挂载，其容量反映共享根卷，不能作为任务磁盘配额 |
| 后台进程和代理流 | 关闭启动客户端后仍可连接；15 个事件持续 70.052 秒，首事件 0.007 秒 |
| 桥接认证头 | `Authorization` 被剥离；专用应用头可用且缺失时返回 401；控制面密钥不进入沙箱 |
| SDK 预热池 | 同一进程的两个池客户端共享 Redis，核验后入池、metadata 更新和补池均通过；取用约 0.034 秒 |
| 清理 | 本次沙箱剩余 0，独立 Redis 命名空间已删除 |

第一期本地报告保存在 gitignored 的 `docs/local/tools-phase0-development.json`，`phase_zero_complete=false`。当时独立镜像自检、完整 `tests.execution.opensandbox_smoke` 和 `sandbox.tests` 的 10 项检查通过，job 协议覆盖率实测 84%。本轮增加 bash 与 stdio 宿主后重新构建独立测试镜像并通过完整 live smoke；这些结果均不作为 Kata/VM 或生产资源校准的验收。

#### A. 执行会话持久化（跨 worker，已实现）

- 数据：新表 `execution_sessions`，ORM 放新模块 `app/domain/execution/models.py`，实体放 `app/entities/execution.py`，仓储放 `app/infra/db/repositories/execution/sessions.py`，加 Alembic 迁移。
  - 字段：`id`、`workspace_id`、`run_id`、`purpose`（`run` / `mcp`）、`owner_key`、`sandbox_id`、`image`、`profile_fingerprint`、`state`（creating / ready / closing / closed）、`staged_packages`（JSON，已上传包的键）、`environments`（JSON，manager → 环境哈希）、`holder`、`holder_expires_at`、`expires_at`、`last_used_at`、`created_at`、`updated_at`。
  - 部分唯一索引：`(workspace_id, run_id, purpose, owner_key)`，约束包括 closing 在内的未关闭记录。先提交创建意图再调用控制面，争用者返回 `ExecutionBusy`，不先创建第二台再竞争记录。记录包含全局/访客容量 token，关闭中记录确认清理后才能重建。
- 适配器（`app/adapters/execution/opensandbox.py`）的会话路径改为：
  1. 进程内 `asyncio.Lock` 保持（同一进程内并行的工具调用仍然串行）。
  2. 仓储一次查询返回会话记录和 Run 信息（状态、执行截止时间、来源、消费方）。Run 已终态就拒绝创建，避免取消后又把沙箱建起来。
  3. 记录可用且指纹一致：进程内有句柄直接用，没有就 `Sandbox.connect(sandbox_id)` 接回并缓存句柄。
  4. 只有确认控制面返回 404 才重建；其他接回失败保持确认失败，避免临时故障生成第二台。进程内缓存句柄遇到 404 也会重建。重建时响应带 `workspace_reset: true`，Skill/bash 结果会保留此提示。
  5. 先抢 `holder` 租约：启动期 60 秒，监督任务每 2 秒核验 Run worker 身份、截止时间与 holder，并续期到 15 秒；失去所有权立即中止。接管过期 holder 时先杀旧 job 监督进程及 UID 65532 的进程，再运行新命令。抢不到返回 `ExecutionBusy`，旧 worker 不能销毁后继者的沙箱。
- 沙箱 TTL 改用 Run 的执行截止时间加 60 秒，不再用全局 `AGENT_RUN_TIMEOUT_SECONDS`（D 的命令行档预算会更长）。
- Skill 依赖：适配器按 Skill 环境与 bootstrap 记录安装锁，普通重连直接返回锁而不重新安装/遍历哈希；沙箱重建后 Skill 脚本和 bash 都重放 ledger 里已批准的计划并核对最终环境哈希。
- 关闭：
  - Agent Run 终态：已有（`executor.py`）。
  - Workflow Run 终态：同时关闭执行会话和 MCP 会话；暂停状态保留会话。
  - `cancel_run_tree`：新增，尽力关闭，失败交给回收。
  - Beat（`tasks/maintenance/jobs.py` 的分钟级步骤）回收终态、Run 截止时间已过、沙箱已过期、找不到 Run 或 closing 的记录；标签清扫处理创建超过 120 秒且没有记录的遗留沙箱。保护正在发布的创建意图、当前预热池和仍由原生 TTL 管理的一次性任务，删除前刷新记录并核验 owner 过滤。
- 测试：`tests.execution.unit` 覆盖跨客户端接回、404 重建、依赖缓存、容量失败清理和遗留清扫；`tests.execution.sessions` 用隔离 SQLite 验证租约/终态/过期/唯一索引。PostgreSQL 实测并发唯一索引及迁移往返通过。

#### B. Run 内的沙箱任务统一走会话（已实现）

- `app/infra/sandbox/client.py` 的 `_exchange`：当前执行范围带 `run_id` 时自动加上 `execution_session`。Python Tool、生成文件、四个固定渲染器、Workflow 代码节点都随之进入 Run 会话；Tool 测试没有 Run，仍然一次性。
- `job.py` 每次都在独立临时目录里运行并杀掉整个进程组，所以同一台沙箱里先后执行的任务互不干扰。
- 效果：一个 Run 只冷启动一次。

#### C. 预热池（已实现，默认关闭）

- 用 SDK 的 `SandboxPoolAsync` + `AsyncRedisPoolStateStore`（broker 用的 Redis），池名包含镜像指纹。
  - `creation_spec`：镜像、默认拒绝出网和 `DENIED_NETWORKS`、metadata `{owner: nexaflow, pool: <池名>}`。
  - `warmup_sandbox_preparer` 里执行 `_require_enforcement`，进池的沙箱都已核验过网络策略。
  - 取用：`acquire(sandbox_timeout=..., policy=DIRECT_CREATE)`，取到后 `patch_metadata` 补上工作区、Run 标签。需要出网域名的请求（依赖安装、stdio MCP）取到后再走现有的 `_allow_egress`。
- 新配置 `OPENSANDBOX_WARM_POOL_SIZE`，默认 0。池在每个 worker 进程首次使用时于共享任务事件循环里懒启动，补池由 SDK 的 Redis 主锁保证只有一个进程负责。
- `idle_timeout` 明确设为 240 秒，主锁 120 秒，启动就绪最多 60 秒，每 5 秒协调补池。新生成的服务端 TTL 上限为 1860 秒，不使用 SDK 默认的 24 小时空闲时长。
- 容量：池里的空闲沙箱不经过我们的名额，所以按需名额上限改为 `OPENSANDBOX_MAX_SANDBOXES - OPENSANDBOX_WARM_POOL_SIZE`；从池里取沙箱前也要先占名额。
- 换镜像后旧池的空闲沙箱由 A 的遗留清扫按池名回收。

#### D. bash 工具（已实现）

后端：

- 内置 Tool：`catalog/service.py` 新增 `build_shell_tool`，`function_name = "bash"`、`execution_spec = {"builtin": "shell"}`，策略 `approval = auto`、`effect = pure`、三种来源都开放、`workflow_callable = False`、`parallel_safe = False`。加入 `ensure_workspace_system_catalog`，并按 `202609270002_builtin_image_filename.py` 的写法加一个 Alembic 迁移，为已有工作区生成。
- 默认能力：`prepare_agent_run` 自动把 bash 加入冻结工具目录；`CapabilityRegistry` 优先装入 bash，在大目录、切换工具和 checkpoint 恢复后持续可用。底层仍走统一工具账本、策略与实时权限检查；不增加手动绑定。
- 适配器：新文件 `app/application/tools/runtime/adapters/shell.py`，`BuiltinToolAdapter` 遇到 `builtin == "shell"` 时分派过去。只在 Agent Run 内可用，没有 `run_id` 直接返回失败。
  1. 加载 Run 的 Skill 快照，逐个做现有的实时授权检查（`require_pinned_skill_access`），把还没上传的 Skill 以只读方式放到 `/skills/<名称>-<版本短哈希>/`，记入会话的 `staged_packages`。
  2. 发送 `{"execution_session": "agent_run", "command": {...}}` 请求。
  3. 读回结果：退出码、截断后的输出、新增的生成物清单。非零退出码和超时（退出码 124）都按成功的工具结果返回给模型，只有沙箱本身出错才算工具失败。
  4. 生成物不经过 `job.py` 响应传 base64，而是由适配器通过端口新增的 `read_session_file(workspace_id, run_id, path, max_bytes)` 用文件流读取，逐个调用 `create_generated_artifact`，幂等键为 `sha256(调用幂等键 + 相对路径)`。每条命令最多登记 8 个文件，单个不超过 5 MiB。
- `sandbox/job.py` 新增 `command` 模式（与依赖安装的 `shell` 字段分开）：
  - 以 UID 65532 在工作区目录执行 `/bin/bash --noprofile --norc -c <command>`；`HOME` 指向工作区；已装依赖时设置 `PYTHONPATH` 和 `NODE_PATH`。
  - rlimit：CPU 等于超时；不设地址空间上限（会派生 node 等进程）；单文件 64 MiB；进程数 64。
  - 执行前后各记录一次 `outputs/` 下的（路径、大小、mtime），对比出新增和修改的文件。
  - 结束后先杀进程组，再清理该用户除自身以外的所有进程，防止 `setsid` 或 `nohup` 留下后台进程。
  - 工作区超过 512 MiB 时在结果里提示模型。
  - 输出最多 30 KB：保留开头和结尾，中间截断并标注。
- 工具截止时间：`UnifiedAgentToolRuntime._tool_deadline` 改为接收参数，bash 用"命令超时 + 60 秒"，代替默认的 30 秒，与图片生成的特例同一处理方式。
- 预算：`snapshots.py` 的 `AgentRuntimePolicy` 增加命令行档。新配置 `AGENT_SHELL_MAX_TURNS`（24）、`AGENT_SHELL_MAX_TOOL_CALLS`（64）、`AGENT_SHELL_RUN_TIMEOUT_SECONDS`（900），在 `Settings.validate` 里按现有上限校验。`prepare_agent_run` 和重新生成两处创建 Run 的地方，在工具快照包含 bash 时选用此档。
- 部署：`configure.py` 新配置的服务端 TTL 上限为 1860 秒，覆盖最大 1800 秒 Run 加 60 秒。已有执行主机的旧 360 秒配置需由操作者更新，不能静默改写。
- 外部访问：容量模块增加按消费方分组的第二层计数（新配置 `OPENSANDBOX_MAX_SANDBOXES_PER_CONSUMER`，默认 2），分组键取自 A 中查询会话时一并读出的 Run 来源和消费方，只对公开链接和 API 生效。

前端：

- `src/lib/tool-display.ts` 的 `builtinToolDisplayName` 加 `bash` → `t("命令行")`；过程时间线显示命令和退出码（只在控制台，外部投影已经不暴露工具参数）。
- `src/lib/tool-visibility.ts` 将 bash 作为隐式能力隐藏；工具目录、选择器和 Agent 配置不展示独立命令行工具。
- `src/components/tools/builtin-tool-icon.tsx` 加终端图标。
- 生成物复用 `run_skill_script` 的 `artifacts` 输出结构和聊天里的展示路径。
- 新文案同时加进 `zhHans`、`zhHant`、`en` 三份字典。

测试：

- `sandbox.tests`：`command` 模式的超时、输出截断、进程清理（含 `setsid` 逃逸）、生成物识别。
- `tests.tools.unit` / `tests.tools.tools`：Tool 定义与迁移、适配器结果映射、生成物登记幂等。
- `tests.agents.agents`：命令行档预算、截止时间、外部来源投影。
- 在独立测试服务器上跑 `tests.execution.opensandbox_smoke`，确认 bash 无法出网。

#### E. stdio MCP 宿主沙箱（已实现）

- `sandbox/mcp_bridge.py`：用镜像里已有的 `mcp` SDK 只启动一次 stdio 服务，再起一个只转发 `tools/list` 和 `tools/call` 的低层 MCP Server，以 Streamable HTTP 监听沙箱内端口；要求启动时注入的随机令牌，通过专用应用头 `X-NexaFlow-MCP-Token: Bearer <token>` 验证。server 0.2.3 的代理会剥掉 `Authorization`，不能用该头给桥接进程认证。需确认 uvicorn 和 starlette 已在执行镜像的锁定依赖里。
- 启动：建一台 `purpose = mcp` 的会话沙箱（`owner_key` 为注册版本，出网域名在创建时设定），用 `background=True` 启动桥接，轮询就绪。令牌只保存在 worker 进程内存里，丢了就销毁重建。
- 连接：`_open_remote_client` 增加"受信任控制面"模式，目标为 `{OPENSANDBOX_URL}/v1/sandboxes/{id}/proxy/{port}/mcp`，只允许控制面主机，不做公网 DNS 校验；请求头带控制面密钥和桥接应用头。控制面密钥由代理核验并剥离，不转发进沙箱。之后复用现有的 Run 会话池（`app/adapters/mcp/sessions.py`），连接关闭时一并销毁沙箱。
- 失败归类：沙箱或桥接起不来算请求未发出。工具发现（注册、刷新）保持一次性沙箱，不占常驻会话。

#### F. Skill 轮次与命名（已实现）

- 已实现：`capabilities.py` 的 `load_skill` 在实时授权检查通过后，Skill 含 `.py` / `.js` 且目录里有 `run_skill_script` 时，把它加入 `active_names`，随 checkpoint 保存；重复加载不重复添加，纯说明 Skill 不激活脚本工具，也不授予目录外的能力。模型下一轮即可执行脚本，无需另一次 `activate_tools`。
- 已实现：前端 DOCX / PDF / PPTX / Excel 的展示名改为"生成 Word / PDF / PPT / Excel"，简体、繁体、英文三份字典同步。后端定义和已有绑定版本保持不变。
- 已实现：Run 包含默认 bash 能力时，`load_skill` 返回 `/skills/<安全名称>-<版本哈希>/` 路径与调用提示；名称使用统一规范化函数，bash 按相同规则挂载经过实时授权检查的固定版本文件。
- 验证：harness 集成覆盖直接加载后执行、重复加载、checkpoint 恢复、无脚本/无执行器和授权撤销；`tests.agents.harness`、`tests.agents.unit`、`tests.agents.agent_runtime_coverage` 已通过。前端按三种语言验证四个名称，工具选择器、目录、权限、Agent 配置和 Workflow 节点相关 10 个测试文件共 183 项通过；`bun run typecheck`、定向 ESLint / Prettier、`bun run build` 通过。后端编译、Ruff 和差异检查通过。

#### G. 资源档位（选择逻辑已实现，数值待 Kata 校准）

- 暂定 small = 1 CPU / 512 MiB、standard = 1 CPU / 1 GiB、heavy = 2 CPU / 2 GiB。一次性请求按任务类型选择；Run 主沙箱按冻结工具/Skill 中的最大需求选择，纯 Python/代码节点 small，bash/脚本 standard，渲染或依赖安装 heavy，防止先创建 small 后再运行大任务。stdio 宿主 standard。
- 三个 SDK 池按档位分摊部署配置的总池大小，池名包含控制面、镜像和资源规格。规格尚未依据 Kata 冷启动/OOM/并发数据校准；有执行主机后补跑第 0 步并调整这一处资源表。

#### 暂不做（2026-10-13 已决定）

Skill 发布时构建依赖、运行时经内网包镜像装包。
## 验证计划

- 后端：`tests.execution.unit`、`tests.execution.sessions`、`tests.tools.shell_unit`、`tests.tools.tools`、`tests.tools.unit`、`tests.infra.mcp_transports`、`tests.agent_skills.unit`、`tests.agent_skills.api`、`tests.agents.harness`、`tests.agents.agents`、`tests.workflows.workflows`；迁移在测试库上执行 Alembic。
- 执行镜像：`uv run --project sandbox python -m sandbox.tests`、`sandbox/run_coverage.sh`；在独立测试服务器上跑 `tests.execution.opensandbox_smoke`，覆盖 bash 超时、输出截断、进程组清理和默认拒绝出网。
- 前端：`bun run typecheck`，以及工具展示名、bash 过程事件的相关测试。

## 已同步更新的文档

`AGENTS.md`（Skill 脚本类型、stdio MCP 一次性沙箱、Run 私有会话等描述）、`docs/AGENTS_RUNTIME.md`、`deploy/opensandbox/README.md`、`docs/DEPLOYMENT.md`。
