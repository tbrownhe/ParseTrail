import { createFileRoute } from "@tanstack/react-router"

function validateUsersSearch(search: Record<string, unknown>) {
  const page = search.page
  return {
    page:
      typeof page === "number" && Number.isSafeInteger(page) && page > 0
        ? page
        : 1,
  }
}

export const Route = createFileRoute("/_layout/admin")({
  validateSearch: validateUsersSearch,
})
