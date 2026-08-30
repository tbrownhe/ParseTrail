import { Button, Flex, Icon, useDisclosure } from "@chakra-ui/react"
import { FaPlus } from "react-icons/fa"

import AddUser from "./AddUser"

const AdminToolbar = () => {
  const addModal = useDisclosure()

  return (
    <Flex py={8} gap={4}>
      <Button
        variant="primary"
        gap={1}
        fontSize={{ base: "sm", md: "inherit" }}
        onClick={addModal.onOpen}
      >
        <Icon as={FaPlus} /> Add User
      </Button>
      <AddUser isOpen={addModal.isOpen} onClose={addModal.onClose} />
    </Flex>
  )
}

export default AdminToolbar
