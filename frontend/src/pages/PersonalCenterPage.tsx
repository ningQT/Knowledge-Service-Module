import { useState, type FormEvent } from 'react'
import { Loader2, ShieldCheck, UserCircle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { changePassword } from '@/services/auth'
import { useAuthStore } from '@/stores/useAuthStore'
import { formatApiError } from '@/lib/i18nFormat'
import { useTranslation } from 'react-i18next'

export default function PersonalCenterPage() {
  const { user, resetAuth } = useAuthStore()
  const { t } = useTranslation('common')
  const navigate = useNavigate()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (newPassword !== confirmPassword) {
      setError(t('personalCenter.passwordMismatch'))
      return
    }
    setBusy(true)
    setError('')
    try {
      await changePassword({ current_password: currentPassword, new_password: newPassword })
      resetAuth()
      navigate('/')
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold">{t('personalCenter.title')}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t('personalCenter.description')}</p>
      </div>
      <div className="rounded-lg border border-border bg-card p-6">
        <div className="flex items-center gap-3">
          <UserCircle className="h-10 w-10 text-primary" />
          <div>
            <p className="font-medium">{user?.username}</p>
            <p className="text-sm text-muted-foreground">{user?.role === 'admin' ? t('personalCenter.administrator') : t('personalCenter.user')}</p>
          </div>
        </div>
      </div>
      <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border border-border bg-card p-6">
        <div className="flex items-center gap-2 font-medium">
          <ShieldCheck className="h-4 w-4" />
          {t('personalCenter.changePassword')}
        </div>
        <Input type="password" placeholder={t('personalCenter.currentPassword')} value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required />
        <Input type="password" placeholder={t('personalCenter.newPassword')} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required minLength={8} />
        <Input type="password" placeholder={t('personalCenter.confirmPassword')} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required minLength={8} />
        {error && <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}
        <Button type="submit" disabled={busy}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          {t('personalCenter.savePassword')}
        </Button>
      </form>
    </div>
  )
}
