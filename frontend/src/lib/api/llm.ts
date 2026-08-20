import { listQuery, request } from "@/lib/api-client"

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

/**
 * Lists available model providers, optionally filtered by model type.
 *
 * @param token - Authentication token for the request
 * @param modelType - The model type used to filter the provider catalog.
 * @returns The matching model provider catalog entries.
 */
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

/**
 * Lists the model types supported by a model provider.
 *
 * @param token - Authentication token for the request
 * @param provider - The provider whose supported model types to retrieve
 * @returns The provider's supported model types
 */
export function listModelProviderModelTypes(token: string, provider: string) {
  return request<ModelTypeOption[]>(
    `/api/v1/model-providers/model-types?provider=${encodeURIComponent(provider)}`,
    { token }
  )
}

/**
 * Lists the base models available from a provider for a model type.
 *
 * @param token - Authentication token for the request
 * @param provider - The model provider identifier
 * @param modelType - The model type used to filter available models
 * @returns The provider's available base model options
 */
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

/**
 * Retrieves the credential form fields for a model provider.
 *
 * @param token - Authentication token for the request
 * @param provider - The provider whose credential fields to retrieve
 * @returns The provider's credential form field definitions
 */
export function getModelProviderForm(token: string, provider: string) {
  return request<ModelCredentialField[]>(
    `/api/v1/model-providers/credential-form?provider=${encodeURIComponent(provider)}`,
    { token }
  )
}

/**
 * Lists the models registered in a workspace.
 *
 * @param token - Authentication token for the request
 * @param workspaceId - The workspace whose registered models to retrieve
 * @param options - Optional pagination parameters
 * @returns The workspace's registered models
 */
export function listRegisteredModels(
  token: string,
  workspaceId: string,
  options: { limit?: number; offset?: number } = {},
) {
  return request<RegisteredModel[]>(
    `/api/v1/workspaces/${workspaceId}/models${listQuery(options)}`,
    { token },
  )
}

/**
 * Creates a registered model for a workspace.
 *
 * @param token - Authentication token for the request
 * @param workspaceId - The workspace that will own the model
 * @param payload - The model details to create
 * @returns The created registered model
 */
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

/**
 * Partially updates a registered model in a workspace.
 *
 * @param token - Authentication token for the request
 * @param workspaceId - The workspace containing the model
 * @param modelId - The identifier of the model to update
 * @param payload - The model fields to update
 * @returns The updated registered model
 */
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

/**
 * Deletes a registered model from a workspace.
 *
 * @param token - Authentication token for the request
 * @param workspaceId - The workspace containing the model
 * @param modelId - The registered model to delete
 */
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
