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

/**
 * Builds an API URL by prefixing a path with the configured base URL.
 *
 * @param path - The API path to append
 * @returns The complete API URL
 */
export function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`
}

/**
 * Builds a query string from optional pagination parameters.
 *
 * @param options - Pagination values to include in the query string
 * @returns A query string beginning with `?`, or an empty string when no parameters are provided
 */
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

/**
 * Extracts a readable error message from an API response payload.
 *
 * @param payload - The response payload that may contain error details
 * @param fallback - The message to use when the payload has no readable error
 * @returns The extracted error message or the fallback message
 */
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

/**
 * Sends an API request and parses the successful response.
 *
 * @param path - The API path to request
 * @param options - Request settings, including an optional bearer token
 * @returns The parsed response value, `undefined` for a successful 204 response, or `null` for an empty response body
 * @throws `ApiError` when the response has an unsuccessful HTTP status
 */
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

export async function requestPage<T>(path: string, options: RequestOptions = {}) {
  const response = await fetch(apiUrl(path), {
    ...options,
    credentials: options.credentials ?? "include",
    headers: options.token
      ? new Headers({ ...Object.fromEntries(new Headers(options.headers)), Authorization: `Bearer ${options.token}` })
      : options.headers,
  })
  if (!response.ok) {
    const text = await response.text()
    let payload: unknown = text
    try { payload = text ? JSON.parse(text) : null } catch { /* plain text */ }
    throw new ApiError(response.status, errorMessage(payload, response.statusText))
  }
  return {
    items: await response.json() as T[],
    total: Number(response.headers.get("X-Total-Count") ?? 0),
  }
}


/**
 * Requests a resource and provides its successful response as a blob.
 *
 * @param path - The API path to request
 * @param options - Request configuration, including an optional bearer token
 * @returns The response body as a `Blob`
 */
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
