import * as React from "react"
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
import { getMembershipRole } from "@/app/display"
import { getErrorMessage } from "@/app/errors"
import type { AppNotification } from "@/app/notifications"
import { useLanguage } from "@/components/language-provider"
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
import {
  createRegisteredModel,
  deleteRegisteredModel,
  listModelProviderBaseModels,
  listModelProviderCatalog,
  listRegisteredModels,
  type BaseModelOption,
  type MeResponse,
  type ModelProviderCatalog,
  type RegisteredModel,
  updateRegisteredModel,
} from "@/lib/api"
import type { FeaturePageConfig } from "@/lib/pages"

const MODEL_TYPE_LABELS: Record<string, string> = {
  LLM: "大语言模型",
  EMBEDDING: "向量模型",
  RERANKER: "重排模型",
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

type ModelForm = {
  id: string | null
  name: string
  provider: string
  provider_type: string
  model_type: string
  model_name: string
  api_base: string
  api_key: string
  api_key_hint: string
  status: string
}

const EMPTY_MODEL_FORM: ModelForm = {
  id: null,
  name: "",
  provider: "",
  provider_type: "openai_compatible",
  model_type: "LLM",
  model_name: "",
  api_base: "",
  api_key: "",
  api_key_hint: "",
  status: "active",
}

export function ModelRegistryPage({
  page,
  token,
  me,
  selectedWorkspaceId,
  onNotify,
}: {
  page: FeaturePageConfig
  token: string
  me: MeResponse
  selectedWorkspaceId: string | null
  onNotify: (kind: AppNotification["kind"], message: string) => void
}) {
  const { t } = useLanguage()
  const [providerCatalog, setProviderCatalog] = React.useState<
    ModelProviderCatalog[]
  >([])
  const [models, setModels] = React.useState<RegisteredModel[]>([])
  const [baseModels, setBaseModels] = React.useState<BaseModelOption[]>([])
  const [selectedProvider, setSelectedProvider] = React.useState("")
  const [search, setSearch] = React.useState("")
  const [modelForm, setModelForm] = React.useState<ModelForm>(EMPTY_MODEL_FORM)
  const [error, setError] = React.useState<string | null>(null)
  const [isCatalogLoading, setIsCatalogLoading] = React.useState(false)
  const [isModelsLoading, setIsModelsLoading] = React.useState(false)
  const [isBaseModelsLoading, setIsBaseModelsLoading] = React.useState(false)
  const [isSaving, setIsSaving] = React.useState(false)
  const [isDialogOpen, setIsDialogOpen] = React.useState(false)
  const [isProviderPickerOpen, setIsProviderPickerOpen] = React.useState(false)

  const workspaceRole = getMembershipRole(me, selectedWorkspaceId)
  const canManage = workspaceRole === "admin"

  const reportError = React.useCallback(
    (error: unknown) => {
      const message = getErrorMessage(error, t)
      setError(message)
      onNotify("error", message)
      return message
    },
    [onNotify, t]
  )

  const loadProviderCatalog = React.useCallback(async () => {
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
    if (!selectedWorkspaceId) {
      setModels([])
      return
    }

    setError(null)
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
      api_base: provider.default_api_base,
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
    setIsProviderPickerOpen(false)
    setIsDialogOpen(true)
    void selectFirstBaseModel(nextForm.provider, nextForm.model_type)
  }

  function openEditModel(model: RegisteredModel) {
    setModelForm({
      id: model.id,
      name: model.name,
      provider: model.provider,
      provider_type: model.provider_type,
      model_type: model.model_type,
      model_name: model.model_name,
      api_base: String(model.credential.api_base ?? model.api_base),
      api_key: "",
      api_key_hint: model.api_key_hint ?? "",
      status: model.status,
    })
    setIsProviderPickerOpen(false)
    setIsDialogOpen(true)
    void loadBaseModels(model.provider, model.model_type)
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
      api_base: provider?.default_api_base ?? current.api_base,
    }))
    void selectFirstBaseModel(providerCode, modelType)
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
    if (!selectedWorkspaceId) {
      return
    }

    const payload = {
      name: modelForm.name,
      provider: modelForm.provider,
      provider_type: modelForm.provider_type,
      model_type: modelForm.model_type,
      model_name: modelForm.model_name,
      credential: {
        api_base: modelForm.api_base,
        ...(modelForm.api_key.trim() ? { api_key: modelForm.api_key } : {}),
      },
      status: modelForm.status,
      meta: {},
    }

    setIsSaving(true)
    setError(null)
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
        onNotify("success", "模型测试通过，模型已更新")
      } else {
        const model = await createRegisteredModel(
          token,
          selectedWorkspaceId,
          payload
        )
        setModels((current) => [...current, model])
        onNotify("success", "模型测试通过，模型已添加")
      }
      setIsDialogOpen(false)
      setIsProviderPickerOpen(false)
      setModelForm(EMPTY_MODEL_FORM)
      setBaseModels([])
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDeleteModel(model: RegisteredModel) {
    if (!selectedWorkspaceId) {
      return
    }
    if (!window.confirm(`删除模型 ${model.name}？`)) {
      return
    }

    setError(null)
    try {
      await deleteRegisteredModel(token, selectedWorkspaceId, model.id)
      setModels((current) => current.filter((item) => item.id !== model.id))
      onNotify("success", "模型已删除")
    } catch (error) {
      reportError(error)
    }
  }

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold">{page.label}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            按模型维度接入供应商、基础模型和 API Key，保存前会先测试真实调用。
          </p>
        </div>
        {canManage ? (
          <Button type="button" className="shrink-0" onClick={openCreateModel}>
            <PlusIcon data-icon="inline-start" />
            {page.actionLabel}
          </Button>
        ) : null}
      </div>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {!selectedWorkspaceId ? (
        <EmptyState
          icon={BrainCircuitIcon}
          title="未选择工作空间"
          description="选择工作空间后管理可被应用和 Agent 调用的模型。"
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
                  placeholder="搜索模型、供应商或 API URL..."
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
                          : "全部供应商"}
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
                      全部供应商
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

          <section className="rounded-lg border bg-background p-4 shadow-sm">
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
                    <div key={model.id} className="rounded-md border p-3">
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
                                {modelTypeLabel(model.model_type)}
                              </Badge>
                            </div>
                            <p className="mt-1 truncate text-sm text-muted-foreground">
                              {providerLabel(providerCatalog, model.provider)} ·{" "}
                              {model.model_name}
                            </p>
                          </div>
                        </div>
                        {canManage ? (
                          <div className="flex gap-1">
                            <IconButton
                              label="编辑"
                              onClick={() => openEditModel(model)}
                            >
                              <PencilIcon className="size-4" />
                            </IconButton>
                            <IconButton
                              label="删除"
                              onClick={() => void handleDeleteModel(model)}
                            >
                              <Trash2Icon className="size-4" />
                            </IconButton>
                          </div>
                        ) : null}
                      </div>

                      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                        <Spec label="API URL" value={model.api_base} />
                        <Spec
                          label="API Key"
                          value={model.api_key_hint ?? "未配置"}
                        />
                      </dl>
                    </div>
                  )
                })}
              </div>
            ) : (
              <EmptyState
                icon={BrainCircuitIcon}
                title={page.emptyTitle}
                description="添加模型后，应用和 Agent 才能选择它进行对话、检索增强和工具调用。"
                action={
                  canManage ? (
                    <Button type="button" onClick={openCreateModel}>
                      <PlusIcon data-icon="inline-start" />
                      {page.actionLabel}
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
        open={isDialogOpen}
        isSaving={isSaving}
        isBaseModelsLoading={isBaseModelsLoading}
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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>选择供应商</DialogTitle>
          <DialogDescription>选择后继续填写模型和凭据。</DialogDescription>
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
              暂无可用供应商
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
  if (provider?.icon) {
    return (
      <span
        className={`flex shrink-0 items-center justify-center rounded-md border bg-white ${frameClassName}`}
      >
        <img
          src={provider.icon}
          alt=""
          className={`object-contain ${imageClassName}`}
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
  open,
  isSaving,
  isBaseModelsLoading,
  onOpenChange,
  onFormChange,
  onProviderChange,
  onModelTypeChange,
  onSubmit,
}: {
  form: ModelForm
  providerCatalog: ModelProviderCatalog[]
  baseModels: BaseModelOption[]
  open: boolean
  isSaving: boolean
  isBaseModelsLoading: boolean
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
          <DialogTitle>{isEditing ? "编辑模型" : t("接入模型")}</DialogTitle>
          <DialogDescription>
            选择供应商和基础模型，填写 API URL 与 API
            Key；保存前会测试模型调用。
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit}>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="model-name">名称</FieldLabel>
              <Input
                id="model-name"
                value={form.name}
                onChange={(event) =>
                  onFormChange({ ...form, name: event.target.value })
                }
                placeholder={
                  firstBaseModel?.desc ?? selectedProvider?.name ?? "模型名称"
                }
                maxLength={120}
                required
              />
              <FieldDescription>应用内显示的模型名称。</FieldDescription>
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="model-provider">供应商</FieldLabel>
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
                        {selectedProvider?.name ?? "选择供应商"}
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
                <FieldLabel htmlFor="model-type">模型类型</FieldLabel>
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
                        {modelTypeLabel(form.model_type)}
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
                        {modelTypeLabel(modelType)}
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
              <FieldLabel htmlFor="base-model">基础模型</FieldLabel>
              <Input
                id="base-model"
                value={form.model_name}
                onChange={(event) =>
                  onFormChange({ ...form, model_name: event.target.value })
                }
                list="base-model-options"
                placeholder={firstBaseModel?.name ?? "输入模型名"}
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
                  ? "正在加载基础模型..."
                  : "可以从列表选择，也可以直接输入未列出的模型名。"}
              </FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="api-base">API URL</FieldLabel>
              <Input
                id="api-base"
                value={form.api_base}
                onChange={(event) =>
                  onFormChange({ ...form, api_base: event.target.value })
                }
                placeholder="https://api.deepseek.com"
                required
              />
            </Field>

            <Field>
              <FieldLabel htmlFor="api-key">API Key</FieldLabel>
              <Input
                id="api-key"
                type="password"
                value={form.api_key}
                onChange={(event) =>
                  onFormChange({ ...form, api_key: event.target.value })
                }
                placeholder={isEditing ? "留空则保留当前 API Key" : "sk-..."}
                required={!isEditing}
              />
              <FieldDescription>
                {isEditing && form.api_key_hint
                  ? `当前密钥：${form.api_key_hint}`
                  : "保存后只显示脱敏尾号，不会返回明文。"}
              </FieldDescription>
            </Field>

            {isEditing ? (
              <Field>
                <FieldLabel htmlFor="model-status">状态</FieldLabel>
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
                ? "测试并保存中..."
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

function IconButton({
  label,
  children,
  onClick,
}: {
  label: string
  children: React.ReactNode
  onClick: (event: React.MouseEvent<HTMLButtonElement>) => void
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      title={label}
      onClick={onClick}
    >
      {children}
      <span className="sr-only">{label}</span>
    </Button>
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
  return (
    <Badge variant={status === "active" ? "secondary" : "outline"}>
      {status === "active" ? "已启用" : "已停用"}
    </Badge>
  )
}

function Spec({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 truncate font-medium" title={value}>
        {value}
      </dd>
    </div>
  )
}

function providerLabel(providers: ModelProviderCatalog[], value: string) {
  return (
    providers.find((provider) => provider.provider === value)?.name ?? value
  )
}

function modelTypeLabel(value: string) {
  return MODEL_TYPE_LABELS[value] ?? value
}

function providerDisplayIndex(provider: string) {
  const index = PROVIDER_DISPLAY_ORDER.indexOf(provider)
  return index === -1 ? PROVIDER_DISPLAY_ORDER.length : index
}
