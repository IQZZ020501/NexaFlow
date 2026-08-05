import { request } from "@/lib/api-client"

export type ModelProviderCatalog = {
  provider: string
  name: string
  provider_type: string
  icon: string
  model_types: string[]
  default_api_base: string
}

export type BaseModelOption = {
  name: string
  desc: string
  model_type: string
}

export type ModelCredentialField = {
  field: string
  label: string
  input_type: string
  required: boolean
  default_value: unknown
}

export type RegisteredModel = {
  id: string
  workspace_id: string
  name: string
  provider: string
  provider_type: string
  model_type: string
  model_name: string
  status: string
  credential: Record<string, unknown>
  api_base: string
  has_api_key: boolean
  api_key_hint: string | null
  meta: Record<string, unknown>
  created_by_user_id: string
  created_at: string
  updated_at: string
}

export type RegisteredModelPayload = {
  name: string
  provider: string
  provider_type: string
  model_type: string
  model_name: string
  credential: Record<string, unknown>
  meta?: Record<string, unknown>
  status?: string
}

export function listModelProviderCatalog(token: string, modelType?: string) {
  const query = modelType ? `?model_type=${encodeURIComponent(modelType)}` : ""
  return request<ModelProviderCatalog[]>(`/api/v1/model-providers${query}`, {
    token,
  })
}

export type ModelTypeOption = {
  key: string
  value: string
}

export function listModelProviderModelTypes(token: string, provider: string) {
  return request<ModelTypeOption[]>(
    `/api/v1/model-providers/model-types?provider=${encodeURIComponent(provider)}`,
    { token }
  )
}

export function listModelProviderBaseModels(
  token: string,
  provider: string,
  modelType: string
) {
  return request<BaseModelOption[]>(
    `/api/v1/model-providers/base-models?provider=${encodeURIComponent(provider)}&model_type=${encodeURIComponent(modelType)}`,
    { token }
  )
}

export function getModelProviderForm(token: string, provider: string) {
  return request<ModelCredentialField[]>(
    `/api/v1/model-providers/credential-form?provider=${encodeURIComponent(provider)}`,
    { token }
  )
}

export function listRegisteredModels(token: string, workspaceId: string) {
  return request<RegisteredModel[]>(`/api/v1/workspaces/${workspaceId}/models`, {
    token,
  })
}

export function createRegisteredModel(
  token: string,
  workspaceId: string,
  payload: RegisteredModelPayload
) {
  return request<RegisteredModel>(`/api/v1/workspaces/${workspaceId}/models`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  })
}

export function updateRegisteredModel(
  token: string,
  workspaceId: string,
  modelId: string,
  payload: Partial<RegisteredModelPayload>
) {
  return request<RegisteredModel>(
    `/api/v1/workspaces/${workspaceId}/models/${modelId}`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify(payload),
    }
  )
}

export function deleteRegisteredModel(
  token: string,
  workspaceId: string,
  modelId: string
) {
  return request<void>(`/api/v1/workspaces/${workspaceId}/models/${modelId}`, {
    method: "DELETE",
    token,
  })
}
