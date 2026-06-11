import api from './client'
import type { AnswerJob, AnswerResult, SearchResult, SseTokenResponse } from '@/types/api'

export async function search(
  query: string,
  instanceIds?: string[],
  options?: { include_comprehension?: boolean }
): Promise<SearchResult> {
  return api.post('search', {
    json: {
      query,
      instance_ids: instanceIds,
      include_comprehension: options?.include_comprehension ?? true,
    },
  }).json<SearchResult>()
}

export async function startAnswerJob(
  query: string,
  instanceIds?: string[],
  options?: { include_search_result?: boolean; include_comprehension?: boolean }
): Promise<{ job_id: string; status: string }> {
  return api.post('search/answer-jobs', {
    json: {
      query,
      instance_ids: instanceIds,
      include_search_result: options?.include_search_result ?? false,
      include_comprehension: options?.include_comprehension ?? false,
      answer_options: {
        strategy: 'map_card_first',
        citation_level: 'source_note',
      },
    },
  }).json()
}

export async function getAnswerJob(jobId: string): Promise<AnswerJob> {
  return api.get(`search/answer-jobs/${jobId}`).json<AnswerJob>()
}

export function getAnswerJobSSEUrl(jobId: string): string {
  return `/api/v1/search/answer-jobs/${jobId}/sse`
}

export async function createAnswerJobSSEToken(jobId: string): Promise<SseTokenResponse> {
  return api.post(`search/answer-jobs/${jobId}/sse-token`).json<SseTokenResponse>()
}

export async function searchAnswer(
  query: string,
  instanceIds?: string[],
  options?: { include_search_result?: boolean; include_comprehension?: boolean }
): Promise<AnswerResult> {
  return api.post('search/answer', {
    json: {
      query,
      instance_ids: instanceIds,
      include_search_result: options?.include_search_result ?? false,
      include_comprehension: options?.include_comprehension ?? false,
      answer_options: {
        strategy: 'map_card_first',
        citation_level: 'source_note',
      },
    },
  }).json<AnswerResult>()
}
