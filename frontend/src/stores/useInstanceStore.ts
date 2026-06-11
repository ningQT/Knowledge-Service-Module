import { create } from 'zustand'
import type { Instance } from '@/types/api'

interface InstanceStore {
  instanceId: string | null
  instances: Instance[]
  setInstanceId: (id: string | null) => void
  setInstances: (list: Instance[]) => void
}

export const useInstanceStore = create<InstanceStore>((set) => ({
  instanceId: null,
  instances: [],
  setInstanceId: (id) => set({ instanceId: id }),
  setInstances: (list) => set({ instances: list }),
}))
