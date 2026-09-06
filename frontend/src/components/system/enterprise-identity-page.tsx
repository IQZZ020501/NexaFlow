"use client"

import * as React from "react"
import {
  CopyIcon,
  ExternalLinkIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  SaveIcon,
} from "lucide-react"

import { FilterDropdown } from "@/components/app/filter-dropdown"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { copyText } from "@/lib/clipboard"
import { displayWorkspaceName } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import {
  bindEnterpriseIdentity,
  listEnterpriseConnections,
  listEnterpriseIdentities,
  saveEnterpriseConnection,
  type EnterpriseConnection,
  type EnterpriseIdentity,
  type EnterpriseProvider,
} from "@/lib/api/enterprise-identity"
import { listAllWorkspaceMembers, type WorkspaceMember } from "@/lib/api/system"

const providers: EnterpriseProvider[] = ["feishu", "dingtalk", "wecom"]
const providerConsoleUrls: Record<EnterpriseProvider, string> = {
  feishu: "https://open.feishu.cn/app",
  dingtalk: "https://open-dev.dingtalk.com/",
  wecom: "https://work.weixin.qq.com/wework_admin/frame#apps",
}

type ConnectionForm = {
  name: string
  clientId: string
  clientSecret: string
  tenantId: string
  agentId: string
  enabled: boolean
}

function emptyForm(label: string): ConnectionForm {
  return {
    name: label,
    clientId: "",
    clientSecret: "",
    tenantId: "",
    agentId: "",
    enabled: true,
  }
}

