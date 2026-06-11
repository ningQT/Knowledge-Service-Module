import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Eye, EyeOff, Languages, Loader2, LogIn, Moon, ShieldCheck, Sun } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { LoadingState } from '@/components/shared/LoadingState'
import { useLanguage } from '@/hooks/useLanguage'
import { useTheme } from '@/hooks/useTheme'
import { formatApiError } from '@/lib/i18nFormat'
import { getAuthStatus, login, setupAdmin } from '@/services/auth'
import { useAuthStore } from '@/stores/useAuthStore'

export function AuthGate({ children }: { children: ReactNode }) {
  const { user, setupRequired, setUser, setSetupRequired } = useAuthStore()
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const { t } = useTranslation('auth')

  useEffect(() => {
    let mounted = true
    async function loadStatus() {
      setLoading(true)
      setLoadError('')
      try {
        const status = await getAuthStatus()
        if (!mounted) return
        setSetupRequired(status.setup_required)
        setUser(status.authenticated ? status.user : null)
      } catch (e) {
        if (mounted) setLoadError(formatApiError(t, e))
      } finally {
        if (mounted) setLoading(false)
      }
    }
    loadStatus()
    return () => {
      mounted = false
    }
  }, [setSetupRequired, setUser, t])

  if (loading) return <LoadingState />

  if (loadError) {
    return (
      <AuthShell title={t('statusError.title')} description={loadError}>
        <Button onClick={() => window.location.reload()}>{t('action.retry')}</Button>
      </AuthShell>
    )
  }

  if (setupRequired) {
    return <AuthForm mode="setup" />
  }

  if (!user) {
    return <AuthForm mode="login" />
  }

  return <>{children}</>
}

function AuthForm({ mode }: { mode: 'setup' | 'login' }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const { setUser, setSetupRequired } = useAuthStore()
  const { t } = useTranslation('auth')

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = mode === 'setup'
        ? await setupAdmin({ username, password })
        : await login({ username, password })
      setUser(result.user)
      setSetupRequired(false)
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setBusy(false)
    }
  }

  const isSetup = mode === 'setup'
  return (
    <AuthShell
      title={isSetup ? t('setup.title') : t('login.title')}
      description={isSetup ? t('setup.description') : t('login.description')}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium mb-1">{t('field.username')}</label>
          <Input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">{t('field.password')}</label>
          <PasswordField
            value={password}
            onChange={setPassword}
            autoComplete={isSetup ? 'new-password' : 'current-password'}
          />
        </div>
        {error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : isSetup ? <ShieldCheck /> : <LogIn />}
          {isSetup ? t('setup.submit') : t('login.submit')}
        </Button>
      </form>
    </AuthShell>
  )
}

function AuthShell({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: ReactNode
}) {
  const { theme, toggleTheme } = useTheme()
  const { language, toggleLanguage } = useLanguage()
  const { t } = useTranslation('layout')

  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center p-6">
      <div className="absolute left-4 top-4 flex items-center gap-2 sm:left-6 sm:top-6">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
          <span className="text-sm font-bold text-primary-foreground">K</span>
        </div>
        <span className="font-semibold text-foreground">{t('brand')}</span>
      </div>

      <div className="absolute right-4 top-4 flex items-center gap-2 sm:right-6 sm:top-6">
        <button
          onClick={toggleLanguage}
          className="flex h-9 items-center gap-1.5 rounded-md px-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
          title={language === 'en' ? t('language.zh') : t('language.en')}
        >
          <Languages className="h-4 w-4" />
          <span className="font-medium">{language === 'en' ? t('language.en') : t('language.zh')}</span>
        </button>
        <button
          onClick={toggleTheme}
          className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
        </button>
      </div>

      <div className="w-full max-w-md rounded-lg border border-border bg-card p-6 shadow-sm">
        <div className="mb-6 flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-xl font-semibold">{title}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          </div>
        </div>
        {children}
      </div>
    </div>
  )
}

function PasswordField({
  value,
  onChange,
  autoComplete,
}: {
  value: string
  onChange: (value: string) => void
  autoComplete: string
}) {
  const [showPassword, setShowPassword] = useState(false)
  const { t } = useTranslation('auth')
  const label = showPassword ? t('password.hide') : t('password.show')

  return (
    <div className="relative">
      <Input
        type={showPassword ? 'text' : 'password'}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete={autoComplete}
        minLength={8}
        required
        className="pr-11"
      />
      <button
        type="button"
        onClick={() => setShowPassword((current) => !current)}
        className="absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={label}
        title={label}
      >
        {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  )
}
