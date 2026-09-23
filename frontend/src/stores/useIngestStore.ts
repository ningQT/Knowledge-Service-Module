import { create } from 'zustand'
import type { IngestJob, IngestStep } from '@/types/api'

const ACTIVE_JOB_STORAGE_KEY = 'ksm-active-ingest-job'

interface StoredIngestJob {
  jobId: string
  instanceId: string
}

function readStoredJob(): StoredIngestJob | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(ACTIVE_JOB_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<StoredIngestJob>
    if (typeof parsed.jobId !== 'string' || typeof parsed.instanceId !== 'string') return null
    return { jobId: parsed.jobId, instanceId: parsed.instanceId }
  } catch {
    return null
  }
}

function persistStoredJob(job: StoredIngestJob | null): void {
  if (typeof window === 'undefined') return
  try {
    if (job) {
      window.sessionStorage.setItem(ACTIVE_JOB_STORAGE_KEY, JSON.stringify(job))
    } else {
      window.sessionStorage.removeItem(ACTIVE_JOB_STORAGE_KEY)
    }
  } catch {
    // 浏览器未提供 sessionStorage 时，仅保留当前页面内存状态。
  }
}

function mergeSteps(restoredSteps: IngestStep[]): IngestStep[] {
  return initialSteps.map((step) => {
    const restored = restoredSteps.find((item) => item.step === step.step)
    return restored ? { ...step, ...restored } : step
  })
}

const terminalStatuses = new Set(['success', 'partial_failed', 'failed', 'cancelled'])
const storedJob = readStoredJob()

interface IngestStore {
  currentJobId: string | null
  jobInstanceId: string | null
  status: string
  steps: IngestStep[]
  result: {
    status: string
    created_files: string[]
    generated_cards: string[]
    generated_maps: string[]
    warnings: string[]
  } | null
  setJobId: (id: string, instanceId: string) => void
  restoreJob: (job: IngestJob) => void
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
  currentJobId: storedJob?.jobId ?? null,
  jobInstanceId: storedJob?.instanceId ?? null,
  status: storedJob ? 'running' : 'idle',
  steps: initialSteps,
  result: null,
  setJobId: (id, instanceId) => {
    persistStoredJob({ jobId: id, instanceId })
    set({ currentJobId: id, jobInstanceId: instanceId, status: 'running', steps: initialSteps, result: null })
  },
  restoreJob: (job) => {
    persistStoredJob({ jobId: job.job_id, instanceId: job.instance_id })
    set({
      currentJobId: job.job_id,
      jobInstanceId: job.instance_id,
      status: job.status,
      steps: mergeSteps(job.steps),
      result: terminalStatuses.has(job.status)
        ? {
            status: job.status,
            created_files: job.created_files,
            generated_cards: job.generated_cards,
            generated_maps: job.generated_maps,
            warnings: job.warnings,
          }
        : null,
    })
  },
  updateStep: (step, status, summary) =>
    set((state) => ({
      steps: state.steps.map((s) =>
        s.step === step ? { ...s, status: status as IngestStep['status'], summary } : s
      ),
    })),
  setResult: (result) => set({ result, status: result?.status || 'completed' }),
  cancel: () => {
    persistStoredJob(null)
    set({
      currentJobId: null,
      jobInstanceId: null,
      status: 'idle',
      steps: initialSteps,
      result: null,
    })
  },
  reset: () => {
    persistStoredJob(null)
    set({
      currentJobId: null,
      jobInstanceId: null,
      status: 'idle',
      steps: initialSteps,
      result: null,
    })
  },
}))
