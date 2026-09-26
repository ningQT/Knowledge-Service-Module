import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Outlet } from 'react-router-dom'
import { AppSidebar } from './AppSidebar'
import { getCurrentUser } from '@/services/auth'
import { listInstances } from '@/services/instances'
import { useAuthStore } from '@/stores/useAuthStore'
import { canEditCurrentInstance, useInstanceStore } from '@/stores/useInstanceStore'
import { AppHeader } from './AppHeader'

export function AppLayout() {
  const instanceId = useInstanceStore((state) => state.instanceId)
  const instances = useInstanceStore((state) => state.instances)
  const currentInstance = instances.find((item) => item.id === instanceId)
  const readOnly = Boolean(currentInstance && !canEditCurrentInstance())
  const setUser = useAuthStore((state) => state.setUser)
  const resetAuth = useAuthStore((state) => state.resetAuth)
  const { t } = useTranslation('layout')

  useEffect(() => {
    /** ???? 403????????????????????? */
    async function handleForbidden() {
      try {
        const current = await getCurrentUser()
        setUser(current.user)
      } catch {
        resetAuth()
        useInstanceStore.getState().setInstanceId(null)
        useInstanceStore.getState().setInstances([])
        return
      }

      try {
        const nextInstances = await listInstances()
        const store = useInstanceStore.getState()
        store.setInstances(nextInstances)
        if (store.instanceId && !nextInstances.some((item) => item.id === store.instanceId)) {
          store.setInstanceId(null)
        }
      } catch {
        // ??????????????????????????????
      }
    }

    window.addEventListener('ksm:forbidden', handleForbidden)
    return () => window.removeEventListener('ksm:forbidden', handleForbidden)
  }, [resetAuth, setUser])

  return (
    <div className="flex h-screen overflow-hidden">
      <AppSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <AppHeader />
        <main className="flex-1 overflow-auto p-6">
          {readOnly && (
            <div className="mb-4 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
              {t('instance.readOnly')}
            </div>
          )}
          <Outlet />
        </main>
      </div>
    </div>
  )
}
