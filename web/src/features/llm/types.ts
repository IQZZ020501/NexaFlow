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
