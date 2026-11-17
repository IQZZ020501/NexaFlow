# NexaFlow Skills

Skills 是按需加载的指令与文件包，不是另一套 Agent、RAG 流程或权限系统。
Agent 内核负责模型/工具循环、会话、上下文、扩展和持久化；知识检索、
MCP 与 Skills 是可选择的能力。没有强制检索、依据核验、隐藏答案清单，
Skill 也不能把整个 Run 的执行预算收紧。

## 工作空间版本化包

工具页 `/app/tools` 的「Skills」页签（`kind=builtin`）可创建、导入、编辑、保存草稿、发布和停用包；导入检查与授权查询接口为 `POST /api/v1/workspaces/{workspace_id}/agent-skills/imports/inspect` 与 `GET …/{skill_id}/permissions`。
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

初始小规模工具 loadout 最多 8 个且 Schema 总大小有界；单个超大工具会
延迟加载，但不会清空其他已配置工具。大型目录通过
`search_tools`/`activate_tools` 渐进选择。激活不能越过授权目录。
活跃工具与已加载 Skills 随 checkpoint 保存和恢复。

## 工作流使用

工作流 LLM 节点「工具」右侧的「＋」可以添加 MCP 服务和已发布的工作空间
Skill。MCP 按服务展示，保存时绑定其中有使用权限的子工具；同一 Skill 在
一个工作流中统一绑定指定发布版本。节点只可加载和执行自己选择的 Skill，不能使用同一工作流其他
节点的 Skill。发布、排队和执行时仍检查绑定者权限及版本哈希。

节点按需加载 `load_skill`，脚本通过 `run_skill_script` 在 Run 的沙箱中执行，
文件通过统一产物服务交付；内置文档处理指南可以使用同一沙箱的 bash。
需要逐次审批的 MCP 或依赖安装会暂停工作流，调试面板与分享页都可批准或
拒绝；恢复沿用保存的模型调用和账本身份，已执行的脚本不会重复运行。
多个节点同时请求审批时，全部决定后才恢复。API 消费者不能执行需要交互
审批的工具；依赖安装器也不会向 API 模型开放。

已有安装升级需应用迁移 `202611170005`，再重新发布引用了旧策略的工作流。
迁移保留审批模式、访问来源和已有授权，停用工具保持停用。

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
和下载链接（普通文件为签名链接，PNG 为随机 UUIDv4 链接）；保存/下载继续
使用租户范围、幂等键、24 小时有效期、attachment/nosniff 与 HTML CSP。
脚本默认超时 30 秒，可声明 0.1–120 秒；
整个调用仍受 Tool/Run 总截止时间限制。

包不能选镜像、挂载宿主目录、提供安装命令或直接安装
`requirements.txt`/`package.json`。如果脚本缺包，Agent 可显式调用
`install_skill_dependencies` 请求精确版本依赖；审批通过后，依赖安装到该
Agent Run 的私有 OpenSandbox 会话，并由后续脚本复用。Worker 恢复时会根据
已成功的 Tool 账本重建环境并核对哈希。Python 仅接受二进制 wheel，npm
禁用 lifecycle scripts；依赖数量（单次最多 16 个）、文件数、单文件和总存储均有上限。

安装期间只临时开放部署允许的官方包注册域名，结束后立即恢复默认拒绝；
脚本本身始终无外网。固定 renderer 依赖仍须预装到 digest 固定的执行镜像。
MCP 走已授权 Tool，不向脚本注入业务凭据。

## 内置文件工作流与 Skill Creator

`sandbox/skills/{documents,pdf,pptx,spreadsheets,skill-creator}` 存放项目维护的
指引与辅助脚本。五个可选内置 Tool 均以 `{}` 加载完整指引，随后由 Agent
通过已授权的 bash 在 Run 私有沙箱读写文件；不再要求固定 Markdown、
结构化工作表或 PPT 构图输入。加载本身不执行程序、不生成文件或授予能力。

- `documents_skill`：python-docx 创建与定点修改，检查原文样式、章节、
  表格、图像、页眉页脚与相关 OOXML；可用 LibreOffice Writer 生成预览。
- `pdf_skill`：PyMuPDF 读取、渲染、合并、拆分、旋转、表单与明确请求的
  内容编辑；没有 Aside 专用接口，不预装 OCR。
- `pptx_skill`：python-pptx 自由设计与定点修改，保留原主题、母版、
  图表、嵌入工作簿、图像和备注。构图、字体和配色由任务决定。
  提供有界结构盘点和 LibreOffice Impress 预览辅助脚本；
  旧 layout、PPTD/WASM 与固定构图引擎已删除。
- `spreadsheets_skill`：pandas 分析、openpyxl 编辑 CSV/XLSX/XLSM；
  保留公式和有关元数据，避免 DataFrame 导出覆盖原工作簿。
  LibreOffice Calc 可在副本中重算；未重算的缓存值不得宣称验证通过。
- `skill_creator`：生成可导入的 SKILL.md/ZIP，并检查项目导入限制。
  不写宿主账户目录，不自动发布、绑定或授权新 Skill。

每份完整指引随 ToolVersion 参与定义哈希并冻结，业务镜像只携带 Markdown，
辅助代码和锁定依赖预装在执行镜像。文件通过现有 bash 出口自动持久化和
交付，沿用 5 MiB 上限、租户隔离、连续会话恢复与不可变版本。

这些加载器仅供 Agent 使用，`workflow_callable=false`；Workflow 的文件
生成可通过已授权 MCP 工具或 Agent 节点完成，独立 Python Tool 与 Python Code 节点已删除。DOCX/PDF/XLSX 旧 renderer 仍仅用于
已有冻结契约，不作为新 Skill 的创作接口。PPT 旧实现已按要求完全删除。
生成页图并不等于完成视觉检查，指引要求明确报告实际检查能力与局限。

升级须同时发布业务代码与执行镜像，再应用 `202611170003`：刷新已有工作
空间的四个文件 Tool、补齐 Skill Creator，将可编辑应用绑定移到新契约，
保留审批/访问策略及发布、执行历史。新契约只接受 `{}`；历史发布版本需
重新发布，使用旧输入的 Workflow 需改用已授权 MCP 工具或 Agent 节点。此处提供迁移但不
自动操作正在运行的数据库或服务。回退须配套恢复业务代码、执行镜像与
数据库备份；迁移降级不会重建已删除的 PPT 实现。

## 执行边界与检查

生产采用独立 Linux/Kata 主机、`dns+nft` 默认拒绝、无业务挂载/环境继承、
cgroup/process 限制、任务 UID 65532、显式 destroy 与原生 TTL。工作空间
Skill 的安装与脚本在同一个 Run 私有 sandbox 中串行执行；Run 终态销毁，
Worker 丢失时由原生 TTL 回收。普通 Docker 只用于显式开发检查。包内只读
权限和程序限制是纵深防御，不能替代整个容器/VM 隔离边界。详情见
[OpenSandbox 部署](../deploy/opensandbox/README.md)。

回归：`tests.agent_skills.unit`、`tests.agent_skills.api`、
`tests.agents.harness`、`tests.execution.unit`、`sandbox.tests` 和执行镜像自检。
