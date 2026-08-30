import {
  Button,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  useDisclosure,
} from "@chakra-ui/react"
import { BsThreeDotsVertical } from "react-icons/bs"
import { FiEdit, FiTrash } from "react-icons/fi"

import type { UserPublic } from "../../client"
import DeleteUserAlert from "./DeleteUserAlert"
import EditUser from "./EditUser"

interface UserActionsMenuProps {
  user: UserPublic
  disabled?: boolean
}

const UserActionsMenu = ({ user, disabled }: UserActionsMenuProps) => {
  const editModal = useDisclosure()
  const deleteModal = useDisclosure()

  return (
    <Menu>
      <MenuButton
        isDisabled={disabled}
        as={Button}
        rightIcon={<BsThreeDotsVertical />}
        variant="unstyled"
      />
      <MenuList>
        <MenuItem onClick={editModal.onOpen} icon={<FiEdit fontSize="16px" />}>
          Edit User
        </MenuItem>
        <MenuItem
          onClick={deleteModal.onOpen}
          icon={<FiTrash fontSize="16px" />}
          color="ui.danger"
        >
          Delete User
        </MenuItem>
      </MenuList>
      <EditUser
        user={user}
        isOpen={editModal.isOpen}
        onClose={editModal.onClose}
      />
      <DeleteUserAlert
        userId={user.id}
        isOpen={deleteModal.isOpen}
        onClose={deleteModal.onClose}
      />
    </Menu>
  )
}

export default UserActionsMenu
