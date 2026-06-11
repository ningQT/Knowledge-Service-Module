import { create } from 'zustand'
import type { AnswerResult, AnswerStep, ProcessSummary, SearchResult } from '@/types/api'

export type SearchTabKey = 'core' | 'related' | 'source' | 'map'

type Updater<T> = T | ((prev: T) => T)

interface SearchStore {
  instanceId: string | null
  query: string
  searching: boolean
  result: SearchResult | null
  activeTab: SearchTabKey
  error: string | null
  elapsedMs: number | undefined
  answerJobId: string | null
  answerStatus: string
  answerSteps: AnswerStep[]
  answerResult: AnswerResult | null
  answerError: string | null
  answerNotice: string | null
  liveSummaries: ProcessSummary[]
  setQuery: (query: string) => void
  setSearching: (searching: boolean) => void
  setResult: (result: SearchResult | null) => void
  setActiveTab: (tab: SearchTabKey) => void
  setError: (error: string | null) => void
  setElapsedMs: (elapsedMs: number | undefined) => void
  setSearchInstanceId: (instanceId: string | null) => void
  clearForInstance: (instanceId: string | null) => void
  resetSearch: () => void
  resetAnswer: () => void
  setAnswerJobId: (jobId: string | null) => void
  setAnswerStatus: (status: string) => void
  setAnswerSteps: (steps: Updater<AnswerStep[]>) => void
  setAnswerResult: (result: AnswerResult | null) => void
  setAnswerError: (error: string | null) => void
  setAnswerNotice: (notice: string | null) => void
  setLiveSummaries: (summaries: Updater<ProcessSummary[]>) => void
}

const answerInitialState = {
  answerJobId: null,
  answerStatus: 'idle',
  answerSteps: [],
  answerResult: null,
  answerError: null,
  answerNotice: null,
  liveSummaries: [],
}

function resolveUpdater<T>(value: Updater<T>, previous: T): T {
  return typeof value === 'function' ? (value as (prev: T) => T)(previous) : value
}

export const useSearchStore = create<SearchStore>((set, get) => ({
  instanceId: null,
  query: '',
  searching: false,
  result: null,
  activeTab: 'core',
  error: null,
  elapsedMs: undefined,
  ...answerInitialState,
  setQuery: (query) => set({ query }),
  setSearching: (searching) => set({ searching }),
  setResult: (result) => set({ result }),
  setActiveTab: (activeTab) => set({ activeTab }),
  setError: (error) => set({ error }),
  setElapsedMs: (elapsedMs) => set({ elapsedMs }),
  setSearchInstanceId: (instanceId) => set({ instanceId }),
  clearForInstance: (instanceId) => {
    if (get().instanceId === instanceId) return
    set({
      instanceId,
      searching: false,
      result: null,
      activeTab: 'core',
      error: null,
      elapsedMs: undefined,
      ...answerInitialState,
    })
  },
  resetSearch: () =>
    set({
      searching: false,
      result: null,
      activeTab: 'core',
      error: null,
      elapsedMs: undefined,
      ...answerInitialState,
    }),
  resetAnswer: () => set({ ...answerInitialState }),
  setAnswerJobId: (answerJobId) => set({ answerJobId }),
  setAnswerStatus: (answerStatus) => set({ answerStatus }),
  setAnswerSteps: (answerSteps) =>
    set((state) => ({
      answerSteps: resolveUpdater(answerSteps, state.answerSteps),
    })),
  setAnswerResult: (answerResult) => set({ answerResult }),
  setAnswerError: (answerError) => set({ answerError }),
  setAnswerNotice: (answerNotice) => set({ answerNotice }),
  setLiveSummaries: (liveSummaries) =>
    set((state) => ({
      liveSummaries: resolveUpdater(liveSummaries, state.liveSummaries),
    })),
}))
