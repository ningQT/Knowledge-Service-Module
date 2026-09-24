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
  instanceRevision: number
  instances: Instance[]
  setInstanceId: (id: string | null) => void
  setInstances: (list: Instance[]) => void
}

export const useInstanceStore = create<InstanceStore>((set) => ({
  instanceId: readStoredInstanceId(),
  instanceRevision: 0,
  instances: [],
  setInstanceId: (id) => {
    persistInstanceId(id)
    set((state) => ({
      instanceId: id,
      instanceRevision: state.instanceRevision + 1,
    }))
  },
  setInstances: (list) => set({ instances: list }),
}))

/**
 * 判断异步响应是否仍属于当前实例选择周期。
 *
 * @param revision 请求发起时捕获的实例版本号
 * @returns 当前实例版本与请求版本一致时返回 true
 */
export function isInstanceRevisionCurrent(revision: number): boolean {
  return useInstanceStore.getState().instanceRevision === revision
}
