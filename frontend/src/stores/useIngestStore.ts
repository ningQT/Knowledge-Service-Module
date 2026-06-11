import { create } from 'zustand'
import type { IngestStep } from '@/types/api'

interface IngestStore {
  currentJobId: string | null
  status: string
  steps: IngestStep[]
  result: {
    status: string
    created_files: string[]
    generated_cards: string[]
    generated_maps: string[]
    warnings: string[]
  } | null
  setJobId: (id: string) => void
  updateStep: (step: number, status: string, summary?: Record<string, unknown>) => void
  setResult: (result: IngestStore['result']) => void
  cancel: () => void
  reset: () => void
}

const initialSteps: IngestStep[] = Array.from({ length: 8 }, (_, i) => ({
  step: i + 1,
  name: '', // 步骤名由 StepProgress 组件通过 t() 动态获取
  status: 'pending' as const,
}))

export const useIngestStore = create<IngestStore>((set) => ({
  currentJobId: null,
  status: 'idle',
  steps: initialSteps,
  result: null,
  setJobId: (id) => set({ currentJobId: id, status: 'running', steps: initialSteps, result: null }),
  updateStep: (step, status, summary) =>
    set((state) => ({
      steps: state.steps.map((s) =>
        s.step === step ? { ...s, status: status as IngestStep['status'], summary } : s
      ),
    })),
  setResult: (result) => set({ result, status: result?.status || 'completed' }),
  cancel: () => set({ currentJobId: null, status: 'idle', steps: initialSteps, result: null }),
  reset: () => set({ currentJobId: null, status: 'idle', steps: initialSteps, result: null }),
}))
