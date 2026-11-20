# 第三方应用集成

工具页的「集成」位于 MCP 右侧，独立地址为 `/app/tools/integrations`。滴答清单、飞书和腾讯会议默认均未安装；浏览目录不会连接平台、交换 Token 或创建工具。点击「安装」后在平台登录授权，服务端接受有效授权结果才会显示「已安装」。

## 应用配置

滴答清单和飞书需要空间管理员先在对应的开发者平台注册应用，再通过集成卡片的「配置」入口保存 Client ID / Client Secret。Secret 加密保存，接口只返回是否已配置。普通成员分别登录自己的账号，不接触应用密钥。

系统管理员需先在现有站点设置中配置公开站点地址，并在两个开发者平台登记 `<站点地址>/app/tools/integrations/callback`。回调地址由服务端生成，不使用请求 Host。滴答清单申请 `tasks:read tasks:write`；飞书申请 `offline_access docx:document:readonly im:message:send_as_user`，并按平台要求发布应用、批准权限和配置可用成员。存在未卸载的账号连接时，应用配置不能修改。

腾讯会议使用其[官方 CLI 公布的设备授权流程](https://github.com/TencentCloud/tencentmeeting-cli)：安装按钮打开腾讯会议授权页面，NexaFlow 在原页面按五秒间隔查询授权结果，不在宿主机或沙箱安装 CLI。部署网络需能访问 `work.medialab.qq.com`、`meeting.tencent.com` 和 `api.meeting.qq.com`。该流程由平台管理应用注册；业务请求必须携带 `Tmeet-Open-Source: CLI` 以及由授权账号和原始设备标识组成的 `Tmeet-Unique-ID`，否则有效 Token 也会被平台报为过期。这两个请求头与 Token 一样仅在服务端使用。平台实际返回过期错误码 `190303` / `200190303` 时，连接标为需要重新认证，不会自动重复调用业务接口。

## 安装与使用

| 集成 | 当前提供的 Agent 工具 |
| --- | --- |
| 滴答清单 | 列出清单、读取清单任务、创建任务、标记完成 |
| 飞书 | 读取云文档、以授权用户身份发送文本消息 |
| 腾讯会议 | 35 项工具：会议管理与搜索、受邀成员、录制与下载地址、AI 纪要与转写、参会报告与导出、企业通讯录、会中控制 |

安装成功才创建对应来源、不可变工具版本和审批策略；随后可在 Agent 的工具选择器选择整个集成。凭据不进入模型参数、运行快照、沙箱或工具结果。调用继续使用 `tool_invocations` 账本、运行归属检查和对话审批模式；写操作不会在结果不明时自动重放。当前集成限账号本人交互式使用，不支持共享账号、机器 API 或工作流调用。

腾讯会议已安装账号可点击卡片的「更新工具」同步当前目录，无需卸载或重新授权；该操作只更新本人的本地工具目录，不调用平台业务接口或交换凭据。相同定义重复更新不会创建多余版本。更新后，在 Agent 工具选择器中取消并重新勾选此集成，然后保存，以选择新增工具并切换到当前版本；已有绑定和运行快照不会自动获得新能力。定义发生变化的旧工具仍会被现有版本校验阻止，需重新选择后再使用。全新安装直接提供完整目录。

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

连接按「工作空间 × 用户 × 平台」唯一，管理员不能读取其他用户的安装凭据。回调状态绑定连接、用户、代次和五分钟有效期；授权码交换先持久化处理中状态，避免重放。飞书使用 PKCE；滴答使用其文档规定的机密客户端授权码流程。支持刷新凭据的平台使用数据库刷新租约，结果不明或租约过期时要求重新认证。

卸载立即清除本地凭据、作废待完成授权并归档工具来源。重新安装更新工具版本和授权代次，旧运行不能借此恢复权限；已有调用记录保留。卸载不会宣称撤销平台侧的授权，必要时可在平台账号设置中另外撤销。删除账号时，私人连接及授权尝试随账号删除，工具和历史归档保留。

## 验证

从 `backend/` 运行 `uv run python -m tests.tools.integrations`、`uv run python -m tests.tools.integration_providers` 和 `uv run python -m tests.tools.tencent_meeting`，覆盖路由、加密、个人隔离、回调重放、刷新、迟到授权、卸载、重新安装、目录更新和真实调用账本，以及腾讯会议 35 项工具的 HTTP 路径、参数、分页、身份、时间和读写行为；提供方 HTTP 响应在隔离测试中模拟，不访问用户账号。前端回归位于 `frontend/tests/integrations.test.tsx`。部署前需应用迁移 `202611200002`，并使用实际应用与账号完成三方授权和业务接口联调。扩展目录不需要额外数据库迁移，更新代码后需重新启动 API / Worker 以加载新目录和适配器。

`tests.tools.integration_concurrency` 需要通过 `NEXAFLOW_TEST_DATABASE_URL` 显式指定已迁移的隔离 PostgreSQL，验证并发刷新只交换一次、卸载拦截迟到刷新、过期租约不能重放刷新凭据，以及永久删除工作空间时的级联关系。

接口依据：[滴答清单 OpenAPI](https://developer.dida365.com/docs/index.html#/openapi)、[飞书官方 OpenAPI MCP](https://github.com/larksuite/lark-openapi-mcp)、[腾讯会议 CLI](https://github.com/TencentCloud/tencentmeeting-cli)。
