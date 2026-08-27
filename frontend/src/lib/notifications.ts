export type AppNotification = {
  id: number
  kind: "success" | "error" | "info"
  message: string
}
