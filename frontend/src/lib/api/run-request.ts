import { ApiError, request, type RequestOptions } from "@/lib/api-client"

/** Keep one client identity across an ambiguous transport failure. */
export async function requestRun<T>(
  path: string,
  payload: Record<string, unknown>,
  options: RequestOptions
) {
  const body = JSON.stringify({
    ...payload,
    request_id: payload.request_id ?? crypto.randomUUID(),
  })
  const send = () => request<T>(path, { ...options, method: "POST", body })
  try {
    return await send()
  } catch (error) {
    if (
      options.signal?.aborted ||
      (error instanceof ApiError && error.status < 500)
    )
      throw error
    return send()
  }
}
