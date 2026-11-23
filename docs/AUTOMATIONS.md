# 自动化与任务通知

自动化属于当前工作空间中的个人用户，可绑定已发布的 Agent 或 Workflow 的明确版本。
从「自动化」页面创建，也可从应用详情进入并预选应用。自动化详情保留执行记录、
结果、工具审批、工作流表单及生成文件下载；列表和执行历史均支持分页。

## 触发与执行

- 定时支持单次、每天、每周指定星期，按 `Asia/Shanghai` 计算，星期采用 ISO 编号：周一为 1、周日为 7。数据库保存 UTC 时间。
- 后台 Worker 的单例 Beat 每约 30 秒扫描到期任务；实际启动时间还受队列、额度和执行资源影响。
- 停机恢复最多补最近一次到期任务，记录更早的错过次数。同一自动化串行执行；上次仍在运行时，定时触发会记录跳过。
- Webhook 先持久化接收记录，再异步派发。已接收的事件按接收顺序串行执行，排队上限通过 `max_pending` 配置，范围 1–100，默认 20；队列满返回 `429`。
- 暂停阻止后续派发。已在运行的 Run 通过「取消运行」单独取消。恢复单次任务时，即使原定时间已过，仍保留这次执行；已完成的单次任务需要重新安排时间。
- 每次触发创建独立会话。输入、发布版本和执行模式在触发时冻结，后续编辑只影响新触发。
- Run 创建与执行记录关联在一个事务中提交。派发故障由后台恢复，重复投递复用原 Run；普通业务失败不自动创建另一个 Run。

文本任务输入最多 4000 字符；结构化 JSON 作为 Workflow 输入传递，也会用于构造 Agent 任务。
映射后的任务文本超长或必需字段缺失会明确拒绝，不静默截断。持久知识资料沿用应用绑定；
本期不提供定时附件上传、平台专用事件订阅或对外结果回调。

## Webhook 接入

创建 Webhook 自动化后，保存返回的地址与一次性展示的密钥；密钥可在详情页轮换。
服务端加密保存密钥，不将其写入执行快照或日志。

请求使用 UTF-8 JSON 对象，正文最多 256 KiB，包括分块传输；携带以下请求头：

| 请求头 | 内容 |
| --- | --- |
| `X-NexaFlow-Timestamp` | Unix 时间戳（秒），允许与服务器相差最多 300 秒 |
| `X-NexaFlow-Event-Id` | 发送方稳定事件 ID，最多 128 个可见 ASCII 字符 |
| `X-NexaFlow-Signature` | `sha256=` 加 HMAC-SHA256 十六进制摘要 |

签名输入为 `timestamp.event_id.` 的 UTF-8 字节，紧接**原始正文**字节，使用 Webhook 密钥计算。
例如可用标准 Python 库构造请求：

```python
import hashlib
import hmac
import json
import os
import time
import urllib.request

event_id = "upstream-event-123"  # 同一事件重试时保持不变
timestamp = str(int(time.time()))
body = json.dumps({"message": "生成今日报告"}, ensure_ascii=False).encode("utf-8")
signed = f"{timestamp}.{event_id}.".encode("utf-8") + body
signature = hmac.new(os.environ["WEBHOOK_SECRET"].encode(), signed, hashlib.sha256).hexdigest()
request = urllib.request.Request(
    os.environ["WEBHOOK_URL"], data=body, method="POST",
    headers={
        "Content-Type": "application/json",
        "X-NexaFlow-Timestamp": timestamp,
        "X-NexaFlow-Event-Id": event_id,
        "X-NexaFlow-Signature": f"sha256={signature}",
    },
)
with urllib.request.urlopen(request, timeout=10) as response:
    print(json.load(response)["execution_id"])
```

持久接收成功返回 `202`。同一事件 ID 与相同 JSON 内容的重试返回原执行记录；
同一 ID 携带不同内容返回 `409`。重试可使用新时间戳重新签名，但必须保留事件 ID。
签名覆盖事件 ID，捕获的请求无法通过更换 ID 创建另一次执行。

可通过 `webhook_input_path` 提取点分字段，或用 `webhook_prompt_template` 中的
`{{data.message}}` 一类占位符构造任务文本。事件数据只进入任务输入，不能改变目标应用、
模型、工具授权或执行模式。

## 权限与通知

自动化按工作空间与所属用户隔离，管理员没有读取他人自动化或签名密钥的隐式权限。
每次派发和 Worker 开始／恢复执行前重新检查所属用户、工作空间与目标应用权限；
发布者和资源授权沿用现有发布运行规则。读取运行详情及下载文件也会重新鉴权。
账号永久删除会停用其自动化并清除 Webhook 凭据，运行历史保留。

执行模式沿用已有工具审批机制。需要审批或表单输入时，任务持久等待，用户可从通知
进入详情处理；恢复不重置原 Run 的截止时间或预算。

成功、失败、取消、待审批和待输入通知进入现有消息中心，可分别设置通知偏好。
通知属于接收用户，持久落库并按执行事件去重；只对根 Run 通知。
通知只含状态与详情入口，结果正文和错误详情通过授权的 Run 页面读取。
Redis 推送用于及时刷新，页面也会在重新可见及每分钟刷新持久消息。

## 迁移与检查

部署前执行正常 Alembic 升级至 `202611230001`，然后加载新的 API、后台 Worker、Agent Worker
与前端代码。继续使用现有 Compose 拓扑与单例 Beat，不增加常驻服务。
回退前暂停自动化；存在 `automation` 来源的 Run 或工具调用时，迁移拒绝降级，避免破坏历史。

从 `backend/` 运行：

```bash
uv run python -m tests.automations.unit
uv run python -m tests.automations.api
uv run python -m tests.automations.reliability
uv run python -m tests.automations.migration
uv run python -m tests.notifications.unit
```

并发检查另用已完成迁移的隔离 PostgreSQL，显式设置 `NEXAFLOW_TEST_DATABASE_URL` 后运行
`uv run python -m tests.automations.postgres`。该测试会写入测试账号和数据，不应指向业务库。
前端检查位于 `frontend/tests/automations.test.tsx`、消息中心和公告日期选择器相关测试。
