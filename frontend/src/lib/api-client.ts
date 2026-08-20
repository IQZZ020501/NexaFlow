// Empty by default: the Next.js dev server proxies /api to the FastAPI
// backend. Set NEXT_PUBLIC_API_BASE_URL to point at the API for split hosting.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? ""

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

export function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`
}

export function listQuery(options: { limit?: number; offset?: number }): string {
  const params = new URLSearchParams()
  if (options.limit !== undefined) {
    params.set("limit", String(options.limit))
  }
  if (options.offset !== undefined) {
    params.set("offset", String(options.offset))
  }
  const query = params.toString()
  return query ? `?${query}` : ""
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

  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json")
  }

  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`)
  }

  const response = await fetch(apiUrl(path), {
    ...options,
    credentials: options.credentials ?? "include",
    headers,
  })

  if (response.status === 204) {
    if (!response.ok) {
      throw new ApiError(response.status, response.statusText)
    }

    return undefined as T
  }

  if (!response.ok) {
    const text = await response.text()
    let payload: unknown = text
    try {
      payload = text ? JSON.parse(text) : null
    } catch {
      // Keep the plain response body as the fallback message.
    }
    throw new ApiError(response.status, errorMessage(payload, response.statusText))
  }

  const text = await response.text()
  return (text ? JSON.parse(text) : null) as T
}


export async function requestBlob(
  path: string,
  options: RequestOptions = {},
) {
  const headers = new Headers(options.headers)
  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`)
  }
  const response = await fetch(apiUrl(path), {
    ...options,
    credentials: options.credentials ?? "include",
    headers,
  })
  if (!response.ok) {
    const text = await response.text()
    let payload: unknown = text
    try {
      payload = text ? JSON.parse(text) : null
    } catch {
      // Keep the plain response body as the fallback message.
    }
    throw new ApiError(
      response.status,
      errorMessage(payload, response.statusText),
    )
  }
  return response.blob()
}
