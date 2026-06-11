import api from './client'
import type { Instance, InstanceDiagnostics, InstanceStats } from '@/types/api'

export async function listInstances(): Promise<Instance[]> {
  const data = await api.get('instances').json<{ instances: Instance[] }>()
  return data.instances
}

export async function getInstance(id: string): Promise<Instance> {
  return api.get(`instances/${id}`).json<Instance>()
}

export async function getInstanceStats(id: string): Promise<InstanceStats> {
  return api.get(`instances/${id}/stats`).json<InstanceStats>()
}

export async function getInstanceDiagnostics(id: string): Promise<InstanceDiagnostics> {
  return api.get(`instances/${id}/diagnostics`).json<InstanceDiagnostics>()
}

export async function createInstance(data: {
  name: string
  template_id?: string
  auto_map?: boolean
  language?: 'zh' | 'en'
}): Promise<Instance> {
  return api.post('instances', { json: data }).json<Instance>()
}

export async function updateInstance(
  id: string,
  data: { name?: string; auto_map?: boolean }
): Promise<Instance> {
  return api.patch(`instances/${id}`, { json: data }).json<Instance>()
}

export async function deleteInstance(
  id: string,
  options: { deleteFiles?: boolean } = {}
): Promise<{ deleted: boolean; id: string; path: string | null; files_deleted: boolean }> {
  return api
    .delete(`instances/${id}`, {
      searchParams: { delete_files: String(Boolean(options.deleteFiles)) },
    })
    .json<{ deleted: boolean; id: string; path: string | null; files_deleted: boolean }>()
}
