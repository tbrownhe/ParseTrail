// biome-ignore-all lint/complexity/noStaticOnlyClass: preserves the previous generated client API while callers migrate
import {
  createItem as apiCreateItem,
  createUser as apiCreateUser,
  deleteItem as apiDeleteItem,
  deleteUser as apiDeleteUser,
  deleteUserMe as apiDeleteUserMe,
  healthCheck as apiHealthCheck,
  loginAccessToken as apiLoginAccessToken,
  readItem as apiReadItem,
  readItems as apiReadItems,
  readUserById as apiReadUserById,
  readUserMe as apiReadUserMe,
  readUsers as apiReadUsers,
  recoverPassword as apiRecoverPassword,
  recoverPasswordHtmlContent as apiRecoverPasswordHtmlContent,
  registerUser as apiRegisterUser,
  resetPassword as apiResetPassword,
  testEmail as apiTestEmail,
  testToken as apiTestToken,
  updateItem as apiUpdateItem,
  updatePasswordMe as apiUpdatePasswordMe,
  updateUser as apiUpdateUser,
  updateUserMe as apiUpdateUserMe,
  verifyEmail as apiVerifyEmail,
} from "./generated/sdk.gen"
import type {
  BodyLoginLoginAccessToken,
  ItemCreate,
  ItemUpdate,
  NewPassword,
  UpdatePassword,
  UserCreate,
  UserRegister,
  UserUpdate,
  UserUpdateMe,
  VerificationToken,
} from "./generated/types.gen"

const requestOptions = { throwOnError: true } as const

export class LoginService {
  public static loginAccessToken(data: {
    formData: BodyLoginLoginAccessToken
  }) {
    return apiLoginAccessToken({ body: data.formData, ...requestOptions })
  }

  public static testToken() {
    return apiTestToken(requestOptions)
  }

  public static recoverPassword(data: { email: string }) {
    return apiRecoverPassword({
      path: { email: data.email },
      ...requestOptions,
    })
  }

  public static resetPassword(data: { requestBody: NewPassword }) {
    return apiResetPassword({ body: data.requestBody, ...requestOptions })
  }

  public static verifyEmail(data: { requestBody: VerificationToken }) {
    return apiVerifyEmail({ body: data.requestBody, ...requestOptions })
  }

  public static recoverPasswordHtmlContent(data: { email: string }) {
    return apiRecoverPasswordHtmlContent({
      path: { email: data.email },
      ...requestOptions,
    })
  }
}

export class UsersService {
  public static readUsers(data: { limit?: number; skip?: number } = {}) {
    return apiReadUsers({ query: data, ...requestOptions })
  }

  public static createUser(data: { requestBody: UserCreate }) {
    return apiCreateUser({ body: data.requestBody, ...requestOptions })
  }

  public static readUserMe() {
    return apiReadUserMe(requestOptions)
  }

  public static deleteUserMe() {
    return apiDeleteUserMe(requestOptions)
  }

  public static updateUserMe(data: { requestBody: UserUpdateMe }) {
    return apiUpdateUserMe({ body: data.requestBody, ...requestOptions })
  }

  public static updatePasswordMe(data: { requestBody: UpdatePassword }) {
    return apiUpdatePasswordMe({ body: data.requestBody, ...requestOptions })
  }

  public static registerUser(data: { requestBody: UserRegister }) {
    return apiRegisterUser({ body: data.requestBody, ...requestOptions })
  }

  public static readUserById(data: { userId: string }) {
    return apiReadUserById({
      path: { user_id: data.userId },
      ...requestOptions,
    })
  }

  public static updateUser(data: { requestBody: UserUpdate; userId: string }) {
    return apiUpdateUser({
      body: data.requestBody,
      path: { user_id: data.userId },
      ...requestOptions,
    })
  }

  public static deleteUser(data: { userId: string }) {
    return apiDeleteUser({
      path: { user_id: data.userId },
      ...requestOptions,
    })
  }
}

export class UtilsService {
  public static testEmail(data: { emailTo: string }) {
    return apiTestEmail({
      query: { email_to: data.emailTo },
      ...requestOptions,
    })
  }

  public static healthCheck() {
    return apiHealthCheck(requestOptions)
  }
}

export class ItemsService {
  public static readItems(data: { limit?: number; skip?: number } = {}) {
    return apiReadItems({ query: data, ...requestOptions })
  }

  public static createItem(data: { requestBody: ItemCreate }) {
    return apiCreateItem({ body: data.requestBody, ...requestOptions })
  }

  public static readItem(data: { id: string }) {
    return apiReadItem({ path: { id: data.id }, ...requestOptions })
  }

  public static updateItem(data: { id: string; requestBody: ItemUpdate }) {
    return apiUpdateItem({
      body: data.requestBody,
      path: { id: data.id },
      ...requestOptions,
    })
  }

  public static deleteItem(data: { id: string }) {
    return apiDeleteItem({ path: { id: data.id }, ...requestOptions })
  }
}
