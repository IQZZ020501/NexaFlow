const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL ?? "http://localhost:8000"

export type RequestOptions = RequestInit & {
  token?: string
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`
}

function errorMessage(payload: unknown, fallback: string) {
  if (typeof payload === "string" && payload) {
    return payload
  }

  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail
    if (typeof detail === "string") {
      return detail
    }

    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg)
          }

          return String(item)
        })
        .join("; ")
    }
  }

  return fallback
}

export async function request<T>(path: string, options: RequestOptions = {}) {
  const headers = new Headers(options.headers)

  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }

  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`)
  }

  const response = await fetch(apiUrl(path), {
    ...options,
    headers,
  })

  if (response.status === 204) {
    if (!response.ok) {
      throw new ApiError(response.status, response.statusText)
    }

    return undefined as T
  }

  const text = await response.text()
  const payload = text ? JSON.parse(text) : null

  if (!response.ok) {
    throw new ApiError(response.status, errorMessage(payload, response.statusText))
  }

  return payload as T
}
