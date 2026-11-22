# 第三方应用集成

工具页的「集成」位于 MCP 右侧，独立地址为 `/app/tools/integrations`。滴答清单、飞书和腾讯会议默认均未安装；浏览目录不会连接平台、交换 Token 或创建工具。点击「安装」后在平台登录授权，服务端接受有效授权结果才会显示「已安装」。

## 应用配置

滴答清单采用与[官方 DIDA CLI](https://help.dida365.com/articles/7464976698707017728) 对齐的单一集成目录，当前依据 `@suibiji/dida-cli` **0.1.16**，替换原来的四项工具实现。CLI 本身封装滴答 Open API；NexaFlow 在服务端调用相同的固定接口，不运行宿主 CLI，也不在用户之间共用 CLI 配置或 Token 文件。

滴答清单**不需要填写 Client ID、Client Secret 或 Token**，成员和管理员均点击「安装」后直接登录授权。服务端依据滴答的[官方 OAuth 元数据](https://dida365.com/.well-known/oauth-authorization-server)，为本次安装向 `https://api.dida365.com/oauth/register` 自动注册公共客户端，指定本站回调与 `token_endpoint_auth_method=none`，再以 PKCE S256 授权、向 `https://api.dida365.com/oauth/token` 交换凭据。注册得到的公共 Client ID 与 verifier 绑定本人的五分钟授权尝试并加密保存；不发送 Client Secret，也不复用 CLI 固定的 `localhost:8766` 回调。注册与交换期间卸载或发起新安装，迟到结果均无法恢复连接。

滴答清单直接使用浏览器 OAuth，**无需在 SMTP 页面配置站点地址**。回调为 `<NexaFlow 访问地址>/app/tools/integrations/callback`，沿用部署时已有的 `PUBLIC_APP_URL`（Compose 的 `x-settings.public-app-url`）；根 `make dev` 自动将实际前端端口作为访问地址，同时保留显式环境配置。浏览器 Origin 只在与部署地址匹配时用于生成回调；本地开发允许同协议、同端口的 `localhost` / `127.0.0.1` / `::1` 互换，避免登录状态跨来源丢失。服务端不信任 Host 或转发头，也不接受任意回调网址。

点击「安装」后自动登记回调、申请 `tasks:read tasks:write` 并跳转滴答登录；完成后返回原站点的集成回调页面。旧版手工应用授权需要重新认证一次，旧配置入口及接口已移除，原凭据不会被新流程使用。滴答安装不再读取 SMTP 站点配置。

飞书采用[官方飞书 CLI](https://www.feishu.cn/feishu-cli) 的个人应用注册与设备授权协议，当前固定依据 `@larksuite/cli` **1.0.100**（上游 `c5fbf1a`）。点击「安装」后先在飞书页面创建个人应用，再继续登录并授权个人数据访问；两步均在浏览器完成，无需填写 Client ID、Client Secret、Token、回调地址或 SMTP 站点地址。只支持飞书 / Lark 账号，不支持豆包账号。企业对应用与数据权限的管控仍然生效。

服务端先向 `accounts.feishu.cn/oauth/v1/app/registration` 申请 `PersonalAgent` 注册，再轮询个人应用凭据；如平台报告账号属于 Lark，仅切换至固定的 `accounts.larksuite.com`。随后向对应品牌的 `/oauth/v1/device_authorization` 申请用户登录授权，通过 `/oauth/v3/token` 交换及刷新凭据。个人应用凭据与用户 Token 加密保存在本人的连接中，不共享工作空间应用配置，不创建宿主 CLI 配置文件，也不把凭据交给 Agent 或执行沙箱。授权页面仅允许飞书 / Lark 的固定官方域名；私有 device code 不返回前端。轮询按平台间隔执行，`slow_down` 延长间隔，拒绝、过期或结果不明时要求重新安装。创建个人应用与登录分别使用平台返回的有效期，最多十分钟。

登录权限来自两品牌官方 CLI 公布的 `/lark-cli/apis/scopes.json` 用户权限目录（固定于 2026-11-20），与本地操作实际需要的权限取交集，并显式申请 `offline_access` 和代用户发消息权限。不会把接口元数据中的旧版替代权限直接拼入授权请求。创建成功后自动进入用户授权；如果平台窗口的隔离策略阻止自动跳转，原安装弹窗仍保留「前往授权」链接。失败或请求取消会把授权尝试标为失败，重试需重新安装。

两阶段授权期间保留飞书窗口与安装页的关联，避免过早清空 `opener` 使浏览器拒绝第二次跨站导航；授权成功后关闭该窗口。授权页面均来自上述固定官方域名，凭据只通过后端轮询交换，不接受窗口消息传入的 Token。飞书的访问与刷新令牌允许最多 64 KiB（整体授权响应仍限 64 KiB），兼容全业务权限下超过 8,000 字符的实际令牌；空值、控制字符和越界值继续拒绝。

原来的飞书开发者应用配置入口、配置接口、授权码回调和两项业务工具实现已移除。旧连接会显示「需要重新认证」，原凭据无法继续调用或刷新；重新安装后归档旧工具。历史版本与账本保留，不自动替换已经冻结的运行快照。无需数据库迁移，旧应用配置记录不会被新流程使用。

腾讯会议使用其[官方 CLI 公布的设备授权流程](https://github.com/TencentCloud/tencentmeeting-cli)：安装按钮打开腾讯会议授权页面，NexaFlow 在原页面按五秒间隔查询授权结果，不在宿主机或沙箱安装 CLI。部署网络需能访问 `work.medialab.qq.com`、`meeting.tencent.com` 和 `api.meeting.qq.com`。该流程由平台管理应用注册；业务请求必须携带 `Tmeet-Open-Source: CLI` 以及由授权账号和原始设备标识组成的 `Tmeet-Unique-ID`，否则有效 Token 也会被平台报为过期。这两个请求头与 Token 一样仅在服务端使用。平台实际返回过期错误码 `190303` / `200190303` 时，连接标为需要重新认证，不会自动重复调用业务接口。

## 安装与使用

| 集成 | 当前提供的 Agent 工具 |
| --- | --- |
| 滴答清单 | 与 DIDA CLI 对齐的 50 项工具：任务及评论、清单及文件夹和看板列、标签、习惯及打卡、专注、第三方日历、倒数日和偏好 |
| 飞书 / Lark | 289 项固定接口操作：消息、邮箱、日历、云文档、电子表格、Base、幻灯片、画板、知识库、云空间、思维笔记、妙记、视频会议、任务、审批、考勤、通讯录、OKR |
| 腾讯会议 | 35 项工具：会议管理与搜索、受邀成员、录制与下载地址、AI 纪要与转写、参会报告与导出、企业通讯录、会中控制 |

安装成功才创建对应来源、不可变工具版本和审批策略；随后可在 Agent 的工具选择器选择整个集成。凭据不进入模型参数、运行快照、沙箱或工具结果。调用继续使用 `tool_invocations` 账本、运行归属检查和对话审批模式；写操作不会在结果不明时自动重放。当前集成限账号本人交互式使用，不支持共享账号、机器 API 或工作流调用。

已安装账号可点击卡片的「更新工具」同步当前目录，无需卸载或重新授权；该操作只更新本人的本地工具目录，不调用平台业务接口或交换凭据。相同定义重复更新不会创建多余版本。更新后，在 Agent 工具选择器中取消并重新勾选此集成，然后保存，以选择新增工具并切换到当前版本；已有绑定和运行快照不会自动获得新能力。定义发生变化的旧工具仍会被现有版本校验阻止，需重新选择后再使用。全新安装直接提供完整目录。

### 飞书 CLI 工具范围

飞书目录通过四项 Agent 工具按需发现，避免一次向模型注入数百份参数定义：`list_operations` 按业务域或英文关键词分页查找，`describe_operation` 返回准确的 `params_schema`、`body_schema`、平台权限和读写属性，`read_api` 调用只读接口，`write_api` 调用写接口并沿用对话审批模式。读工具不能执行写操作；忙闲查询、搜索、批量读取等只读 POST 仍按读取处理。模型不能选择任意 URL、请求头、账号或 Token，资源标识与参数会再次校验。目录修订写入工具定义，旧版本不会静默获得新接口。

底层由服务端请求官方 CLI 使用的固定 HTTP 接口，不在业务服务器或沙箱运行 CLI 二进制，也不复制上游技能正文。固定 API 目录由官方 CLI 的用户身份目录及已核对的业务快捷命令整理，许可保存在 `backend/app/adapters/integrations/feishu-catalog.LICENSE`。支持 Markdown/XML 云文档读写、消息发送及回复、表格单元格读写、Base 数据管理、妙记逐字稿与摘要读取等；异步创建文档通过返回的任务 ID 显式查询。每次只读一页，JSON 请求最大 128 KiB，响应沿用 2 MiB 上限；消息发送和回复使用调用账本标识生成幂等键。平台实际开放的权限与产品版本决定可执行范围。

本次没有接入本机文件上传下载、常驻事件订阅、应用身份与应用配置管理、CLI 安装更新命令或未包含在该版本官方 CLI 中的 OCR 能力；不把 289 项接口操作等同于官方 CLI 所有命令。已有 Agent 需要重新选择并保存飞书集成，才能使用新工具。

### 滴答清单工具范围

| 分类 | 操作标识 |
| --- | --- |
| 任务 | `get_task`、`create_task`、`update_task`、`complete_task`、`complete_tasks`、`delete_task`、`move_tasks`、`assign_task`、`unassign_task`、`list_completed_tasks`、`filter_tasks`、`search_tasks` |
| 任务评论 | `list_task_comments`、`add_task_comment`、`delete_task_comment` |
| 清单 | `list_projects`、`get_project`、`get_project_data`、`list_project_members`、`create_project`、`update_project`、`delete_project` |
| 文件夹和看板列 | `list_project_groups`、`create_project_group`、`update_project_group`、`delete_project_group`、`list_columns`、`create_column`、`update_column` |
| 标签 | `list_tags`、`create_tag`、`update_tag`、`rename_tag`、`delete_tag` |
| 习惯和打卡 | `get_habit`、`list_habit_sections`、`list_habits`、`create_habit`、`update_habit`、`create_habit_checkin`、`list_habit_checkins` |
| 专注 | `get_focus`、`list_focus`、`create_focus`、`update_focus`、`delete_focus` |
| 日历、倒数日和偏好 | `list_calendar_accounts`、`query_calendar_events`、`list_countdowns`、`get_preference` |

任务支持优先级、起止日期、全天标记、重复、标签、提醒、检查事项和父子关系；更新只发送指定字段，日期传 `null` 清除，标签和提醒传空数组清除。批量完成最多 50 项，返回已完成和失败 ID，不静默截断或重试；分配任务的用户名取自清单成员。按名称移动看板列先查询其 ID；设置看板列或文件夹后重新读取确认，未生效或无法确认时返回结果不确定，避免把接口回显当作成功。

专注类型为 `0`（番茄）或 `1`（正计时），时长单位为秒，查询范围最多 30 天。习惯打卡日期使用 `YYYYMMDD`；时间戳携带明确时区。第三方日历查询不传条件时保留平台默认的未来三个月范围，显式范围由平台按最多三个月校验；完整保留部分成功状态与账号错误。日历、偏好、任务筛选、搜索及已完成任务查询虽然使用 POST，仍按只读工具处理。所有写操作继续受对话审批控制。具体可访问能力由滴答账号、共享清单权限和平台接口决定。

目录更新会归档旧的 `list_tasks`，由 `get_project_data` 替代；旧版本和调用历史仅保留审计，不再提供旧实现或第二套入口。

### 腾讯会议工具范围

| 分类 | 操作标识 |
| --- | --- |
| 会议管理与查询 | `list_meetings`、`get_meeting`、`get_by_code`、`list_ended`、`search_meetings`、`create_meeting`、`update_meeting`、`cancel_meeting` |
| 受邀成员 | `list_invitees`、`add_invitees`、`remove_invitees`、`replace_invites` |
| 录制与转写 | `search_records`、`record_download`、`record_minutes`、`record_todos`、`transcript_get`、`transcript_find`、`transcript_part`、`record_timeline`、`minutes_by_url`、`transcript_url` |
| 参会报告 | `participants`、`waiting_log`、`export_members`、`export_result` |
| 企业通讯录 | `search_contacts`、`lookup_email`、`lookup_phone` |
| 会中控制 | `call_members`、`kick_members`、`waiting_control` |
| 元宝纪要 | `search_minutes`、`get_minutes`、`live_minutes` |

创建和更新会议支持普通/周期性会议、密码、时区、入会范围、等候室、水印、自动录制及转写设置。时间使用带时区的 ISO 8601 格式，服务端转换为各接口要求的时间戳或时间文本；更新仅提交指定字段，不把未填写的设置重置为默认值。目录对分页大小、批量成员数和递归规则设有边界，调用身份始终取自当前账号授权，不接受模型覆盖操作者。

有分页的读取一次只请求一页，模型可用返回的游标继续查询；参会报告最多每页 100 条，转写详情的 `pid` / `limit` 用于段落读取。出勤导出先创建异步任务，再以 `export_result` 查询状态和下载地址；录制下载只获取平台地址，不在业务服务器自动下载文件。创建/更新/取消会议、邀请变更、导出任务和会中控制均标记为写操作，遵循对话审批模式。通讯录反查和分享链接内容读取虽然使用 POST，仍按只读工具处理。

具体可访问的数据与功能取决于平台账号、企业权限、录制权限、纪要生成状态及主持人身份。目录不会授予平台权限。当前不包含官方 CLI 的本机日志导出与问题反馈、常驻事件订阅、录制分享权限修改或录制配置修改；这些不属于本次业务工具范围。

连接按「工作空间 × 用户 × 平台」唯一，管理员不能读取其他用户的安装凭据。回调状态绑定连接、用户、代次和有效期；每次交换前先持久化处理中状态，避免重放。滴答使用五分钟公共客户端授权码与 PKCE 流程，不保留机密客户端回退；飞书使用上述两阶段设备授权。滴答元数据目前仅声明授权码 grant，过期后重新认证；支持刷新凭据的平台使用数据库刷新租约，结果不明或租约过期时要求重新认证。

卸载立即清除本地凭据、作废待完成授权并归档工具来源。重新安装更新工具版本和授权代次，旧运行不能借此恢复权限；已有调用记录保留。卸载不会宣称撤销平台侧的授权，必要时可在平台账号设置中另外撤销。删除账号时，私人连接及授权尝试随账号删除，工具和历史归档保留。

## 验证

从 `backend/` 运行 `uv run python -m tests.tools.integrations`、`uv run python -m tests.tools.integration_providers`、`uv run python -m tests.tools.feishu`、`uv run python -m tests.tools.dida` 和 `uv run python -m tests.tools.tencent_meeting`，覆盖无 SMTP 配置时发起浏览器 OAuth、可信来源与伪造 Host 隔离、公共客户端自动注册、PKCE、旧授权退役、路由、加密、个人隔离、回调重放、刷新、迟到授权、卸载、重新安装、目录替换和真实调用账本，以及滴答、飞书和腾讯会议的 HTTP 契约、参数边界与读写行为；飞书额外覆盖个人应用注册、两步设备授权、Lark 品牌切换、授权链接校验、轮询间隔、全部固定参数 schema 和读写隔离。`tests.tools.unit` 覆盖回调来源规范化及本地回环地址规则。提供方 HTTP 响应在隔离测试中模拟，不访问用户账号或自动执行真实客户端注册。前端回归位于 `frontend/tests/integrations.test.tsx` 和 `frontend/tests/errors.test.ts`。开发启动器的实际端口与环境覆盖回归运行根目录 `uv run --project backend python -m unittest scripts.dev_test scripts.compose_test`。部署前需应用迁移 `202611200002`，并使用实际账号完成三方授权和业务接口联调。目录替换及免配置授权均不需要额外数据库迁移，更新代码后需重新启动 API / Worker 以加载新目录和适配器。

`tests.tools.integration_concurrency` 需要通过 `NEXAFLOW_TEST_DATABASE_URL` 显式指定已迁移的隔离 PostgreSQL，验证并发刷新只交换一次、卸载拦截迟到刷新、过期租约不能重放刷新凭据，以及永久删除工作空间时的级联关系。

接口依据：[DIDA CLI 官方帮助](https://help.dida365.com/articles/7464976698707017728)、[DIDA CLI npm 包及 API mapping](https://www.npmjs.com/package/@suibiji/dida-cli/v/0.1.16)、[飞书 CLI 官方入口](https://www.feishu.cn/feishu-cli)、[官方安装使用指南](https://www.feishu.cn/content/article/7623291503305083853)、[飞书 CLI 源码](https://github.com/larksuite/cli/tree/c5fbf1a)、[自研 Agent 接入说明](https://open.feishu.cn/document/mcp_open_tools/feishu-cli/embed-feishu-cli-in-agent)、[腾讯会议 CLI](https://github.com/TencentCloud/tencentmeeting-cli)。
