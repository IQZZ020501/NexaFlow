# NexaFlow Skills

Skills 是按需加载的指令与文件包，不是另一套 Agent、RAG 流程或权限系统。
Agent 内核负责模型/工具循环、会话、上下文、扩展和持久化；知识检索、
MCP 与 Skills 是可选择的能力。没有强制检索、依据核验、隐藏答案清单，
Skill 也不能把整个 Run 的执行预算收紧。

## 工作空间版本化包

工具页 `/app/tools/skills` 可创建、导入、编辑、保存草稿、发布和停用包。
支持 UTF-8 `SKILL.md` 或包含单个包的 ZIP；包内可有 `scripts/`、
`references/`、`assets/` 和二进制文件。ZIP 可以带根目录，但不能包含
包根以外的文件、路径穿越、重复路径、链接、特殊文件或加密项。
上传/解压后的总大小均限 2 MiB，最多 64 个文件。

```text
research/
├── SKILL.md
├── scripts/
│   ├── main.py
│   └── helper.py
├── references/
│   └── guide.md
└── assets/
    └── data.csv
```

```markdown
---
name: research
description: Analyze a supplied dataset and produce a report.
license: MIT
---

Read references/guide.md when needed. Use scripts/main.py for the calculation.
```

前置 YAML 必须有非空 name/description；正文限 12,000 字符。
服务端保存时统一生成 `SKILL.md`，保证正文/名称/描述和编辑字段一致，
保留其他 YAML 元数据、脚本、参考资料和二进制资产。

控制面使用 schema-v2 定义：`instructions`、`files`（相对路径到 base64
内容）、可选意图/输入输出 Schema、知识库与 Tool 引用、护栏和单次脚本超时。
旧 `retrieval`、`stop`、`evaluation`、`budgets` 字段已删除并拒绝接收。
旧 schema-v1 测试包需重新创建；不迁移旧包或提供旧运行器回退。

发布版本不可变，正文和全部文件参与 SHA-256 定义哈希。Agent 绑定固定
skill/version 引用，Run 冻结快照及非敏感执行镜像/网络指纹。发布下一版本
不会替换运行中的旧版本；执行配置变更会拒绝旧 Run 重试，避免静默换镜像。

## 渐进加载与权限

- 初始上下文只有名称、描述、意图和版本目录，不含完整正文或 base64 文件。
- `load_skill(version_id)` 按需读取固定版本正文与文件目录。
- `read_skill_file(version_id, path, offset)` 读取已加载包的 UTF-8 文件，
  分页返回；二进制不注入模型上下文，但可供包内脚本使用。
- `run_skill_script(version_id, path, inputs, filename?)` 是普通内置 Tool，
  不是绕过账本的管理动作；绑定脚本包的 Agent 自动纳入此 Tool 的固定
  授权快照。只允许运行该 Run 绑定版本中的 `.py`/`.js` 文件。
- `install_skill_dependencies(version_id, manager, packages)` 只接受精确版本的
  PyPI `package==version` 或 npm `package@version`，每次调用都需要用户审批。
  它不接受 URL、路径、版本范围、tag、安装参数或 Skill 自带的安装脚本。
- 每次加载、读取和执行都重新检查工作空间、绑定者状态、`use` 授权、
  停用状态和不可变版本哈希。Skill 文本不会创建或授权任意 Tool。
- Tool 仍经过统一审批、幂等、租约和 `tool_invocations` 账本；
  需要审批的外部写入不会因加载 Skill 获得自动执行权限。

初始小规模工具 loadout 最多 8 个且 Schema 总大小有界；大型目录通过
`search_tools`/`activate_tools` 渐进选择。激活不能越过授权目录。
活跃工具与已加载 Skills 随 checkpoint 保存和恢复。

## 包内脚本

脚本在外部 OpenSandbox 运行，接收 stdin 上的 JSON 对象。Python 可导入
包内辅助模块；Node.js 使用同一只读包的脚本/资产。环境不含数据库、
JWT、模型凭据或 OpenSandbox 控制面密钥。

```python
import json
import os
import sys
from pathlib import Path

inputs = json.load(sys.stdin)
package = Path(os.environ["NEXAFLOW_SKILL_DIR"])
data = (package / "assets/data.csv").read_text()
Path(os.environ["NEXAFLOW_OUTPUT_PATH"]).write_text(data)
```

提供 filename 时须写出单个 1 字节至 5 MiB 普通文件。返回 stdout/exit_code
和签名下载链接；保存/下载继续使用租户范围、幂等键、24 小时有效期、
attachment/nosniff 与 HTML CSP。脚本默认超时 30 秒，可声明 0.1–120 秒；
整个调用仍受 Tool/Run 总截止时间限制。

包不能选镜像、挂载宿主目录、提供安装命令或直接安装
`requirements.txt`/`package.json`。如果脚本缺包，Agent 可显式调用
`install_skill_dependencies` 请求精确版本依赖；审批通过后，依赖安装到该
Agent Run 的私有 OpenSandbox 会话，并由后续脚本复用。Worker 恢复时会根据
已成功的 Tool 账本重建环境并核对哈希。Python 仅接受二进制 wheel，npm
禁用 lifecycle scripts；依赖数量、文件数、单文件和总存储均有上限。

安装期间只临时开放部署允许的官方包注册域名，结束后立即恢复默认拒绝；
脚本本身始终无外网。固定 renderer 依赖仍须预装到 digest 固定的执行镜像。
MCP 走已授权 Tool，不向脚本注入业务凭据。

## 固定文件渲染 Tools

`sandbox/skills/{documents,pdf,pptx,spreadsheets}` 是 NexaFlow 自编固定渲染器，
预装于执行镜像，并非上传后即可自动注册的第三方包。它们继续在
Agent/Workflow 工具选择器中提供同一输入契约：

- `documents_skill`：DOCX 文件名与 Markdown，可继承参考 DOCX 格式。
- `pdf_skill`：PDF 文件名与 Markdown。
- `pptx_skill`：PPTX 文件名与结构化幻灯片、表格和讲者备注。
- `spreadsheets_skill`：XLSX 文件名与结构化工作表/行。

调用方只能传内容/数据，不能替换 renderer 代码。这四项功能和 Workflow
Python Code 均通过同一 execution port 进入 OpenSandbox。

## 执行边界与检查

生产采用独立 Linux/Kata 主机、`dns+nft` 默认拒绝、无业务挂载/环境继承、
cgroup/process 限制、任务 UID 65532、显式 destroy 与原生 TTL。工作空间
Skill 的安装与脚本在同一个 Run 私有 sandbox 中串行执行；Run 终态销毁，
Worker 丢失时由原生 TTL 回收。普通 Docker 只用于显式开发检查。包内只读
权限和程序限制是纵深防御，不能替代整个容器/VM 隔离边界。详情见
[OpenSandbox 部署](../deploy/opensandbox/README.md)。

回归：`tests.agent_skills.unit`、`tests.agent_skills.api`、
`tests.agents.harness`、`tests.execution.unit`、`sandbox.tests` 和执行镜像自检。
