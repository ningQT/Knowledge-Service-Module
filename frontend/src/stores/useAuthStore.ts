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
