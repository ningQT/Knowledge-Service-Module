import { useCallback, useEffect, useState } from 'react'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import {
  createAccount,
  deleteAccount,
  listAccounts,
  resetAccountPassword,
  updateAccount,
} from '@/services/auth'
import type { AccountSummary } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatApiError } from '@/lib/i18nFormat'
import { useTranslation } from 'react-i18next'

export function AccountManager() {
  const { t } = useTranslation('common')
  const [accounts, setAccounts] = useState<AccountSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<AccountSummary | null>(null)
  const [confirmUsername, setConfirmUsername] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setAccounts(await listAccounts())
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    queueMicrotask(load)
  }, [load])

  async function handleCreate() {
    setBusyId('create')
    setError('')
    try {
      await createAccount({ username, password, enabled: true })
      setCreateOpen(false)
      setUsername('')
      setPassword('')
      await load()
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setBusyId('')
    }
  }

  async function handleToggle(account: AccountSummary) {
    setBusyId(account.id)
    setError('')
    try {
      await updateAccount(account.id, { enabled: !account.enabled })
      await load()
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setBusyId('')
    }
  }

  async function handleReset(account: AccountSummary) {
    const nextPassword = window.prompt(t('account.resetPrompt', { username: account.username }))
    if (!nextPassword) return
    setBusyId(account.id)
    try {
      await resetAccountPassword(account.id, nextPassword)
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setBusyId('')
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return
    setBusyId(deleteTarget.id)
    try {
      await deleteAccount(deleteTarget.id, confirmUsername)
      setDeleteTarget(null)
      setConfirmUsername('')
      await load()
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setBusyId('')
    }
  }

  if (loading) {
    return <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin" /></div>
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-medium">{t('account.management')}</h3>
          <p className="text-sm text-muted-foreground">{t('account.managementDescription')}</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          {t('account.create')}
        </Button>
      </div>
      {error && <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}
      <div className="divide-y rounded-lg border border-border bg-card">
        {accounts.map((account) => (
          <div key={account.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="font-medium">{account.username}</span>
              <Badge variant={account.enabled ? 'secondary' : 'outline'}>
                {account.enabled ? t('account.enabled') : t('account.disabled')}
              </Badge>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" onClick={() => void handleToggle(account)} disabled={busyId === account.id}>
                {account.enabled ? t('account.disabled') : t('account.enabled')}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => void handleReset(account)} disabled={busyId === account.id}>
                {t('account.resetPassword')}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(account)}>
                <Trash2 className="h-4 w-4" />
                {t('account.delete')}
              </Button>
            </div>
          </div>
        ))}
        {accounts.length === 0 && <div className="px-4 py-8 text-center text-sm text-muted-foreground">{t('account.empty')}</div>}
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('account.createTitle')}</DialogTitle>
            <DialogDescription>{t('account.createDescription')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input placeholder={t('account.username')} value={username} onChange={(e) => setUsername(e.target.value)} />
            <Input type="password" placeholder={t('account.initialPassword')} value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>{t('cancel')}</Button>
            <Button onClick={() => void handleCreate()} disabled={busyId === 'create'}>{t('account.createAction')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('account.deleteTitle')}</DialogTitle>
            <DialogDescription>
              {t('account.deleteDescription', { username: deleteTarget?.username })}
            </DialogDescription>
          </DialogHeader>
          <Input value={confirmUsername} onChange={(e) => setConfirmUsername(e.target.value)} placeholder={t('account.confirmUsername')} />
          <DialogFooter>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>{t('cancel')}</Button>
            <Button variant="destructive" onClick={() => void handleDelete()} disabled={confirmUsername !== deleteTarget?.username}>
              {t('account.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
