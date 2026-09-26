import { create } from 'zustand'
import type { AuthUser } from '@/types/api'

interface AuthStore {
  user: AuthUser | null
  setupRequired: boolean
  setUser: (user: AuthUser | null) => void
  setSetupRequired: (required: boolean) => void
  resetAuth: () => void
}

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  setupRequired: false,
  setUser: (user) => set({ user }),
  setSetupRequired: (required) => set({ setupRequired: required }),
  resetAuth: () => set({ user: null, setupRequired: false }),
}))

/**
 * 判断当前用户是否为管理员。
 *
 * @returns 当前用户角色为管理员时返回 true
 */
export function useIsAdmin(): boolean {
  return useAuthStore((state) => state.user?.role === 'admin')
}
