import { useEffect } from 'react'
import { LogOut, Moon, Sun, Languages, UserCircle } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { useTheme } from '@/hooks/useTheme'
import { useLanguage } from '@/hooks/useLanguage'
import { logout } from '@/services/auth'
import { listInstances } from '@/services/instances'
import { useAuthStore } from '@/stores/useAuthStore'
import { useInstanceStore } from '@/stores/useInstanceStore'
import type { Instance } from '@/types/api'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useTranslation } from 'react-i18next'

export function AppHeader() {
  const { theme, toggleTheme } = useTheme()
  const { language, toggleLanguage } = useLanguage()
  const { user, resetAuth } = useAuthStore()
  const { instances, instanceId, setInstanceId, setInstances } = useInstanceStore()
  const navigate = useNavigate()
  const { t } = useTranslation('layout')
  const currentInstance = instances.find((item) => item.id === instanceId)

  useEffect(() => {
    if (instances.length > 0) return
    let cancelled = false
    listInstances()
      .then((list) => {
        if (cancelled) return
        setInstances(list)
        if (instanceId && !list.some((item) => item.id === instanceId)) {
          setInstanceId(null)
        }
      })
      .catch((error) => {
        console.error('Failed to load instances:', error)
      })
    return () => { cancelled = true }
  }, [instanceId, instances.length, setInstanceId, setInstances])

  async function handleLogout() {
    try {
      await logout()
    } finally {
      resetAuth()
      setInstanceId(null)
      setInstances([])
      navigate('/')
    }
  }

  return (
    <header className="flex items-center justify-end h-14 px-6 border-b border-border bg-card">
      <div className="flex items-center gap-4">
        <Select value={instanceId || ''} onValueChange={setInstanceId}>
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder={t('instance.placeholder')} />
          </SelectTrigger>
          <SelectContent align="end">
            {instances.map((inst: Instance) => (
              <SelectItem key={inst.id} value={inst.id}>
                {inst.name}
                {inst.access_level ? ` ? ${t(`instance.access.${inst.access_level}`)}` : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {currentInstance?.access_level && (
          <Badge variant={currentInstance.can_edit ? 'secondary' : 'outline'}>
            {t(`instance.access.${currentInstance.access_level}`)}
          </Badge>
        )}

        <button
          onClick={toggleLanguage}
          className="flex items-center gap-1.5 px-2 py-1.5 hover:bg-muted rounded-md text-sm text-muted-foreground hover:text-foreground"
          title={language === 'en' ? t('language.zh') : t('language.en')}
        >
          <Languages className="w-4 h-4" />
          <span className="font-medium">{language === 'en' ? t('language.en') : t('language.zh')}</span>
        </button>

        <button
          onClick={toggleTheme}
          className="p-2 hover:bg-muted rounded-md text-muted-foreground hover:text-foreground"
        >
          {theme === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
        </button>

        {user && (
          <div className="flex items-center gap-2 border-l border-border pl-4">
            <Link
              to="/profile"
              className="hidden items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground sm:flex"
              title={t('profile')}
            >
              <UserCircle className="h-4 w-4" />
              <span className="max-w-32 truncate">{user.username}</span>
              <span className="rounded border border-border px-1.5 py-0.5 text-[10px] leading-none">
                {t(`accountType.${user.role}`)}
              </span>
            </Link>
            <button
              onClick={handleLogout}
              className="p-2 hover:bg-muted rounded-md text-muted-foreground hover:text-foreground"
              title={t('auth.logout')}
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    </header>
  )
}
