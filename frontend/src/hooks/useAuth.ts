import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useState } from "react"

import {
  ApiError,
  type BodyLoginLoginBrowserSession as LoginCredentials,
  LoginService,
  type UserPublic,
  type UserRegister,
  UsersService,
} from "../client"
import useCustomToast from "./useCustomToast"

const useAuth = () => {
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const showToast = useCustomToast()
  const queryClient = useQueryClient()
  const {
    data: user,
    error: authError,
    isLoading,
    refetch: refetchUser,
  } = useQuery<UserPublic, ApiError>({
    queryKey: ["currentUser"],
    queryFn: UsersService.readUserMe,
    retry: false,
  })

  const signUpMutation = useMutation({
    mutationFn: (data: UserRegister) =>
      UsersService.registerUser({ requestBody: data }),

    onSuccess: () => {
      navigate({ to: "/login" })
      showToast(
        "Account created.",
        "Check your inbox to verify your email before logging in.",
        "success",
      )
    },
    onError: (err: ApiError) => {
      const errDetail = (err.body as any)?.detail

      showToast("Something went wrong.", errDetail, "error")
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })

  const login = async (data: LoginCredentials) => {
    return LoginService.loginBrowserSession({
      formData: data,
    })
  }

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: (authenticatedUser) => {
      queryClient.setQueryData(["currentUser"], authenticatedUser)
      navigate({ to: "/" })
    },
    onError: (err: ApiError) => {
      let errDetail = (err.body as any)?.detail

      if (Array.isArray(errDetail)) {
        errDetail = "Something went wrong"
      }

      setError(errDetail)
    },
  })

  const logout = async () => {
    try {
      await LoginService.logoutBrowserSession()
    } catch {
      showToast(
        "Could not log out.",
        "The server could not clear your browser session. Please try again.",
        "error",
      )
      return
    }
    queryClient.clear()
    await navigate({ to: "/login" })
  }

  return {
    signUpMutation,
    loginMutation,
    logout,
    user,
    isLoading,
    authError,
    isUnauthorized: authError instanceof ApiError && authError.status === 401,
    refetchUser,
    error,
    resetError: () => setError(null),
  }
}

export default useAuth
