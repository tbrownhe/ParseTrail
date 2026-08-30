import {
  Box,
  Button,
  Container,
  Heading,
  SimpleGrid,
  Text,
} from "@chakra-ui/react"
import { createLazyFileRoute } from "@tanstack/react-router"

import useAuth from "../../hooks/useAuth"

export const Route = createLazyFileRoute("/_layout/")({
  component: AccountHome,
})

function AccountHome() {
  const { user: currentUser } = useAuth()

  return (
    <Container maxW="full" py={12} px={{ base: 6, lg: 12 }}>
      <Heading size="lg">ParseTrail Account</Heading>
      <Text mt={2} color="ui.dim">
        Signed in as {currentUser?.full_name || currentUser?.email}.
      </Text>
      <Text mt={4} maxW="3xl">
        This account provides signed client and plugin downloads plus explicit
        statement contribution. Your financial database and normal statement
        imports remain on your device and are not available in this dashboard.
      </Text>
      <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={6} mt={10} maxW="4xl">
        <Box borderWidth="1px" borderRadius="lg" p={6}>
          <Heading size="md">Desktop client</Heading>
          <Text mt={3}>
            Download the latest supported ParseTrail installer.
          </Text>
          <Button
            as="a"
            href="https://parsetrail.com/download.html"
            target="_blank"
            rel="noreferrer"
            mt={5}
            variant="primary"
          >
            View downloads
          </Button>
        </Box>
        <Box borderWidth="1px" borderRadius="lg" p={6}>
          <Heading size="md">Plugin library</Heading>
          <Text mt={3}>
            Review the institutions and statement types currently supported.
          </Text>
          <Button
            as="a"
            href="https://parsetrail.com/plugins.html"
            target="_blank"
            rel="noreferrer"
            mt={5}
            variant="primary"
          >
            View supported plugins
          </Button>
        </Box>
      </SimpleGrid>
    </Container>
  )
}
