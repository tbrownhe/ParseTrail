import { ApiError } from "./core/ApiError"
import { client } from "./generated/client.gen"

client.setConfig({
  auth: () => localStorage.getItem("access_token") ?? "",
  baseUrl: import.meta.env.VITE_API_URL,
  responseStyle: "data",
  throwOnError: true,
})

client.interceptors.error.use((error, response, request) => {
  const apiError =
    error instanceof ApiError ? error : new ApiError(error, response, request)
  if (apiError.status === 401 && localStorage.getItem("access_token")) {
    localStorage.removeItem("access_token")
    if (window.location.pathname !== "/login") {
      window.location.assign("/login")
    }
  }
  return apiError
})

export type * from "./generated/types.gen"
export type { BodyLoginLoginAccessToken as Body_login_login_access_token } from "./generated/types.gen"
export * from "./services"
export { ApiError, client }
