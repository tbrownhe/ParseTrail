import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Button,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import React from "react"

import { UsersService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"

interface DeleteUserAlertProps {
  userId: string
  isOpen: boolean
  onClose: () => void
}

const DeleteUserAlert = ({ userId, isOpen, onClose }: DeleteUserAlertProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const cancelRef = React.useRef<HTMLButtonElement | null>(null)

  const mutation = useMutation({
    mutationFn: () => UsersService.deleteUser({ userId }),
    onSuccess: () => {
      showToast("Success", "The user was deleted successfully.", "success")
      onClose()
    },
    onError: () => {
      showToast(
        "An error occurred.",
        "An error occurred while deleting the user.",
        "error",
      )
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })

  return (
    <AlertDialog
      isOpen={isOpen}
      onClose={onClose}
      leastDestructiveRef={cancelRef}
      size={{ base: "sm", md: "md" }}
      isCentered
    >
      <AlertDialogOverlay>
        <AlertDialogContent>
          <AlertDialogHeader>Delete User</AlertDialogHeader>
          <AlertDialogBody>
            Are you sure? You will not be able to undo this action.
          </AlertDialogBody>
          <AlertDialogFooter gap={3}>
            <Button
              variant="danger"
              onClick={() => mutation.mutate()}
              isLoading={mutation.isPending}
            >
              Delete
            </Button>
            <Button
              ref={cancelRef}
              onClick={onClose}
              isDisabled={mutation.isPending}
            >
              Cancel
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialogOverlay>
    </AlertDialog>
  )
}

export default DeleteUserAlert
