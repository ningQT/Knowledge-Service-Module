import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { listBoundApiKeys } from '@/services/instances'
import type { BoundApiKey, Instance } from '@/types/api'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatApiError } from '@/lib/i18nFormat'
import { useTranslation } from 'react-i18next'

interface Props {
  instance: Instance | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function BoundApiKeysDialog({ instance, open, onOpenChange }: Props) {
  const { t } = useTranslation('common')
  const [keys, setKeys] = useState<BoundApiKey[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!instance) return
    setLoading(true)
    setError('')
    try {
      setKeys(await listBoundApiKeys(instance.id))
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setLoading(false)
    }
  }, [instance, t])

  useEffect(() => {
    if (open) queueMicrotask(load)
  }, [load, open])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('boundApiKeys.title', { name: instance?.name })}</DialogTitle>
          <DialogDescription>{t('boundApiKeys.description')}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[420px] divide-y overflow-auto rounded-md border border-border">
          {loading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin" /></div>
          ) : keys.map((key) => (
            <div key={key.id} className="grid gap-2 px-3 py-3 text-sm sm:grid-cols-[1fr_120px_100px]">
              <div>
                <p className="font-medium">{key.name}</p>
                <p className="font-mono text-xs text-muted-foreground">{key.key_prefix}...</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {key.last_used_at
                    ? t('boundApiKeys.lastUsed', { value: new Date(key.last_used_at).toLocaleString() })
                    : t('boundApiKeys.neverUsed')}
                </p>
              </div>
              <span className="text-muted-foreground">{key.owner_username}</span>
              <div className="flex items-center gap-2">
                <Badge variant="outline">{key.scope === 'write' ? t('boundApiKeys.write') : t('boundApiKeys.read')}</Badge>
                <Badge variant={key.enabled ? 'secondary' : 'outline'}>{key.enabled ? t('boundApiKeys.enabled') : t('boundApiKeys.disabled')}</Badge>
              </div>
            </div>
          ))}
          {!loading && keys.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">{t('boundApiKeys.empty')}</p>}
        </div>
        {error && <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}
      </DialogContent>
    </Dialog>
  )
}
