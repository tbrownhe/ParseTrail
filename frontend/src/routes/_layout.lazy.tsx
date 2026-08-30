import { Button, Flex, Spinner, Text } from "@chakra-ui/react"
import {
  createLazyFileRoute,
  Outlet,
  useNavigate,
} from "@tanstack/react-router"
import { useEffect } from "react"

import Sidebar from "../components/Common/Sidebar"
import UserMenu from "../components/Common/UserMenu"
import useAuth from "../hooks/useAuth"

export const Route = createLazyFileRoute("/_layout")({
  component: Layout,
})

function Layout() {
  const navigate = useNavigate()
  const { user, isLoading, authError, isUnauthorized, refetchUser } = useAuth()

  useEffect(() => {
    if (isUnauthorized) {
      navigate({ to: "/login", replace: true })
    }
  }, [isUnauthorized, navigate])

  if (isLoading || isUnauthorized || (!user && !authError)) {
    return (
      <Flex justify="center" align="center" height="100vh" width="full">
        <Spinner size="xl" color="ui.main" />
      </Flex>
    )
  }

  if (authError || !user) {
    return (
      <Flex
        direction="column"
        gap={4}
        justify="center"
        align="center"
        height="100vh"
        width="full"
      >
        <Text>ParseTrail could not verify your session.</Text>
        <Button variant="primary" onClick={() => refetchUser()}>
          Try again
        </Button>
      </Flex>
    )
  }

  return (
    <Flex maxW="large" h="auto" position="relative">
      <Sidebar />
      <Outlet />
      <UserMenu />
    </Flex>
  )
}
