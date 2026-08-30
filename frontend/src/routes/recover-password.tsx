import { createFileRoute, redirect } from "@tanstack/react-router"

import { isLoggedIn } from "../hooks/useAuth"

export const Route = createFileRoute("/recover-password")({
  beforeLoad: async () => {
    if (isLoggedIn()) {
      throw redirect({
        to: "/",
      })
    }
  },
})
