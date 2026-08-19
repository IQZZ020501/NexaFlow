import { redirect } from "next/navigation"

/**
 * Redirects visitors to the applications page.
 */
export default function PlatformHome() {
  redirect("/app/apps")
}
