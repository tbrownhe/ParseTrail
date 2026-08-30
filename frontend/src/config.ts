declare global {
  interface Window {
    __PARSETRAIL_CONFIG__?: {
      apiBaseUrl?: unknown
    }
  }
}

function validateApiBaseUrl(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error("ParseTrail API URL is not configured")
  }

  const parsed = new URL(value)
  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error(
      "ParseTrail API URL must be an HTTP(S) URL without credentials, query, or fragment",
    )
  }

  if (parsed.pathname === "/") {
    // Preserve compatibility with the original local Vite setting.
    parsed.pathname = "/api/v1"
  }
  if (parsed.pathname.replace(/\/$/, "") !== "/api/v1") {
    throw new Error("ParseTrail API URL must end with /api/v1")
  }

  return parsed.href.replace(/\/$/, "")
}

const configuredApiBaseUrl =
  window.__PARSETRAIL_CONFIG__?.apiBaseUrl ??
  (import.meta.env.DEV ? import.meta.env.VITE_API_URL : undefined)

export const apiBaseUrl = validateApiBaseUrl(configuredApiBaseUrl)
