const errorMessage = (error: unknown, response?: Response): string => {
  if (error instanceof Error) {
    return error.message
  }
  if (typeof error === "object" && error !== null && "detail" in error) {
    const detail = error.detail
    if (typeof detail === "string") {
      return detail
    }
  }
  return response?.statusText || "API request failed"
}

export class ApiError extends Error {
  public readonly url: string
  public readonly status: number
  public readonly statusText: string
  public readonly body: unknown
  public readonly request?: Request

  constructor(error: unknown, response?: Response, request?: Request) {
    super(errorMessage(error, response))
    this.name = "ApiError"
    this.url = request?.url ?? ""
    this.status = response?.status ?? 0
    this.statusText = response?.statusText ?? ""
    this.body = error instanceof Error ? { detail: error.message } : error
    this.request = request
  }
}
