import { create } from 'zustand'
import type { Instance } from '@/types/api'

const INSTANCE_STORAGE_KEY = 'ksm-selected-instance-id'

function readStoredInstanceId(): string | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(INSTANCE_STORAGE_KEY)
  } catch {
    return null
  }
}

function persistInstanceId(id: string | null): void {
  if (typeof window === 'undefined') return
  try {
    if (id) {
      window.localStorage.setItem(INSTANCE_STORAGE_KEY, id)
    } else {
      window.localStorage.removeItem(INSTANCE_STORAGE_KEY)
    }
  } catch {
    // 浏览器未提供 localStorage 时，仅保留当前会话内存状态。
  }
}

interface InstanceStore {
  instanceId: string | null
  instances: Instance[]
  setInstanceId: (id: string | null) => void
  setInstances: (list: Instance[]) => void
}

export const useInstanceStore = create<InstanceStore>((set) => ({
  instanceId: readStoredInstanceId(),
  instances: [],
  setInstanceId: (id) => {
    persistInstanceId(id)
    set({ instanceId: id })
  },
  setInstances: (list) => set({ instances: list }),
}))
