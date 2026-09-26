import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { deleteInstance, getInstancePermissions, listBoundApiKeys } from '@/services/instances'
import type { Instance } from '@/types/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
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

interface DeleteInstanceDialogProps {
  instance: Instance | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onDeleted?: (instanceId: string) => void
}

export function DeleteInstanceDialog({
  instance,
  open,
  onOpenChange,
  onDeleted,
}: DeleteInstanceDialogProps) {
  const { t } = useTranslation('dashboard')
  const [confirmName, setConfirmName] = useState('')
  const [deleteFiles, setDeleteFiles] = useState(false)
  const [accountCount, setAccountCount] = useState(0)
  const [keyCount, setKeyCount] = useState(0)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')

  useEffect(() => {
    if (!open || !instance) return
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) {
        setConfirmName('')
        setDeleteFiles(false)
        setPreviewError('')
        setDeleteError('')
        setPreviewLoading(true)
      }
    })
    Promise.all([
      getInstancePermissions(instance.id),
      listBoundApiKeys(instance.id),
    ])
      .then(([permissions, keys]) => {
        if (cancelled) return
        setAccountCount(permissions.accounts.filter((item) => item.permission !== 'none').length)
        setKeyCount(keys.length)
      })
      .catch((error) => {
        if (!cancelled) setPreviewError(formatApiError(t, error))
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false)
      })
    return () => { cancelled = true }
  }, [instance, open, t])

  async function handleDelete() {
    if (!instance || confirmName !== instance.name || deleting) return
    setDeleting(true)
    setDeleteError('')
    try {
      await deleteInstance(instance.id, instance.name, { deleteFiles })
      onOpenChange(false)
      onDeleted?.(instance.id)
    } catch (error) {
      setDeleteError(formatApiError(t, error))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('manage.deleteTitle')}</DialogTitle>
          <DialogDescription>
            {instance?.name ? `${t('manage.deleteDescription')} (${instance.name})` : t('manage.deleteDescription')}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {previewLoading ? t('manage.deleteImpactLoading') : t('manage.deleteImpactCounts', {
              accounts: accountCount,
              keys: keyCount,
            })}
          </div>
          {previewError && <div className="rounded bg-warning/10 p-2 text-sm text-warning">{previewError}</div>}
          <Input
            value={confirmName}
            onChange={(event) => setConfirmName(event.target.value)}
            placeholder={t('manage.deleteNamePlaceholder')}
          />
          <label className="flex items-center justify-between gap-3 rounded-md border border-border p-3 text-sm">
            <span>{t('manage.deleteFiles')}</span>
            <Switch checked={deleteFiles} onCheckedChange={setDeleteFiles} />
          </label>
          {deleteError && <div className="rounded bg-destructive/10 p-2 text-sm text-destructive">{deleteError}</div>}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('manage.cancel')}</Button>
          <Button
            variant="destructive"
            onClick={() => void handleDelete()}
            disabled={deleting || previewLoading || confirmName !== instance?.name}
          >
            {deleting && <Loader2 className="h-4 w-4 animate-spin" />}
            {t('manage.confirmDelete')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
