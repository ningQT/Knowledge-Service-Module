import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { getInstancePermissions, updateInstancePermissions } from '@/services/instances'
import type { Instance, InstancePermissionAccount } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatApiError } from '@/lib/i18nFormat'
import { useTranslation } from 'react-i18next'

interface Props {
  instance: Instance | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function InstancePermissionDialog({ instance, open, onOpenChange }: Props) {
  const { t } = useTranslation('common')
  const [accounts, setAccounts] = useState<InstancePermissionAccount[]>([])
  const [ownerName, setOwnerName] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!instance) return
    setLoading(true)
    setError('')
    try {
      const data = await getInstancePermissions(instance.id)
      setAccounts(data.accounts)
      setOwnerName(data.owner.username)
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setLoading(false)
    }
  }, [instance, t])

  useEffect(() => {
    if (open) queueMicrotask(load)
  }, [load, open])

  function changePermission(accountId: string, permission: InstancePermissionAccount['permission']) {
    setAccounts((current) => current.map((item) => item.account_id === accountId ? { ...item, permission } : item))
  }

  async function handleSave() {
    if (!instance) return
    const affected = accounts
      .filter((item) => item.permission !== 'edit' && item.affected_api_key_count > 0)
      .reduce((sum, item) => sum + item.affected_api_key_count, 0)
    if (affected > 0 && !window.confirm(t('permissions.removeKeysConfirm', { count: affected }))) return
    setSaving(true)
    setError('')
    try {
      await updateInstancePermissions(
        instance.id,
        accounts.map((item) => ({ account_id: item.account_id, permission: item.permission }))
      )
      onOpenChange(false)
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('permissions.dialogTitle', { name: instance?.name })}</DialogTitle>
          <DialogDescription>{t('permissions.dialogDescription')}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[420px] space-y-2 overflow-auto">
          <div className="flex items-center justify-between rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
            <span>{ownerName}</span>
            <Badge>{t('permissions.owner')}</Badge>
          </div>
          {loading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin" /></div>
          ) : accounts.map((account) => (
            <div key={account.account_id} className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-sm">{account.username}</span>
                {account.affected_api_key_count > 0 && <Badge variant="outline">{t('permissions.affectedKeys', { count: account.affected_api_key_count })}</Badge>}
              </div>
              <Select value={account.permission} onValueChange={(value) => changePermission(account.account_id, value as InstancePermissionAccount['permission'])}>
                <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t('permissions.none')}</SelectItem>
                  <SelectItem value="read">{t('permissions.read')}</SelectItem>
                  <SelectItem value="edit">{t('permissions.edit')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          ))}
          {!loading && accounts.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">{t('permissions.emptyAccounts')}</p>}
        </div>
        {error && <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>{t('cancel')}</Button>
          <Button onClick={() => void handleSave()} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            {t('permissions.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
