import { request } from "@/lib/api-client"
import type { LoginResponse, MeResponse } from "@/features/auth/types"

export function login(username: string, password: string) {
  return request<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({
      username,
      password,
    }),
  })
}

export function changePassword(
  token: string,
  newPassword: string,
  currentPassword?: string
) {
  return request<void>("/auth/change-password", {
    method: "POST",
    token,
    body: JSON.stringify({
      new_password: newPassword,
      current_password: currentPassword,
    }),
  })
}

export function getMe(token: string) {
  return request<MeResponse>("/auth/me", { token })
}
