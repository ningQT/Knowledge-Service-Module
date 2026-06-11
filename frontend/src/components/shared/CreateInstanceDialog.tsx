import { useCallback, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { createInstance } from '@/services/instances'
import type { Instance } from '@/types/api'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { formatApiError } from '@/lib/i18nFormat'

interface CreateInstanceDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (instance: Instance) => void
}

export function CreateInstanceDialog({ open, onOpenChange, onCreated }: CreateInstanceDialogProps) {
  const { t } = useTranslation('dashboard')
  const [name, setName] = useState('')
  const [autoMap, setAutoMap] = useState(true)
  const [language, setLanguage] = useState<'zh' | 'en'>('zh')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reset = useCallback(() => {
    setName('')
    setAutoMap(true)
    setLanguage('zh')
    setError(null)
  }, [])

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      onOpenChange(nextOpen)
      if (!nextOpen) reset()
    },
    [onOpenChange, reset]
  )

  const handleCreate = useCallback(async () => {
    if (!name.trim() || creating) return
    setCreating(true)
    setError(null)
    try {
      const instance = await createInstance({
        name: name.trim(),
        template_id: 'standard_v1',
        auto_map: autoMap,
        language,
      })
      onCreated(instance)
      handleOpenChange(false)
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setCreating(false)
    }
  }, [autoMap, creating, handleOpenChange, language, name, onCreated, t])

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('createDialog.title')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div>
            <label className="block text-sm font-medium mb-1">{t('createDialog.name')}</label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('createDialog.namePlaceholder')}
            />
          </div>
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium">{t('createDialog.autoMap')}</label>
            <Switch checked={autoMap} onCheckedChange={setAutoMap} />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">{t('createDialog.language')}</label>
            <Select value={language} onValueChange={(value) => setLanguage(value as 'zh' | 'en')}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="zh">{t('createDialog.languageZh')}</SelectItem>
                <SelectItem value="en">{t('createDialog.languageEn')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {error && (
            <div className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</div>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => handleOpenChange(false)}>
            {t('createDialog.cancel')}
          </Button>
          <Button onClick={handleCreate} disabled={!name.trim() || creating}>
            {creating && <Loader2 className="h-4 w-4 animate-spin" />}
            {t('createDialog.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
