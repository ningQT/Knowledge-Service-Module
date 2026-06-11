import api from './client'
import type {
  CreateSearchLexiconRequest,
  SearchLexiconEntry,
  SearchLexiconListResponse,
  UpdateSearchLexiconRequest,
} from '@/types/api'

export async function listSearchLexicon(instanceId: string): Promise<SearchLexiconEntry[]> {
  const data = await api
    .get(`instances/${instanceId}/search-lexicon`)
    .json<SearchLexiconListResponse>()
  return data.entries
}

export async function createSearchLexicon(
  instanceId: string,
  data: CreateSearchLexiconRequest
): Promise<SearchLexiconEntry> {
  return api
    .post(`instances/${instanceId}/search-lexicon`, { json: data })
    .json<SearchLexiconEntry>()
}

export async function updateSearchLexicon(
  instanceId: string,
  entryId: string,
  data: UpdateSearchLexiconRequest
): Promise<SearchLexiconEntry> {
  return api
    .patch(`instances/${instanceId}/search-lexicon/${entryId}`, { json: data })
    .json<SearchLexiconEntry>()
}

export async function deleteSearchLexicon(
  instanceId: string,
  entryId: string
): Promise<{ deleted: boolean; id: string }> {
  return api.delete(`instances/${instanceId}/search-lexicon/${entryId}`).json<{ deleted: boolean; id: string }>()
}
