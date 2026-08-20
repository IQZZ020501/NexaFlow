import { redirect } from "next/navigation"

/**
 * Redirects visitors from the home page to the applications page.
 */
export default function Home() {
  redirect("/app/apps")
}
