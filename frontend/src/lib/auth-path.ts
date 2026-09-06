const DEFAULT_AUTH_DESTINATION = "/app/apps"

export function safeAuthDestination(value?: string) {
  if (
    !value ||
    value.length > 2048 ||
    !value.startsWith("/") ||
    value.startsWith("//")
  ) {
    return DEFAULT_AUTH_DESTINATION
  }

  for (const character of value) {
    const code = character.charCodeAt(0)
    if (
      character === "\\" ||
      /\s/u.test(character) ||
      code < 32 ||
      (code >= 127 && code <= 159)
    ) {
      return DEFAULT_AUTH_DESTINATION
    }
  }

  return value
}
