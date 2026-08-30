import { apiBaseUrl } from "../config"
import { ApiError } from "./core/ApiError"
import { client } from "./generated/client.gen"

client.setConfig({
  baseUrl: apiBaseUrl,
  credentials: "include",
  responseStyle: "data",
  throwOnError: true,
})

client.interceptors.error.use((error, response, request) => {
  const apiError =
    error instanceof ApiError ? error : new ApiError(error, response, request)
  const publicPaths = new Set([
    "/login",
    "/signup",
    "/recover-password",
    "/reset-password",
    "/verify-email",
  ])
  if (apiError.status === 401 && !publicPaths.has(window.location.pathname)) {
    window.location.assign("/login")
  }
  return apiError
})

export type * from "./generated/types.gen"
export * from "./services"
export { ApiError, client }
