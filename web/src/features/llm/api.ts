import { request } from "@/lib/api-client"
import type {
  BaseModelOption,
  ModelCredentialField,
  ModelProviderCatalog,
  RegisteredModel,
  RegisteredModelPayload,
} from "@/features/llm/types"

export function listModelProviderCatalog(token: string, modelType?: string) {
  const query = modelType ? `?model_type=${encodeURIComponent(modelType)}` : ""
  return request<ModelProviderCatalog[]>(`/model-providers${query}`, { token })
}

export function listModelProviderModelTypes(token: string, provider: string) {
  return request<Array<{ key: string; value: string }>>(
    `/model-providers/model_type_list?provider=${encodeURIComponent(provider)}`,
    { token }
  )
}

export function listModelProviderBaseModels(
  token: string,
  provider: string,
  modelType: string
) {
  return request<BaseModelOption[]>(
    `/model-providers/model_list?provider=${encodeURIComponent(provider)}&model_type=${encodeURIComponent(modelType)}`,
    { token }
  )
}

export function getModelProviderForm(token: string, provider: string) {
  return request<ModelCredentialField[]>(
    `/model-providers/model_form?provider=${encodeURIComponent(provider)}`,
    { token }
  )
}

export function listRegisteredModels(token: string, workspaceId: string) {
  return request<RegisteredModel[]>(`/workspaces/${workspaceId}/models`, {
    token,
  })
}

export function createRegisteredModel(
  token: string,
  workspaceId: string,
  payload: RegisteredModelPayload
) {
  return request<RegisteredModel>(`/workspaces/${workspaceId}/models`, {
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
  return request<RegisteredModel>(`/workspaces/${workspaceId}/models/${modelId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  })
}

export function deleteRegisteredModel(
  token: string,
  workspaceId: string,
  modelId: string
) {
  return request<void>(`/workspaces/${workspaceId}/models/${modelId}`, {
    method: "DELETE",
    token,
  })
}
