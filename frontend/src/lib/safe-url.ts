const CSV_FORMULA_PREFIX_RE = /^[=+\-@\t\r]/

export function isSafeHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value)
    return parsed.protocol === "http:" || parsed.protocol === "https:"
  } catch {
    return false
  }
}

export function isSafeNavigationUrl(value: string): boolean {
  if (!value) {
    return false
  }
  if (value.startsWith("/") && !value.startsWith("//")) {
    return !/[\\\r\n]/.test(value)
  }
  return isSafeHttpUrl(value)
}

export function escapeCsvCell(value: string): string {
  const safe = CSV_FORMULA_PREFIX_RE.test(value) ? `'${value}` : value
  return `"${safe.replaceAll('"', '""')}"`
}
