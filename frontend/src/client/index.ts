import { ApiError } from "./core/ApiError"
import { client } from "./generated/client.gen"

client.setConfig({
  auth: () => localStorage.getItem("access_token") ?? "",
  baseUrl: import.meta.env.VITE_API_URL,
  responseStyle: "data",
  throwOnError: true,
})

client.interceptors.error.use((error, response, request) => {
  if (error instanceof ApiError) {
    return error
  }
  return new ApiError(error, response, request)
})

export type * from "./generated/types.gen"
export type { BodyLoginLoginAccessToken as Body_login_login_access_token } from "./generated/types.gen"
export * from "./services"
export { ApiError, client }
