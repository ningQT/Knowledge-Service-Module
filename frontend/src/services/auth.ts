import api from './client'
import type {
  AccountSummary,
  ApiKeyClient,
  ApiKeyCreateResponse,
  AuthResponse,
  AuthStatus,
} from '@/types/api'

export async function getAuthStatus(): Promise<AuthStatus> {
  return api.get('auth/status').json<AuthStatus>()
}

export async function setupAdmin(data: { username: string; password: string }): Promise<AuthResponse> {
  return api.post('auth/setup', { json: data }).json<AuthResponse>()
}

export async function login(data: { username: string; password: string }): Promise<AuthResponse> {
  return api.post('auth/login', { json: data }).json<AuthResponse>()
}

export async function logout(): Promise<{ logged_out: boolean }> {
  return api.post('auth/logout').json<{ logged_out: boolean }>()
}

/** ???????????????????????? */
export async function getCurrentUser(): Promise<AuthResponse> {
  return api.get('auth/me').json<AuthResponse>()
}

export async function listApiKeys(): Promise<ApiKeyClient[]> {
  const data = await api.get('api-keys').json<{ api_keys: ApiKeyClient[] }>()
  return data.api_keys
}

export async function createApiKey(data: {
  name: string
  scope: 'read' | 'write'
  instance_ids: string[]
}): Promise<ApiKeyCreateResponse> {
  return api.post('api-keys', { json: data }).json<ApiKeyCreateResponse>()
}

export async function updateApiKey(
  id: string,
  data: {
    name?: string
    scope?: 'read' | 'write'
    enabled?: boolean
    instance_ids?: string[]
  }
): Promise<ApiKeyClient> {
  return api.patch(`api-keys/${id}`, { json: data }).json<ApiKeyClient>()
}

export async function deleteApiKey(id: string): Promise<{ deleted: boolean; id: string }> {
  return api.delete(`api-keys/${id}`).json<{ deleted: boolean; id: string }>()
}

export async function rotateApiKey(id: string): Promise<ApiKeyCreateResponse> {
  return api.post(`api-keys/${id}/rotate`).json<ApiKeyCreateResponse>()
}


/** 修改当前账户密码。 */
export async function changePassword(data: {
  current_password: string
  new_password: string
}): Promise<{ logged_out: boolean }> {
  return api.post('auth/change-password', { json: data }).json<{ logged_out: boolean }>()
}

/** 获取普通账户列表。 */
export async function listAccounts(): Promise<AccountSummary[]> {
  const data = await api.get('accounts').json<{ accounts: AccountSummary[] }>()
  return data.accounts
}

/** 创建普通账户。 */
export async function createAccount(data: {
  username: string
  password: string
  enabled?: boolean
}): Promise<AccountSummary> {
  return api.post('accounts', { json: data }).json<AccountSummary>()
}

/** 启停普通账户。 */
export async function updateAccount(id: string, data: { enabled: boolean }): Promise<AccountSummary> {
  return api.patch(`accounts/${id}`, { json: data }).json<AccountSummary>()
}

/** 重置普通账户密码。 */
export async function resetAccountPassword(
  id: string,
  newPassword: string
): Promise<{ deleted: boolean; id: string }> {
  return api
    .post(`accounts/${id}/reset-password`, { json: { new_password: newPassword } })
    .json<{ deleted: boolean; id: string }>()
}

/** 删除普通账户。 */
export async function deleteAccount(
  id: string,
  confirmUsername: string
): Promise<{ deleted: boolean; id: string }> {
  return api
    .delete(`accounts/${id}`, { json: { confirm_username: confirmUsername } })
    .json<{ deleted: boolean; id: string }>()
}
