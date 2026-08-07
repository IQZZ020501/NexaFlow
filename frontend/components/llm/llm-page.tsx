import * as React from "react"
import ModelIcon from "@lobehub/icons/es/features/ModelIcon"
import Anthropic from "@lobehub/icons/es/Anthropic"
import Azure from "@lobehub/icons/es/Azure"
import Bailian from "@lobehub/icons/es/Bailian"
import Bedrock from "@lobehub/icons/es/Bedrock"
import DeepSeek from "@lobehub/icons/es/DeepSeek"
import Gemini from "@lobehub/icons/es/Gemini"
import IFlyTekCloud from "@lobehub/icons/es/IFlyTekCloud"
import Moonshot from "@lobehub/icons/es/Moonshot"
import Ollama from "@lobehub/icons/es/Ollama"
import OpenAI from "@lobehub/icons/es/OpenAI"
import Tencent from "@lobehub/icons/es/Tencent"
import TencentCloud from "@lobehub/icons/es/TencentCloud"
import Vllm from "@lobehub/icons/es/Vllm"
import Volcengine from "@lobehub/icons/es/Volcengine"
import Wenxin from "@lobehub/icons/es/Wenxin"
import Xinference from "@lobehub/icons/es/Xinference"
import Zhipu from "@lobehub/icons/es/Zhipu"
import {
  BrainCircuitIcon,
  ChevronDownIcon,
  CircleCheckIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
  SearchIcon,
  Trash2Icon,
} from "lucide-react"
import { getMembershipRole } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { IconButton } from "@/components/ui/icon-button"
import { CardMoreMenu } from "@/components/ui/card-more-menu"
import { Spec } from "@/components/ui/spec"
import {
  createRegisteredModel,
  deleteRegisteredModel,
  getModelProviderForm,
  listModelProviderBaseModels,
  listModelProviderCatalog,
  listRegisteredModels,
  updateRegisteredModel,
} from "@/lib/api/llm"
import type {
  BaseModelOption,
  ModelCredentialField,
  ModelProviderCatalog,
  RegisteredModel,
} from "@/lib/api/llm"
import type { TFunction, TranslationKey } from "@/i18n"

const MODEL_TYPE_LABELS: Record<string, TranslationKey> = {
  LLM: "大语言模型",
  EMBEDDING: "向量模型",
  RERANKER: "重排模型",
}

const CREDENTIAL_FIELD_LABELS: Record<string, TranslationKey> = {
  api_base: "API URL",
  api_key: "API Key",
  api_version: "API Version",
  azure_endpoint: "API URL",
  region_name: "AWS Region",
  endpoint_url: "Endpoint URL",
  aws_access_key_id: "AWS Access Key ID",
  aws_secret_access_key: "AWS Secret Access Key",
  aws_session_token: "AWS Session Token",
}

const PROVIDER_DISPLAY_ORDER = [
  "aliyun_bai_lian_model_provider",
  "model_anthropic_provider",
  "model_aws_bedrock_provider",
  "model_azure_provider",
  "model_deepseek_provider",
  "model_docker_ai_provider",
  "model_gemini_provider",
  "model_kimi_provider",
  "model_local_provider",
  "model_ollama_provider",
  "model_openai_provider",
  "model_regolo_provider",
  "model_siliconflow_provider",
  "model_tencent_cloud_provider",
  "model_tencent_provider",
  "model_vllm_provider",
  "model_volcanic_engine_provider",
  "model_wenxin_provider",
  "model_xf_provider",
  "model_xinference_provider",
  "model_zhipu_provider",
  "model_custom_provider",
]

type ProviderBrandIcon = {
  Render: React.ComponentType<{ size?: number | string; className?: string }>
  Color?: React.ComponentType<{ size?: number | string; className?: string }>
}

