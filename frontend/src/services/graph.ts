import api from './client'
import type { GraphData } from '@/types/api'

export async function getGraph(
  instanceId: string,
  filters?: {
    layer_filter?: number
    domain_filter?: string
    verification_filter?: string
    include_unresolved?: boolean
  }
): Promise<GraphData> {
  const searchParams = new URLSearchParams()
  if (filters?.layer_filter !== undefined) searchParams.set('layer_filter', String(filters.layer_filter))
  if (filters?.domain_filter) searchParams.set('domain_filter', filters.domain_filter)
  if (filters?.verification_filter) searchParams.set('verification_filter', filters.verification_filter)
  if (filters?.include_unresolved !== undefined) searchParams.set('include_unresolved', String(filters.include_unresolved))

  const query = searchParams.toString()
  return api.get(`instances/${instanceId}/graph${query ? `?${query}` : ''}`).json<GraphData>()
}