export function EnterpriseIdentityPage() {
  const { t } = useLanguage()
  const session = useSession()
  const { notify, selectWorkspace, selectedWorkspaceId, token } = session
  const workspaces = session.workspaces.filter(
    (item) => item.status === "active"
  )
  const workspaceId =
    (selectedWorkspaceId &&
    workspaces.some((item) => item.id === selectedWorkspaceId)
      ? selectedWorkspaceId
      : workspaces[0]?.id) ?? ""
  const [connections, setConnections] = React.useState<EnterpriseConnection[]>(
    []
  )
  const [identities, setIdentities] = React.useState<EnterpriseIdentity[]>([])
  const [members, setMembers] = React.useState<WorkspaceMember[]>([])
  const [forms, setForms] = React.useState<
    Record<EnterpriseProvider, ConnectionForm>
  >({
    feishu: emptyForm(t("飞书")),
    dingtalk: emptyForm(t("钉钉")),
    wecom: emptyForm(t("企业微信")),
  })
  const [loading, setLoading] = React.useState(false)
  const [saving, setSaving] = React.useState<EnterpriseProvider | null>(null)
  const [selectedProvider, setSelectedProvider] =
    React.useState<EnterpriseProvider>("feishu")
  const loadRequestRef = React.useRef(0)

  async function load() {
    const requestId = ++loadRequestRef.current
    if (!token || !workspaceId) return
    setLoading(true)
    try {
      const [nextConnections, nextIdentities, nextMembers] = await Promise.all([
        listEnterpriseConnections(token, workspaceId),
        listEnterpriseIdentities(token, workspaceId),
        listAllWorkspaceMembers(token, workspaceId),
      ])
      if (requestId !== loadRequestRef.current) return
      setConnections(nextConnections)
      setIdentities(nextIdentities)
      setMembers(nextMembers.filter((item) => item.user.is_active))
      setForms(
        Object.fromEntries(
          providers.map((provider) => {
            const current = nextConnections.find(
              (item) => item.provider === provider
            )
            return [
              provider,
              current
                ? {
                    name: current.name,
                    clientId: current.client_id,
                    clientSecret: "",
                    tenantId: current.tenant_id,
                    agentId: current.agent_id ?? "",
                    enabled: current.enabled,
                  }
                : emptyForm(
                    t(
                      provider === "feishu"
                        ? "飞书"
                        : provider === "dingtalk"
                          ? "钉钉"
                          : "企业微信"
                    )
                  ),
            ]
          })
        ) as Record<EnterpriseProvider, ConnectionForm>
      )
    } catch (error) {
      if (requestId === loadRequestRef.current) {
        notify("error", getErrorMessage(error, t))
      }
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false)
    }
  }

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
    return () => {
      loadRequestRef.current += 1
    }
    // Data reload is intentionally keyed only by authentication and workspace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, workspaceId])

  function updateForm(
    provider: EnterpriseProvider,
    field: keyof ConnectionForm,
    value: string | boolean
  ) {
    setForms((current) => ({
      ...current,
      [provider]: { ...current[provider], [field]: value },
    }))
  }

  async function save(provider: EnterpriseProvider) {
    if (!token || !workspaceId) return
    setSaving(provider)
    const form = forms[provider]
    try {
      await saveEnterpriseConnection(token, workspaceId, provider, {
        name: form.name,
        ...(provider === "wecom" ? {} : { client_id: form.clientId }),
        ...(form.clientSecret ? { client_secret: form.clientSecret } : {}),
        ...(provider === "feishu" ? {} : { tenant_id: form.tenantId }),
        ...(form.agentId ? { agent_id: form.agentId } : {}),
        enabled: form.enabled,
      })
      notify("success", t("企业登录配置已保存"))
      await load()
    } catch (error) {
      notify("error", getErrorMessage(error, t))
    } finally {
      setSaving(null)
    }
  }

  async function bind(identity: EnterpriseIdentity, userId: string) {
    if (!token || !workspaceId) return
    try {
      const updated = await bindEnterpriseIdentity(
        token,
        workspaceId,
        identity.id,
        userId || null
      )
      setIdentities((current) =>
        current.map((item) => (item.id === updated.id ? updated : item))
      )
      notify("success", t(userId ? "企业身份已绑定" : "企业身份已解除绑定"))
    } catch (error) {
      notify("error", getErrorMessage(error, t))
    }
  }

  async function handleCopy(value: string) {
    try {
      await copyText(value)
      notify("success", t("已复制"))
    } catch {
      notify("error", t("复制失败"))
    }
  }

  if (!workspaceId) {
    return (
      <Card>
        <CardContent className="text-sm text-muted-foreground">
          {t("暂无可管理工作空间")}
        </CardContent>
      </Card>
    )
  }

  const provider = selectedProvider
  const form = forms[provider]
  const current = connections.find((item) => item.provider === provider)

  return (
    <div className="grid gap-4 pb-6">
      <Card>
        <CardHeader className="flex-row flex-wrap items-end justify-between gap-3">
          <div>
            <CardTitle>{t("企业登录")}</CardTitle>
            <CardDescription>
              {t(
                "每个身份源固定连接一个工作空间，权限仍由 NexaFlow 成员关系决定"
              )}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <FilterDropdown
              className="h-9 w-fit max-w-56"
              value={workspaceId}
              onChange={selectWorkspace}
              ariaLabel={t("选择工作空间")}
              options={workspaces.map((workspace) => ({
                value: workspace.id,
                label: displayWorkspaceName(workspace, t),
              }))}
            />
            <Button
              variant="outline"
              size="icon"
              onClick={() => void load()}
              aria-label={t("刷新")}
            >
              <RefreshCwIcon className={loading ? "animate-spin" : ""} />
            </Button>
          </div>
        </CardHeader>
      </Card>

      <Card className="min-w-0">
        <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>{form.name || t("企业登录")}</CardTitle>
            <CardDescription>
              {t(
                provider === "feishu"
                  ? "配置应用凭证，企业信息将在首次成功登录时自动识别"
                  : "配置服务商应用凭证和租户标识"
              )}
            </CardDescription>
          </div>
          <FilterDropdown
            className="h-9 w-fit"
            value={provider}
            onChange={(value) =>
              setSelectedProvider(value as EnterpriseProvider)
            }
            ariaLabel={t("选择登录平台")}
            options={providers.map((item) => ({
              value: item,
              label: t(
                item === "feishu"
                  ? "飞书"
                  : item === "dingtalk"
                    ? "钉钉"
                    : "企业微信"
              ),
            }))}
          />
        </CardHeader>
        <CardContent className="grid min-w-0 gap-4 md:grid-cols-2">
          <Field>
            <FieldLabel htmlFor={`${provider}-name`}>
              {t("显示名称")}
            </FieldLabel>
            <Input
              id={`${provider}-name`}
              value={form.name}
              maxLength={120}
              onChange={(event) =>
                updateForm(provider, "name", event.target.value)
              }
            />
          </Field>
          {provider !== "wecom" ? (
            <Field>
              <FieldLabel htmlFor={`${provider}-client`}>
                {t("应用 ID")}
              </FieldLabel>
              <Input
                id={`${provider}-client`}
                value={form.clientId}
                maxLength={255}
                onChange={(event) =>
                  updateForm(provider, "clientId", event.target.value)
                }
              />
            </Field>
          ) : null}
          <Field>
            <FieldLabel htmlFor={`${provider}-secret`}>
              {t("应用密钥")}
            </FieldLabel>
            <Input
              id={`${provider}-secret`}
              type="password"
              value={form.clientSecret}
              maxLength={4096}
              autoComplete="new-password"
              placeholder={
                current?.has_client_secret
                  ? t("留空以保留当前密钥")
                  : t("请输入应用密钥")
              }
              onChange={(event) =>
                updateForm(provider, "clientSecret", event.target.value)
              }
            />
            {current?.client_secret_hint ? (
              <FieldDescription>
                {t("当前密钥提示：{hint}", {
                  hint: current.client_secret_hint,
                })}
              </FieldDescription>
            ) : null}
          </Field>
          {provider !== "feishu" ? (
            <Field>
              <FieldLabel htmlFor={`${provider}-tenant`}>
                {t("企业 ID")}
              </FieldLabel>
              <Input
                id={`${provider}-tenant`}
                value={form.tenantId}
                maxLength={255}
                onChange={(event) =>
                  updateForm(provider, "tenantId", event.target.value)
                }
              />
            </Field>
          ) : null}
          {provider === "wecom" ? (
            <Field>
              <FieldLabel htmlFor="wecom-agent">
                {t("应用 Agent ID")}
              </FieldLabel>
              <Input
                id="wecom-agent"
                value={form.agentId}
                maxLength={255}
                onChange={(event) =>
                  updateForm(provider, "agentId", event.target.value)
                }
              />
            </Field>
          ) : null}
          <div className="flex flex-wrap items-center justify-between gap-3 md:col-span-2">
            <Button
              variant="link"
              className="h-auto w-fit justify-start px-0 py-0"
              asChild
            >
              <a
                href={providerConsoleUrls[provider]}
                target="_blank"
                rel="noreferrer"
              >
                {t("获取应用凭证")}
                <ExternalLinkIcon data-icon="inline-end" />
              </a>
            </Button>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(event) =>
                  updateForm(provider, "enabled", event.target.checked)
                }
              />
              {t("启用企业登录")}
            </label>
          </div>
          {current ? (
            <div className="grid min-w-0 gap-2 rounded-lg border bg-muted/20 p-3 text-xs md:col-span-2">
              <div className="font-medium">{t("回调地址")}</div>
              <div className="flex min-w-0 items-center gap-2">
                <code
                  className="min-w-0 flex-1 truncate"
                  title={current.callback_url}
                >
                  {current.callback_url}
                </code>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => void handleCopy(current.callback_url)}
                  aria-label={t("复制回调地址")}
                >
                  <CopyIcon />
                </Button>
              </div>
              <div className="font-medium">{t("工作空间登录地址")}</div>
              <div className="flex min-w-0 items-center gap-2">
                <code
                  className="min-w-0 flex-1 truncate"
                  title={current.login_url}
                >
                  {current.login_url}
                </code>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => void handleCopy(current.login_url)}
                  aria-label={t("复制登录地址")}
                >
                  <CopyIcon />
                </Button>
              </div>
            </div>
          ) : null}
          <Button
            className="md:col-span-2"
            onClick={() => void save(provider)}
            disabled={saving !== null}
          >
            {saving === provider ? (
              <LoaderCircleIcon className="animate-spin" />
            ) : (
              <SaveIcon />
            )}
            {t("保存")}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("企业身份绑定")}</CardTitle>
          <CardDescription>
            {t("首次扫码会自动创建普通成员；管理员可在此调整绑定或停用身份")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {identities.length ? (
            <div className="grid gap-2">
              {identities.map((identity) => (
                <div
                  key={identity.id}
                  className="grid gap-3 rounded-lg border p-3 md:grid-cols-[minmax(0,1fr)_minmax(14rem,20rem)] md:items-center"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">
                      {identity.display_name || identity.subject_id}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {t(
                        identity.provider === "feishu"
                          ? "飞书"
                          : identity.provider === "dingtalk"
                            ? "钉钉"
                            : "企业微信"
                      )}{" "}
                      · {identity.email || identity.subject_id}
                    </div>
                  </div>
                  <FilterDropdown
                    value={identity.user_id ?? ""}
                    onChange={(value) => void bind(identity, value)}
                    ariaLabel={t("绑定 NexaFlow 成员")}
                    options={[
                      { value: "", label: t("停用此身份") },
                      ...members.map((member) => ({
                        value: member.user.id,
                        label: `${member.user.name} (${member.user.username})`,
                      })),
                    ]}
                  />
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
              {t("暂无企业身份")}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