// Brand icons from @lobehub/icons, keyed by the catalog provider id.
// Providers without a brand icon in the package keep the static icon
// (`provider.icon`) or the initials fallback.
const PROVIDER_BRAND_ICONS: Record<string, ProviderBrandIcon> = {
  aliyun_bai_lian_model_provider: { Render: Bailian },
  model_anthropic_provider: { Render: Anthropic },
  model_aws_bedrock_provider: { Render: Bedrock },
  model_azure_provider: { Render: Azure },
  model_deepseek_provider: { Render: DeepSeek },
  model_gemini_provider: { Render: Gemini },
  model_kimi_provider: { Render: Moonshot },
  model_ollama_provider: { Render: Ollama },
  model_openai_provider: { Render: OpenAI },
  model_tencent_cloud_provider: { Render: TencentCloud },
  model_tencent_provider: { Render: Tencent },
  model_vllm_provider: { Render: Vllm },
  model_volcanic_engine_provider: { Render: Volcengine },
  model_wenxin_provider: { Render: Wenxin },
  model_xf_provider: { Render: IFlyTekCloud },
  model_xinference_provider: { Render: Xinference },
  model_zhipu_provider: { Render: Zhipu },
}

type ModelForm = {
  id: string | null
  name: string
  provider: string
  provider_type: string
  model_type: string
  model_name: string
  credential: Record<string, string>
  credential_hints: Record<string, string>
  status: string
}

const EMPTY_MODEL_FORM: ModelForm = {
  id: null,
  name: "",
  provider: "",
  provider_type: "openai_compatible",
  model_type: "LLM",
  model_name: "",
  credential: {},
  credential_hints: {},
  status: "active",
}

