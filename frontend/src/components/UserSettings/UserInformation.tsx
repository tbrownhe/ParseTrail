import {
  Box,
  Button,
  Container,
  Flex,
  FormControl,
  FormErrorMessage,
  FormLabel,
  Heading,
  Input,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"

import {
  type ApiError,
  type UserPublic,
  UsersService,
  type UserUpdateMe,
} from "../../client"
import useAuth from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { emailPattern, handleError } from "../../utils"

const UserInformation = () => {
  const queryClient = useQueryClient()
  const color = useColorModeValue("inherit", "ui.light")
  const showToast = useCustomToast()
  const [editMode, setEditMode] = useState(false)
  const { user: currentUser } = useAuth()
  const {
    register,
    handleSubmit,
    reset,
    getValues,
    formState: { isSubmitting, errors, isDirty },
  } = useForm<UserUpdateMe>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      full_name: currentUser?.full_name,
      email: currentUser?.email,
    },
  })

  const mutation = useMutation({
    mutationFn: (data: UserUpdateMe) =>
      UsersService.updateUserMe({ requestBody: data }),
    onSuccess: (updatedUser: UserPublic) => {
      setEditMode(false)
      reset({
        full_name: updatedUser.full_name,
        email: updatedUser.email,
      })
      if (updatedUser.pending_email) {
        showToast(
          "Verification required",
          `Check ${updatedUser.pending_email} to finish changing your email address.`,
          "success",
        )
      } else {
        showToast("Success!", "User updated successfully.", "success")
      }
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries()
    },
  })

  const onSubmit: SubmitHandler<UserUpdateMe> = async (data) => {
    mutation.mutate(data)
  }

  const onCancel = () => {
    reset({
      full_name: currentUser?.full_name,
      email: currentUser?.email,
    })
    setEditMode(false)
  }

  useEffect(() => {
    if (!editMode) {
      reset({
        full_name: currentUser?.full_name,
        email: currentUser?.email,
      })
    }
  }, [currentUser, editMode, reset])

  return (
    <>
      <Container maxW="full">
        <Heading size="sm" py={4}>
          User Information
        </Heading>
        <Box
          w={{ sm: "full", md: "50%" }}
          as="form"
          onSubmit={handleSubmit(onSubmit)}
        >
          <FormControl>
            <FormLabel color={color} htmlFor="name">
              Full name
            </FormLabel>
            {editMode ? (
              <Input
                id="name"
                {...register("full_name", { maxLength: 30 })}
                type="text"
                size="md"
                w="auto"
              />
            ) : (
              <Text
                size="md"
                py={2}
                color={!currentUser?.full_name ? "ui.dim" : "inherit"}
                isTruncated
                maxWidth="250px"
              >
                {currentUser?.full_name || "N/A"}
              </Text>
            )}
          </FormControl>
          <FormControl mt={4} isInvalid={!!errors.email}>
            <FormLabel color={color} htmlFor="email">
              Email
            </FormLabel>
            {editMode ? (
              <Input
                id="email"
                {...register("email", {
                  required: "Email is required",
                  pattern: emailPattern,
                })}
                type="email"
                size="md"
                w="auto"
              />
            ) : (
              <Text size="md" py={2} isTruncated maxWidth="250px">
                {currentUser?.email}
              </Text>
            )}
            {errors.email && (
              <FormErrorMessage>{errors.email.message}</FormErrorMessage>
            )}
            {!editMode && currentUser?.pending_email && (
              <Text color="orange.500" fontSize="sm" mt={1}>
                Pending verification: {currentUser.pending_email}
              </Text>
            )}
          </FormControl>
          <Flex mt={4} gap={3}>
            <Button
              variant="primary"
              onClick={editMode ? undefined : () => setEditMode(true)}
              type={editMode ? "submit" : "button"}
              isLoading={editMode ? mutation.isPending : false}
              isDisabled={editMode ? !isDirty || !getValues("email") : false}
            >
              {editMode ? "Save" : "Edit"}
            </Button>
            {editMode && (
              <Button onClick={onCancel} isDisabled={isSubmitting}>
                Cancel
              </Button>
            )}
          </Flex>
        </Box>
      </Container>
    </>
  )
}

export default UserInformation
