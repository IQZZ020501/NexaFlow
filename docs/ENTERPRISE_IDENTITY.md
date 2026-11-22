# 企业登录部署说明

NexaFlow 支持飞书、钉钉和企业微信登录。每个身份源连接固定属于一个
NexaFlow 工作空间；服务商只负责证明员工身份，用户是否可访问以及角色权限仍以
PostgreSQL 中的用户、工作空间成员关系为准。

## 上线前配置

1. 将 `PUBLIC_APP_URL` 设置为用户访问 NexaFlow 的 HTTPS Origin，例如
   `https://nexaflow.example.com`。该值不能包含路径、查询参数或片段。
2. 执行 Alembic 迁移。
3. 使用全局管理员账号进入 `/system/identity`，选择工作空间并配置服务商应用。
4. 在服务商开放平台登记页面提供的配置值：
   - 飞书、钉钉：将完整回调地址填写到应用的重定向 URL。
   - 企业微信：将授权回调域（域名及端口，不含协议和路径）填写到应用的 Web 登录
     授权回调域；页面会自动提取，可直接复制。
5. 在服务商开放平台授权应用读取当前登录用户的基础身份信息。企业微信还必须配置
   可信域名、应用的企业可信 IP，并确保应用可见范围包含允许登录的员工。

管理员在企业登录页面选择工作空间后保存服务商配置，该连接会固定属于所选工作空间。
所有已启用连接都会在主登录页显示为服务商图标；点击后进入对应服务商的新版官方
登录页扫码。首次扫码会自动创建该工作空间的普通成员并直接进入系统，后续扫码复用
同一账号。系统不会按服务商返回的邮箱合并
现有 NexaFlow 账号；全局管理员仍可在企业身份列表中调整绑定或停用身份。

登录图标使用 `PUBLIC_APP_URL` 生成的完整入口，在回调所属站点建立浏览器绑定
Cookie 后才跳转服务商。本地通过 `localhost` 打开页面、但回调配置为 `127.0.0.1`
时，登录入口也会先进入 `127.0.0.1`，避免跨主机丢失 Cookie 导致 `invalid_state`。

三家均使用新版授权流程：飞书使用 `accounts.feishu.cn/open-apis/authen/v1/authorize`
及 `accounts.feishu.cn/oauth/v3/token`；企业微信使用
`login.work.weixin.qq.com/wwlogin/sso/login`；钉钉使用
`login.dingtalk.com/oauth2/auth`。系统不再加载旧飞书二维码 SDK 或调用旧 passport 接口。

飞书使用服务端保管 App Secret 的机密客户端授权。当前[授权码文档](https://open.feishu.cn/document/common-capabilities/sso/api/obtain-oauth-code)
注明，该授权入口的 PKCE 暂时需搭配 v2 token 接口，因此本系统的 v3 链路不携带
`code_challenge` 或 `code_verifier`；继续校验一次性 `state` 和浏览器 HttpOnly nonce，
并在服务端使用 App Secret 换取令牌。应用必须使用自己的 App ID / App Secret。

回调地址不是需要管理员编写的接口：NexaFlow 根据 `PUBLIC_APP_URL` 自动生成，并处理
授权码校验、账号绑定和登录。三家仍要求在开放平台登记回调地址或可信域名，以确认
授权结果只能返回指定网站；前端 JS 回调也不能取消这项平台配置。只需在平台后台
登记一次，无须在 NexaFlow 中填写自定义回调地址或额外开发回调接口。回调路径为
`/api/v1/auth/enterprise/callback/{provider}`，其中 `provider` 为 `feishu`、`dingtalk`
或 `wecom`。参见[企业微信新版登录组件说明](https://developer.work.weixin.qq.com/document/path/98152)。

## 安全行为

- 应用密钥使用 `MODEL_SECRET_KEY` 加密保存，接口只返回末四位提示。
- 授权请求使用一次性 `state` 和浏览器 HttpOnly nonce，应用密钥只在服务端使用。
- 回调会校验服务商返回的租户标识，且只访问代码内固定的 HTTPS 服务商端点。
- 企业微信的应用 `access_token` 按企业及应用密钥区分，在 Redis 中加密共享缓存；
  以服务商返回的 `expires_in` 提前 60 秒过期，并以分布式锁合并并发刷新。同一应用
  用于多个工作空间连接时复用缓存，修改密钥后使用独立缓存。平台明确返回 token
  无效或过期时最多刷新并重试一次，授权码错误不重试，非企业成员仍拒绝登录。
  缓存不可用时拒绝登录，不退回每次获取令牌的路径。参见
  [官方缓存及提前失效要求](https://developer.work.weixin.qq.com/document/path/91039)。
- 登录入口按来源 IP 限流；限流存储不可用时拒绝发起登录。
- 提供方失败会记录请求阶段、HTTP 状态和数字错误码到系统日志，不保存授权码、
  token、密钥或可能回显这些数据的原始错误描述。
- 停用连接、解除身份绑定，或修改应用/租户标识时，相关企业登录会话立即失效；解除
  绑定后的身份保持停用，不会在下次扫码时重复创建账号。
- 修改应用或租户标识会清空旧身份绑定，必须重新核验，避免跨租户身份复用。

一个 NexaFlow 用户仍可同时属于多个工作空间。企业登录只决定本次登录后的默认工作
空间，不会删除或隐藏该用户原有的其他工作空间成员关系。