export function LlmPage() {
  const { t } = useLanguage()
  const { token, me, selectedWorkspaceId, notify } = useSession()

  const [providerCatalog, setProviderCatalog] = React.useState<
    ModelProviderCatalog[]
  >([])
  const [models, setModels] = React.useState<RegisteredModel[]>([])
  const [baseModels, setBaseModels] = React.useState<BaseModelOption[]>([])
  const [credentialFields, setCredentialFields] = React.useState<
    ModelCredentialField[]
  >([])
  const [selectedProvider, setSelectedProvider] = React.useState("")
  const [search, setSearch] = React.useState("")
  const [modelForm, setModelForm] = React.useState<ModelForm>(EMPTY_MODEL_FORM)
  const [isCatalogLoading, setIsCatalogLoading] = React.useState(false)
  const [isModelsLoading, setIsModelsLoading] = React.useState(false)
  const [isBaseModelsLoading, setIsBaseModelsLoading] = React.useState(false)
  const [isCredentialFieldsLoading, setIsCredentialFieldsLoading] =
    React.useState(false)
  const [isSaving, setIsSaving] = React.useState(false)
  const [isDialogOpen, setIsDialogOpen] = React.useState(false)
  const [isProviderPickerOpen, setIsProviderPickerOpen] = React.useState(false)
  const credentialRequestId = React.useRef(0)

  const workspaceRole = getMembershipRole(me, selectedWorkspaceId)
  const canManage = workspaceRole === "admin"

  const reportError = React.useCallback(
    (error: unknown) => {
      const message = getErrorMessage(error, t)
      notify("error", message)
      return message
    },
    [notify, t]
  )

  const loadProviderCatalog = React.useCallback(async () => {
    if (!token) {
      setProviderCatalog([])
      return
    }
    setIsCatalogLoading(true)
    try {
      const catalog = await listModelProviderCatalog(token)
      setProviderCatalog(
        catalog.toSorted(
          (left, right) =>
            providerDisplayIndex(left.provider) -
            providerDisplayIndex(right.provider)
        )
      )
    } catch (error) {
      setProviderCatalog([])
      reportError(error)
    } finally {
      setIsCatalogLoading(false)
    }
  }, [reportError, token])

  const loadModels = React.useCallback(async () => {
    if (!token) {
      setModels([])
      return
    }

    if (!selectedWorkspaceId) {
      setModels([])
      return
    }

    setIsModelsLoading(true)
    try {
      setModels(await listRegisteredModels(token, selectedWorkspaceId))
    } catch (error) {
      setModels([])
      reportError(error)
    } finally {
      setIsModelsLoading(false)
    }
  }, [reportError, selectedWorkspaceId, token])

  const loadBaseModels = React.useCallback(
    async (provider: string, modelType: string) => {
      if (!provider || !modelType) {
        setBaseModels([])
        return []
      }

      if (!token) {
        setBaseModels([])
        return []
      }

      setIsBaseModelsLoading(true)
      try {
        const models = await listModelProviderBaseModels(
          token,
          provider,
          modelType
        )
        setBaseModels(models)
        return models
      } catch (error) {
        setBaseModels([])
        reportError(error)
        return []
      } finally {
        setIsBaseModelsLoading(false)
      }
    },
    [reportError, token]
  )

  const loadCredentialFields = React.useCallback(
    async (
      provider: string,
      sourceCredential: Record<string, unknown> = {}
    ) => {
      const requestId = ++credentialRequestId.current
      if (!provider || !token) {
        setCredentialFields([])
        return
      }

      setIsCredentialFieldsLoading(true)
      try {
        const fields = await getModelProviderForm(token, provider)
        if (requestId !== credentialRequestId.current) {
          return
        }
        setCredentialFields(fields)
        setModelForm((current) => {
          if (current.provider !== provider) {
            return current
          }
          const credential: Record<string, string> = {}
          const credentialHints: Record<string, string> = {}
          for (const field of fields) {
            const sourceValue = sourceCredential[field.field]
            if (field.input_type === "PasswordInput") {
              credential[field.field] = ""
              if (typeof sourceValue === "string" && sourceValue) {
                credentialHints[field.field] = sourceValue
              }
            } else {
              credential[field.field] =
                typeof sourceValue === "string"
                  ? sourceValue
                  : String(field.default_value ?? "")
            }
          }
          return {
            ...current,
            credential,
            credential_hints: credentialHints,
          }
        })
      } catch (error) {
        if (requestId !== credentialRequestId.current) {
          return
        }
        setCredentialFields([])
        reportError(error)
      } finally {
        if (requestId === credentialRequestId.current) {
          setIsCredentialFieldsLoading(false)
        }
      }
    },
    [reportError, token]
  )

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadProviderCatalog()
  }, [loadProviderCatalog])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadModels()
  }, [loadModels])

  const visibleModels = React.useMemo(() => {
    const query = search.trim().toLowerCase()
    return models.filter((model) => {
      if (selectedProvider && model.provider !== selectedProvider) {
        return false
      }
      if (!query) {
        return true
      }
      return [
        model.name,
        model.model_name,
        providerLabel(providerCatalog, model.provider),
        model.api_base,
      ]
        .join(" ")
        .toLowerCase()
        .includes(query)
    })
  }, [models, providerCatalog, search, selectedProvider])

  if (!token || !me) {
    return null
  }

  function formForProvider(
    provider: ModelProviderCatalog | undefined
  ): ModelForm {
    if (!provider) {
      return EMPTY_MODEL_FORM
    }

    return {
      ...EMPTY_MODEL_FORM,
      provider: provider.provider,
      provider_type: provider.provider_type,
      model_type: provider.model_types[0] ?? "LLM",
    }
  }

  async function selectFirstBaseModel(providerCode: string, modelType: string) {
    const models = await loadBaseModels(providerCode, modelType)
    const baseModel = models[0]
    if (!baseModel) {
      return
    }
    setModelForm((current) =>
      current.provider === providerCode && current.model_type === modelType
        ? {
            ...current,
            name: baseModel.desc || baseModel.name,
            model_name: baseModel.name,
          }
        : current
    )
  }

  function openCreateModel() {
    setIsProviderPickerOpen(true)
  }

  function openCreateModelForProvider(providerCode: string) {
    const provider = providerCatalog.find(
      (item) => item.provider === providerCode
    )
    const nextForm = formForProvider(provider)
    setModelForm(nextForm)
    setBaseModels([])
    setCredentialFields([])
    setIsProviderPickerOpen(false)
    setIsDialogOpen(true)
    void selectFirstBaseModel(nextForm.provider, nextForm.model_type)
    void loadCredentialFields(nextForm.provider)
  }

  function openEditModel(model: RegisteredModel) {
    setModelForm({
      id: model.id,
      name: model.name,
      provider: model.provider,
      provider_type: model.provider_type,
      model_type: model.model_type,
      model_name: model.model_name,
      credential: {},
      credential_hints: {},
      status: model.status,
    })
    setCredentialFields([])
    setIsProviderPickerOpen(false)
    setIsDialogOpen(true)
    void loadBaseModels(model.provider, model.model_type)
    void loadCredentialFields(model.provider, model.credential)
  }

  function selectProvider(providerCode: string) {
    const provider = providerCatalog.find(
      (item) => item.provider === providerCode
    )
    const modelType = provider?.model_types[0] ?? "LLM"
    setModelForm((current) => ({
      ...current,
      name: "",
      provider: providerCode,
      provider_type: provider?.provider_type ?? "openai_compatible",
      model_type: modelType,
      model_name: "",
      credential: {},
      credential_hints: {},
    }))
    setCredentialFields([])
    void selectFirstBaseModel(providerCode, modelType)
    void loadCredentialFields(providerCode)
  }

  function selectModelType(modelType: string) {
    const providerCode = modelForm.provider
    setModelForm((current) => ({
      ...current,
      name: "",
      model_type: modelType,
      model_name: "",
    }))
    void selectFirstBaseModel(providerCode, modelType)
  }

  async function handleModelSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token || !selectedWorkspaceId) {
      return
    }

    const credential = Object.fromEntries(
      credentialFields.flatMap((field) => {
        const value = modelForm.credential[field.field] ?? ""
        return field.input_type === "PasswordInput" && !value.trim()
          ? []
          : [[field.field, value]]
      })
    )
    const payload = {
      name: modelForm.name,
      provider: modelForm.provider,
      provider_type: modelForm.provider_type,
      model_type: modelForm.model_type,
      model_name: modelForm.model_name,
      credential,
      status: modelForm.status,
      meta: {},
    }

    setIsSaving(true)
    try {
      if (modelForm.id) {
        const model = await updateRegisteredModel(
          token,
          selectedWorkspaceId,
          modelForm.id,
          payload
        )
        setModels((current) =>
          current.map((item) => (item.id === model.id ? model : item))
        )
        notify("success", t("模型测试通过，模型已更新"))
      } else {
        const model = await createRegisteredModel(
          token,
          selectedWorkspaceId,
          payload
        )
        setModels((current) => [...current, model])
        notify("success", t("模型测试通过，模型已添加"))
      }
      setIsDialogOpen(false)
      setIsProviderPickerOpen(false)
      setModelForm(EMPTY_MODEL_FORM)
      setBaseModels([])
      setCredentialFields([])
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDeleteModel(model: RegisteredModel) {
    if (!token || !selectedWorkspaceId) {
      return
    }
    if (!window.confirm(t("删除模型 {value}？", { value: model.name }))) {
      return
    }

    try {
      await deleteRegisteredModel(token, selectedWorkspaceId, model.id)
      setModels((current) => current.filter((item) => item.id !== model.id))
      notify("success", t("模型已删除"))
    } catch (error) {
      reportError(error)
    }
  }

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold">{t("模型")}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {t("按模型维度接入供应商、基础模型和访问凭据。")}
          </p>
        </div>
        {canManage ? (
          <Button type="button" className="shrink-0" onClick={openCreateModel}>
            <PlusIcon data-icon="inline-start" />
            {t("接入模型")}
          </Button>
        ) : null}
      </div>

      {!selectedWorkspaceId ? (
        <EmptyState
          icon={BrainCircuitIcon}
          title={t("未选择工作空间")}
          description={t("选择工作空间后管理可被应用和 Agent 调用的模型。")}
        />
      ) : (
        <>
          <section className="rounded-lg border bg-background p-3 shadow-sm">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="relative min-w-0 lg:w-[320px]">
                <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  className="pl-9"
                  placeholder={t("搜索模型、供应商或 API URL...")}
                />
              </div>
              <div className="flex items-center gap-2">
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-9 w-36 justify-between px-3 font-normal"
                    >
                      <span className="min-w-0 flex-1 truncate text-left">
                        {selectedProvider
                          ? providerLabel(providerCatalog, selectedProvider)
                          : t("全部供应商")}
                      </span>
                      <ChevronDownIcon data-icon="inline-end" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="end"
                    className="max-h-72 w-(--radix-dropdown-menu-trigger-width) min-w-0 overflow-y-auto"
                  >
                    <DropdownMenuItem
                      className="justify-between"
                      onSelect={() => setSelectedProvider("")}
                    >
                      {t("全部供应商")}
                      {!selectedProvider ? (
                        <CircleCheckIcon className="text-primary" />
                      ) : null}
                    </DropdownMenuItem>
                    {providerCatalog.map((provider) => (
                      <DropdownMenuItem
                        key={provider.provider}
                        className="justify-between"
                        onSelect={() => setSelectedProvider(provider.provider)}
                      >
                        <span className="min-w-0 truncate">
                          {provider.name}
                        </span>
                        {selectedProvider === provider.provider ? (
                          <CircleCheckIcon className="text-primary" />
                        ) : null}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
                {isCatalogLoading ? (
                  <LoaderCircleIcon className="mt-2 size-4 animate-spin text-muted-foreground" />
                ) : null}
              </div>
            </div>
          </section>

          <section>
            {isModelsLoading ? (
              <div className="flex min-h-[280px] items-center justify-center">
                <LoaderCircleIcon className="animate-spin text-muted-foreground" />
              </div>
            ) : visibleModels.length > 0 ? (
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                {visibleModels.map((model) => {
                  const provider = providerCatalog.find(
                    (item) => item.provider === model.provider
                  )

                  return (
                    <div
                      key={model.id}
                      className="flex min-h-40 flex-col rounded-md border p-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex min-w-0 gap-3">
                          <ProviderIcon
                            provider={provider}
                            label={providerLabel(
                              providerCatalog,
                              model.provider
                            )}
                            frameClassName="size-9"
                            imageClassName="max-h-6 max-w-6"
                          />
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <h2 className="truncate text-sm font-semibold">
                                {model.name}
                              </h2>
                              <StatusBadge status={model.status} />
                              <Badge variant="outline">
                                {modelTypeLabel(model.model_type, t)}
                              </Badge>
                            </div>
                            <p className="mt-1 flex items-center gap-1.5 truncate text-sm text-muted-foreground">
                              <span className="shrink-0">
                                {providerLabel(
                                  providerCatalog,
                                  model.provider
                                )}
                              </span>
                              <span className="shrink-0">·</span>
                              <ModelIcon
                                model={model.model_name}
                                size={14}
                                type="color"
                                className="shrink-0"
                              />
                              <span className="truncate">
                                {model.model_name}
                              </span>
                            </p>
                          </div>
                        </div>
                        {canManage ? (
                          <IconButton
                            label={t("编辑")}
                            onClick={() => openEditModel(model)}
                          >
                            <PencilIcon className="size-4" />
                          </IconButton>
                        ) : null}
                      </div>

                      <div className="mt-auto flex items-end justify-between gap-2 pt-4">
                        <dl className="grid min-w-0 flex-1 gap-3 text-sm sm:grid-cols-2">
                          <Spec
                            label={t("连接地址")}
                            value={model.api_base || t("默认连接")}
                          />
                          <Spec
                            label={t("访问凭据")}
                            value={
                              model.api_key_hint ??
                              t(
                                model.provider_type === "bedrock"
                                  ? "环境凭据"
                                  : "无需密钥"
                              )
                            }
                          />
                        </dl>
                        {canManage ? (
                          <CardMoreMenu label={t("更多")}>
                            <DropdownMenuItem
                              variant="destructive"
                              onSelect={() => void handleDeleteModel(model)}
                            >
                              <Trash2Icon />
                              {t("删除模型")}
                            </DropdownMenuItem>
                          </CardMoreMenu>
                        ) : null}
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <EmptyState
                icon={BrainCircuitIcon}
                title={t("还没有模型")}
                description={t("接入模型后，应用可以使用它进行对话、检索增强和工具调用。")}
                action={
                  canManage ? (
                    <Button type="button" onClick={openCreateModel}>
                      <PlusIcon data-icon="inline-start" />
                      {t("接入模型")}
                    </Button>
                  ) : null
                }
              />
            )}
          </section>
        </>
      )}

      <ProviderPickerDialog
        providers={providerCatalog}
        open={isProviderPickerOpen}
        isLoading={isCatalogLoading}
        onOpenChange={setIsProviderPickerOpen}
        onSelect={openCreateModelForProvider}
      />

      <ModelDialog
        form={modelForm}
        providerCatalog={providerCatalog}
        baseModels={baseModels}
        credentialFields={credentialFields}
        open={isDialogOpen}
        isSaving={isSaving}
        isBaseModelsLoading={isBaseModelsLoading}
        isCredentialFieldsLoading={isCredentialFieldsLoading}
        onOpenChange={setIsDialogOpen}
        onFormChange={setModelForm}
        onProviderChange={selectProvider}
        onModelTypeChange={selectModelType}
        onSubmit={handleModelSubmit}
      />
    </>
  )
}

function ProviderPickerDialog({
  providers,
  open,
  isLoading,
  onOpenChange,
  onSelect,
}: {
  providers: ModelProviderCatalog[]
  open: boolean
  isLoading: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (provider: string) => void
}) {
  const { t } = useLanguage()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("选择供应商")}</DialogTitle>
          <DialogDescription>{t("选择后继续填写模型和凭据。")}</DialogDescription>
        </DialogHeader>

        <div className="max-h-[56svh] overflow-auto pr-1">
          {isLoading ? (
            <div className="flex min-h-48 items-center justify-center">
              <LoaderCircleIcon className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : providers.length > 0 ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {providers.map((provider) => (
                <button
                  key={provider.provider}
                  type="button"
                  className="flex min-h-14 items-center gap-3 rounded-md border bg-background px-3 text-left shadow-sm transition hover:border-primary/50 hover:bg-muted/30 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
                  onClick={() => onSelect(provider.provider)}
                >
                  <ProviderIcon
                    provider={provider}
                    label={provider.name}
                    frameClassName="size-8"
                    imageClassName="max-h-6 max-w-6"
                  />
                  <span className="min-w-0 truncate text-sm font-semibold">
                    {provider.name}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div className="flex min-h-48 items-center justify-center text-sm text-muted-foreground">
              {t("暂无可用供应商")}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ProviderIcon({
  provider,
  label,
  frameClassName,
  imageClassName,
}: {
  provider: ModelProviderCatalog | undefined
  label: string
  frameClassName: string
  imageClassName: string
}) {
  const brand = provider ? PROVIDER_BRAND_ICONS[provider.provider] : undefined

  if (brand) {
    const Brand = brand.Color ?? brand.Render
    return (
      <span
        className={`flex shrink-0 items-center justify-center rounded-md border bg-white ${frameClassName}`}
      >
        <Brand size={24} className="object-contain" />
      </span>
    )
  }

  if (provider?.icon) {
    return (
      <span
        className={`flex shrink-0 items-center justify-center rounded-md border bg-white ${frameClassName}`}
      >
        {/* Local SVGs are already lightweight; next/image would add client bundle cost. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={provider.icon}
          alt=""
          width={24}
          height={24}
          className={`object-contain ${imageClassName}`}
          loading="lazy"
          decoding="async"
        />
      </span>
    )
  }

  return (
    <span
      className={`flex shrink-0 items-center justify-center rounded-md bg-muted text-xs font-semibold ${frameClassName}`}
    >
      {label.slice(0, 2)}
    </span>
  )
}

function ModelDialog({
  form,
  providerCatalog,
  baseModels,
  credentialFields,
  open,
  isSaving,
  isBaseModelsLoading,
  isCredentialFieldsLoading,
  onOpenChange,
  onFormChange,
  onProviderChange,
  onModelTypeChange,
  onSubmit,
}: {
  form: ModelForm
  providerCatalog: ModelProviderCatalog[]
  baseModels: BaseModelOption[]
  credentialFields: ModelCredentialField[]
  open: boolean
  isSaving: boolean
  isBaseModelsLoading: boolean
  isCredentialFieldsLoading: boolean
  onOpenChange: (open: boolean) => void
  onFormChange: (form: ModelForm) => void
  onProviderChange: (provider: string) => void
  onModelTypeChange: (modelType: string) => void
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void
}) {
  const { t } = useLanguage()
  const isEditing = Boolean(form.id)
  const selectedProvider = providerCatalog.find(
    (provider) => provider.provider === form.provider
  )
  const modelTypeOptions = selectedProvider?.model_types ?? ["LLM"]
  const firstBaseModel = baseModels[0]

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent side="right">
        <DialogHeader>
          <DialogTitle>{t(isEditing ? "编辑模型" : "接入模型")}</DialogTitle>
          <DialogDescription>
            {t("选择供应商和基础模型，填写连接参数；保存前会测试模型调用。")}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit}>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="model-name">{t("名称")}</FieldLabel>
              <Input
                id="model-name"
                value={form.name}
                onChange={(event) =>
                  onFormChange({ ...form, name: event.target.value })
                }
                placeholder={
                  firstBaseModel?.desc ?? selectedProvider?.name ?? t("模型名称")
                }
                maxLength={120}
                required
              />
              <FieldDescription>{t("应用内显示的模型名称。")}</FieldDescription>
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="model-provider">{t("供应商")}</FieldLabel>
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      id="model-provider"
                      type="button"
                      variant="outline"
                      className="h-9 w-full justify-between px-3 font-normal"
                      disabled={!providerCatalog.length}
                    >
                      <span className="min-w-0 flex-1 truncate text-left">
                        {selectedProvider?.name ?? t("选择供应商")}
                      </span>
                      <ChevronDownIcon data-icon="inline-end" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="start"
                    className="max-h-72 w-(--radix-dropdown-menu-trigger-width) overflow-y-auto"
                  >
                    {providerCatalog.map((provider) => (
                      <DropdownMenuItem
                        key={provider.provider}
                        className="justify-between"
                        onSelect={() => onProviderChange(provider.provider)}
                      >
                        <span className="min-w-0 truncate">
                          {provider.name}
                        </span>
                        {provider.provider === form.provider ? (
                          <CircleCheckIcon className="text-primary" />
                        ) : null}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </Field>

              <Field>
                <FieldLabel htmlFor="model-type">{t("模型类型")}</FieldLabel>
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      id="model-type"
                      type="button"
                      variant="outline"
                      className="h-9 w-full justify-between px-3 font-normal"
                      disabled={!modelTypeOptions.length}
                    >
                      <span className="min-w-0 flex-1 truncate text-left">
                        {modelTypeLabel(form.model_type, t)}
                      </span>
                      <ChevronDownIcon data-icon="inline-end" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="start"
                    className="w-(--radix-dropdown-menu-trigger-width)"
                  >
                    {modelTypeOptions.map((modelType) => (
                      <DropdownMenuItem
                        key={modelType}
                        className="justify-between"
                        onSelect={() => onModelTypeChange(modelType)}
                      >
                        {modelTypeLabel(modelType, t)}
                        {modelType === form.model_type ? (
                          <CircleCheckIcon className="text-primary" />
                        ) : null}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </Field>
            </div>

            <Field>
              <FieldLabel htmlFor="base-model">{t("基础模型")}</FieldLabel>
              <Input
                id="base-model"
                value={form.model_name}
                onChange={(event) =>
                  onFormChange({ ...form, model_name: event.target.value })
                }
                list="base-model-options"
                placeholder={firstBaseModel?.name ?? t("输入模型名")}
                maxLength={160}
                required
              />
              <datalist id="base-model-options">
                {baseModels.map((model) => (
                  <option key={model.name} value={model.name}>
                    {model.desc}
                  </option>
                ))}
              </datalist>
              <FieldDescription>
                {isBaseModelsLoading
                  ? t("正在加载基础模型...")
                  : t("可以从列表选择，也可以直接输入未列出的模型名。")}
              </FieldDescription>
            </Field>

            {isCredentialFieldsLoading ? (
              <div className="flex h-20 items-center justify-center">
                <LoaderCircleIcon
                  className="size-4 animate-spin text-muted-foreground"
                  aria-label={t("正在加载连接配置...")}
                />
              </div>
            ) : (
              credentialFields.map((field) => {
                const isSecret = field.input_type === "PasswordInput"
                const hint = form.credential_hints[field.field]
                const labelKey =
                  CREDENTIAL_FIELD_LABELS[field.field] ?? "访问凭据"
                return (
                  <Field key={field.field}>
                    <FieldLabel htmlFor={`credential-${field.field}`}>
                      {t(labelKey)}
                    </FieldLabel>
                    <Input
                      id={`credential-${field.field}`}
                      type={isSecret ? "password" : "text"}
                      value={form.credential[field.field] ?? ""}
                      onChange={(event) =>
                        onFormChange({
                          ...form,
                          credential: {
                            ...form.credential,
                            [field.field]: event.target.value,
                          },
                        })
                      }
                      placeholder={
                        isSecret && isEditing && hint
                          ? t("留空则保留当前凭据")
                          : String(field.default_value ?? "")
                      }
                      required={field.required && !(isSecret && Boolean(hint))}
                    />
                    {isSecret ? (
                      <FieldDescription>
                        {isEditing && hint
                          ? t("当前凭据：{value}", { value: hint })
                          : t("保存后只显示脱敏尾号，不会返回明文。")}
                      </FieldDescription>
                    ) : null}
                  </Field>
                )
              })
            )}

            {isEditing ? (
              <Field>
                <FieldLabel htmlFor="model-status">{t("状态")}</FieldLabel>
                <select
                  id="model-status"
                  className="h-9 rounded-md border bg-background px-3 text-sm"
                  value={form.status}
                  onChange={(event) =>
                    onFormChange({ ...form, status: event.target.value })
                  }
                >
                  <option value="active">{t("已启用")}</option>
                  <option value="disabled">{t("已停用")}</option>
                </select>
              </Field>
            ) : null}
          </FieldGroup>

          <DialogFooter className="pt-5">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              {t("取消")}
            </Button>
            <Button type="submit" disabled={isSaving}>
              {isSaving
                ? t("测试并保存中...")
                : isEditing
                  ? t("保存")
                  : t("接入模型")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: typeof BrainCircuitIcon
  title: string
  description: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex min-h-[260px] flex-col items-center justify-center gap-4 text-center">
      <span className="flex size-12 items-center justify-center rounded-lg bg-muted">
        <Icon className="size-5 text-muted-foreground" />
      </span>
      <div className="flex flex-col gap-2">
        <p className="text-sm font-semibold">{title}</p>
        <p className="max-w-md text-sm leading-6 text-muted-foreground">
          {description}
        </p>
      </div>
      {action}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useLanguage()
  return (
    <Badge variant={status === "active" ? "secondary" : "outline"}>
      {t(status === "active" ? "已启用" : "已停用")}
    </Badge>
  )
}

function providerLabel(providers: ModelProviderCatalog[], value: string) {
  return (
    providers.find((provider) => provider.provider === value)?.name ?? value
  )
}

function modelTypeLabel(value: string, t: TFunction) {
  const labelKey = MODEL_TYPE_LABELS[value]
  return labelKey ? t(labelKey) : value
}

function providerDisplayIndex(provider: string) {
  const index = PROVIDER_DISPLAY_ORDER.indexOf(provider)
  return index === -1 ? PROVIDER_DISPLAY_ORDER.length : index
}
