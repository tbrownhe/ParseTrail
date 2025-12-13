import { Button, Container, Heading, Spinner, Text } from "@chakra-ui/react"
import { useMutation } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect, useMemo } from "react"

import { type ApiError, LoginService } from "../client"
import useCustomToast from "../hooks/useCustomToast"
import { handleError } from "../utils"

export const Route = createFileRoute("/verify-email")({
  component: VerifyEmail,
})

function VerifyEmail() {
  const navigate = useNavigate()
  const showToast = useCustomToast()
  const token = useMemo(
    () => new URLSearchParams(window.location.search).get("token"),
    [],
  )

  const mutation = useMutation({
    mutationFn: async () => {
      if (!token) {
        throw new Error("Missing verification token")
      }
      await LoginService.verifyEmail({ requestBody: { token } })
    },
    onSuccess: () => {
      showToast(
        "Email verified",
        "Your email has been verified. You can now log in.",
        "success",
      )
    },
    onError: (err: ApiError | Error) => {
      if (err instanceof Error) {
        showToast("Error", err.message, "error")
        return
      }
      handleError(err, showToast)
    },
  })

  useEffect(() => {
    // Run once on mount to avoid re-triggering and looping between success/error states
    mutation.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const isError = mutation.isError
  const isSuccess = mutation.isSuccess
  const isLoading = mutation.isPending

  return (
    <Container
      h="100vh"
      maxW="sm"
      alignItems="center"
      justifyContent="center"
      gap={4}
      centerContent
      textAlign="center"
    >
      <Heading size="xl" color="ui.main" mb={2}>
        Email Verification
      </Heading>
      {isLoading && (
        <>
          <Spinner size="xl" thickness="4px" color="ui.main" />
          <Text mt={4}>Verifying your email...</Text>
        </>
      )}
      {isSuccess && (
        <>
          <Text mb={4}>
            Your email is verified. You can now log in to your account.
          </Text>
          <Button variant="primary" onClick={() => navigate({ to: "/login" })}>
            Go to Login
          </Button>
        </>
      )}
      {isError && (
        <>
          <Text mb={4}>
            We could not verify your email. Please request a new verification
            email or contact support.
          </Text>
          <Button variant="primary" onClick={() => navigate({ to: "/login" })}>
            Return to Login
          </Button>
        </>
      )}
    </Container>
  )
}
