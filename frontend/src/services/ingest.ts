import api from './client'
import type { IngestJob, CancelJobResponse, SseTokenResponse } from '@/types/api'

export async function ingestAsync(
  instanceId: string,
  file: File,
  options?: { domain_hint?: string; auto_map?: boolean }
): Promise<{ job_id: string; status: string }> {
  const formData = new FormData()
  formData.append('file', file)
  if (options?.domain_hint) formData.append('domain_hint', options.domain_hint)
  if (options?.auto_map !== undefined) formData.append('auto_map', String(options.auto_map))

  return api.post(`instances/${instanceId}/ingest/async`, { body: formData }).json()
}

export async function getJob(instanceId: string, jobId: string): Promise<IngestJob> {
  return api.get(`instances/${instanceId}/ingest/jobs/${jobId}`).json<IngestJob>()
}

export function getJobSSEUrl(instanceId: string, jobId: string): string {
  return `/api/v1/instances/${instanceId}/ingest/jobs/${jobId}/sse`
}

export async function createJobSSEToken(instanceId: string, jobId: string): Promise<SseTokenResponse> {
  return api.post(`instances/${instanceId}/ingest/jobs/${jobId}/sse-token`).json<SseTokenResponse>()
}

export async function cancelJob(instanceId: string, jobId: string): Promise<CancelJobResponse> {
  return api.post(`instances/${instanceId}/ingest/jobs/${jobId}/cancel`).json()
}
