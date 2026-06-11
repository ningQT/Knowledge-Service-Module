import api from './client'
import type { ApiKeyClient, ApiKeyCreateResponse, AuthResponse, AuthStatus } from '@/types/api'

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
