import api from './client'

export interface NoteData {
  file_path: string
  title: string
  type: string
  domain: string | null
  kind: string | null
  graph_layer: number
  graph_role: string | null
  verification: string
  status: string
  frontmatter: Record<string, unknown>
  body: string
  aliases?: string[]
  domain_values?: string[]
  kind_values?: string[]
  quality_warnings?: string[]
}

export interface NoteListItem {
  file_path: string
  title: string
  type: string
  domain: string | null
  kind: string | null
  graph_layer: number
  graph_role: string | null
  verification: string
  status: string
  concepts: string[]
  aliases: string[]
  domain_values: string[]
  kind_values: string[]
  facets: Record<string, string[]>
  quality_warnings: string[]
  indexed_at: string | null
}

export interface ListNotesFilters {
  domain?: string
  graphLayer?: number
  kind?: string
  query?: string
  type?: string
  verification?: string
}

export type UserVerification = 'verified' | 'unverified' | 'draft'

export async function listNotes(instanceId: string, filters: ListNotesFilters = {}): Promise<NoteListItem[]> {
  const searchParams = new URLSearchParams()
  if (filters.type) searchParams.set('type', filters.type)
  if (filters.domain) searchParams.set('domain', filters.domain)
  if (filters.kind) searchParams.set('kind', filters.kind)
  if (filters.graphLayer !== undefined) searchParams.set('graph_layer', String(filters.graphLayer))
  if (filters.verification) searchParams.set('verification', filters.verification)
  if (filters.query) searchParams.set('q', filters.query)
  const query = searchParams.toString()
  const data = await api.get(`instances/${instanceId}/notes${query ? `?${query}` : ''}`).json<{ notes: NoteListItem[] }>()
  return data.notes
}

export async function listNoteFacets(instanceId: string): Promise<Record<string, string[]>> {
  const data = await api.get(`instances/${instanceId}/notes/facets`).json<{ facets: Record<string, string[]> }>()
  return data.facets
}

export async function getNote(instanceId: string, path: string, signal?: AbortSignal): Promise<NoteData> {
  return api.get(`instances/${instanceId}/notes/${path}`, { signal }).json<NoteData>()
}

export async function updateNoteVerification(
  instanceId: string,
  path: string,
  verification: UserVerification
): Promise<NoteData> {
  return api
    .patch(`instances/${instanceId}/notes/${path}/verification`, { json: { verification } })
    .json<NoteData>()
}

export async function updateNoteMetadata(
  instanceId: string,
  path: string,
  data: { domain?: string; kind?: string; verification?: UserVerification }
): Promise<NoteData> {
  return api
    .patch(`instances/${instanceId}/notes/${path}/metadata`, { json: data })
    .json<NoteData>()
}

export async function deleteNote(
  instanceId: string,
  path: string
): Promise<{ deleted: boolean; path: string }> {
  return api.delete(`instances/${instanceId}/notes/${path}`).json<{ deleted: boolean; path: string }>()
}
