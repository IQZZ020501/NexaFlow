import { redirect } from "next/navigation"

/**
 * Redirects visitors to the system workspaces page.
 */
export default function SystemHome() {
  redirect("/system/workspaces")
}
