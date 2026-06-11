import { LogOut, Moon, Sun, Languages, UserCircle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useTheme } from '@/hooks/useTheme'
import { useLanguage } from '@/hooks/useLanguage'
import { logout } from '@/services/auth'
import { useAuthStore } from '@/stores/useAuthStore'
import { useInstanceStore } from '@/stores/useInstanceStore'
import type { Instance } from '@/types/api'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useTranslation } from 'react-i18next'

export function AppHeader() {
  const { theme, toggleTheme } = useTheme()
  const { language, toggleLanguage } = useLanguage()
  const { user, resetAuth } = useAuthStore()
  const { instances, instanceId, setInstanceId, setInstances } = useInstanceStore()
  const navigate = useNavigate()
  const { t } = useTranslation('layout')

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
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

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
            <div className="hidden items-center gap-1.5 text-sm text-muted-foreground sm:flex">
              <UserCircle className="h-4 w-4" />
              <span className="max-w-32 truncate">{user.username}</span>
            </div>
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
