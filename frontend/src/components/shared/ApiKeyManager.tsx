import { useCallback, useEffect, useState } from 'react'
import { Copy, KeyRound, Loader2, Pencil, Power, PowerOff, RefreshCw, Trash2 } from 'lucide-react'
import {
  createApiKey,
  deleteApiKey,
  listApiKeys,
  rotateApiKey,
  updateApiKey,
} from '@/services/auth'
import { listInstances } from '@/services/instances'
import type { ApiKeyClient, Instance } from '@/types/api'
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatApiError } from '@/lib/i18nFormat'
import { useTranslation } from 'react-i18next'

export interface ApiKeyManagerSummary {
  totalKeys: number
  enabledKeys: number
  readKeys: number
  writeKeys: number
  instanceCount: number
  authorizedInstanceCount: number
  lastUsedAt: string | null
}

type ApiKeySecretNotice = {
  secret: string
  keyName: string
  mode: 'created' | 'rotated'
}

interface ApiKeyManagerProps {
  onSummaryChange?: (summary: ApiKeyManagerSummary) => void
}

function summarizeApiKeys(keys: ApiKeyClient[], instances: Instance[]): ApiKeyManagerSummary {
  const authorizedIds = new Set<string>()
  let lastUsedAt: string | null = null

  keys.forEach((key) => {
    key.instance_ids.forEach((id) => authorizedIds.add(id))
    if (!key.last_used_at) return
    if (!lastUsedAt || Date.parse(key.last_used_at) > Date.parse(lastUsedAt)) {
      lastUsedAt = key.last_used_at
    }
  })

  return {
    totalKeys: keys.length,
    enabledKeys: keys.filter((key) => key.enabled).length,
    readKeys: keys.filter((key) => key.scope === 'read').length,
    writeKeys: keys.filter((key) => key.scope === 'write').length,
    instanceCount: instances.length,
    authorizedInstanceCount: authorizedIds.size,
    lastUsedAt,
  }
}

export function ApiKeyManager({ onSummaryChange }: ApiKeyManagerProps) {
  const { t } = useTranslation(['apiManagement', 'common'])
  const [apiKeys, setApiKeys] = useState<ApiKeyClient[]>([])
  const [instances, setInstances] = useState<Instance[]>([])
  const [apiKeysLoading, setApiKeysLoading] = useState(true)
  const [apiKeyBusy, setApiKeyBusy] = useState<string | null>(null)
  const [apiKeyError, setApiKeyError] = useState('')
  const [secretNotice, setSecretNotice] = useState<ApiKeySecretNotice | null>(null)
  const [secretCopyStatus, setSecretCopyStatus] = useState<'copied' | 'failed' | null>(null)
  const [editingApiKey, setEditingApiKey] = useState<ApiKeyClient | null>(null)
  const [editingInstanceIds, setEditingInstanceIds] = useState<string[]>([])
  const [newKeyName, setNewKeyName] = useState('')
  const [newKeyScope, setNewKeyScope] = useState<'read' | 'write'>('read')
  const [newKeyInstanceIds, setNewKeyInstanceIds] = useState<string[]>([])

  const updateSummary = useCallback((keys: ApiKeyClient[], instanceList = instances) => {
    onSummaryChange?.(summarizeApiKeys(keys, instanceList))
  }, [instances, onSummaryChange])

  const loadApiKeySection = useCallback(async () => {
    setApiKeysLoading(true)
    setApiKeyError('')
    try {
      const [keys, instanceList] = await Promise.all([listApiKeys(), listInstances()])
      setApiKeys(keys)
      setInstances(instanceList)
      onSummaryChange?.(summarizeApiKeys(keys, instanceList))
    } catch (e) {
      setApiKeyError(formatApiError(t, e))
    }
    setApiKeysLoading(false)
  }, [onSummaryChange, t])

  useEffect(() => {
    queueMicrotask(() => {
      void loadApiKeySection()
    })
  }, [loadApiKeySection])

  function toggleNewKeyInstance(instanceId: string) {
    setNewKeyInstanceIds((current) => (
      current.includes(instanceId)
        ? current.filter((id) => id !== instanceId)
        : [...current, instanceId]
    ))
  }

  async function handleCreateApiKey() {
    if (!newKeyName.trim()) {
      setApiKeyError(t('apiKeys.error.nameRequired'))
      return
    }

    setApiKeyBusy('create')
    setApiKeyError('')
    try {
      const result = await createApiKey({
        name: newKeyName,
        scope: newKeyScope,
        instance_ids: newKeyInstanceIds,
      })
      const nextKeys = [result.api_key, ...apiKeys]
      setApiKeys(nextKeys)
      updateSummary(nextKeys)
      setSecretNotice({
        secret: result.secret,
        keyName: result.api_key.name,
        mode: 'created',
      })
      setSecretCopyStatus(null)
      setNewKeyName('')
      setNewKeyInstanceIds([])
    } catch (e) {
      setApiKeyError(formatApiError(t, e))
    }
    setApiKeyBusy(null)
  }

  async function handleToggleApiKey(key: ApiKeyClient) {
    setApiKeyBusy(key.id)
    setApiKeyError('')
    try {
      const updated = await updateApiKey(key.id, { enabled: !key.enabled })
      const nextKeys = apiKeys.map((item) => item.id === key.id ? updated : item)
      setApiKeys(nextKeys)
      updateSummary(nextKeys)
    } catch (e) {
      setApiKeyError(formatApiError(t, e))
    }
    setApiKeyBusy(null)
  }

  async function handleRotateApiKey(key: ApiKeyClient) {
    if (!window.confirm(t('apiKeys.confirm.rotate'))) return
    setApiKeyBusy(key.id)
    setApiKeyError('')
    try {
      const result = await rotateApiKey(key.id)
      const nextKeys = apiKeys.map((item) => item.id === key.id ? result.api_key : item)
      setApiKeys(nextKeys)
      updateSummary(nextKeys)
      setSecretNotice({
        secret: result.secret,
        keyName: result.api_key.name,
        mode: 'rotated',
      })
      setSecretCopyStatus(null)
    } catch (e) {
      setApiKeyError(formatApiError(t, e))
    }
    setApiKeyBusy(null)
  }

  async function handleDeleteApiKey(key: ApiKeyClient) {
    if (!window.confirm(t('apiKeys.confirm.delete'))) return
    setApiKeyBusy(key.id)
    setApiKeyError('')
    try {
      await deleteApiKey(key.id)
      const nextKeys = apiKeys.filter((item) => item.id !== key.id)
      setApiKeys(nextKeys)
      updateSummary(nextKeys)
    } catch (e) {
      setApiKeyError(formatApiError(t, e))
    }
    setApiKeyBusy(null)
  }

  async function copyCreatedSecret() {
    if (!secretNotice) return
    try {
      if (!navigator.clipboard) {
        setSecretCopyStatus('failed')
        return
      }
      await navigator.clipboard.writeText(secretNotice.secret)
      setSecretCopyStatus('copied')
    } catch {
      setSecretCopyStatus('failed')
    }
  }

  function closeSecretDialog() {
    setSecretNotice(null)
    setSecretCopyStatus(null)
  }

  function openEditApiKey(key: ApiKeyClient) {
    setApiKeyError('')
    setEditingApiKey(key)
    setEditingInstanceIds(key.instance_ids)
  }

  function toggleEditingInstance(instanceId: string) {
    setEditingInstanceIds((current) => (
      current.includes(instanceId)
        ? current.filter((id) => id !== instanceId)
        : [...current, instanceId]
    ))
  }

  async function handleSaveApiKeyPermissions() {
    if (!editingApiKey) return
    setApiKeyBusy(`edit:${editingApiKey.id}`)
    setApiKeyError('')
    try {
      const updated = await updateApiKey(editingApiKey.id, { instance_ids: editingInstanceIds })
      const nextKeys = apiKeys.map((item) => item.id === updated.id ? updated : item)
      setApiKeys(nextKeys)
      updateSummary(nextKeys)
      setEditingApiKey(null)
      setEditingInstanceIds([])
    } catch (e) {
      setApiKeyError(formatApiError(t, e))
    }
    setApiKeyBusy(null)
  }

  return (
    <div className="bg-card rounded-lg border border-border p-6 space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/10 text-primary">
            <KeyRound className="h-4 w-4" />
          </div>
          <div>
            <h3 className="font-medium">{t('apiKeys.title')}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{t('apiKeys.description')}</p>
          </div>
        </div>
        <Button variant="secondary" size="sm" onClick={loadApiKeySection} disabled={apiKeysLoading}>
          {apiKeysLoading && <Loader2 className="animate-spin" />}
          {t('apiKeys.refresh')}
        </Button>
      </div>

      {apiKeyError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {apiKeyError}
        </div>
      )}

      <div className="rounded-md border border-border p-4 space-y-4">
        <div className="grid gap-3 md:grid-cols-[1fr_160px]">
          <div>
            <label className="block text-sm font-medium mb-1">{t('apiKeys.create.name')}</label>
            <Input
              value={newKeyName}
              onChange={(event) => setNewKeyName(event.target.value)}
              placeholder={t('apiKeys.create.namePlaceholder')}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">{t('apiKeys.create.scope')}</label>
            <Select value={newKeyScope} onValueChange={(value) => setNewKeyScope(value as 'read' | 'write')}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t('apiKeys.scope.read')}</SelectItem>
                <SelectItem value="write">{t('apiKeys.scope.write')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div>
          <div className="mb-2 text-sm font-medium">{t('apiKeys.create.instances')}</div>
          {instances.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('apiKeys.create.noInstances')}</p>
          ) : (
            <div className="grid gap-2 md:grid-cols-2">
              {instances.map((instance) => (
                <label
                  key={instance.id}
                  className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm"
                >
                  <input
                    type="checkbox"
                    checked={newKeyInstanceIds.includes(instance.id)}
                    onChange={() => toggleNewKeyInstance(instance.id)}
                    className="h-4 w-4 accent-primary"
                  />
                  <span className="truncate">{instance.name}</span>
                </label>
              ))}
            </div>
          )}
        </div>

        <Button onClick={handleCreateApiKey} disabled={apiKeyBusy === 'create'}>
          {apiKeyBusy === 'create' && <Loader2 className="animate-spin" />}
          {t('apiKeys.create.submit')}
        </Button>
      </div>

      <div className="space-y-3">
        {apiKeysLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('apiKeys.loading')}
          </div>
        ) : apiKeys.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('apiKeys.empty')}</p>
        ) : (
          apiKeys.map((key) => (
            <div key={key.id} className="rounded-md border border-border p-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium truncate">{key.name}</span>
                    <Badge variant={key.enabled ? 'secondary' : 'outline'}>
                      {key.enabled ? t('apiKeys.status.enabled') : t('apiKeys.status.disabled')}
                    </Badge>
                    <Badge variant="outline">{t(`apiKeys.scope.${key.scope}`)}</Badge>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {key.key_prefix}...
                    <span className="mx-1">/</span>
                    {t('apiKeys.instancesCount', { count: key.instance_ids.length })}
                    <span className="mx-1">/</span>
                    {key.last_used_at
                      ? t('apiKeys.lastUsed', { value: new Date(key.last_used_at).toLocaleString() })
                      : t('apiKeys.neverUsed')}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => openEditApiKey(key)}
                    disabled={apiKeyBusy === key.id}
                  >
                    <Pencil />
                    {t('apiKeys.action.edit')}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleToggleApiKey(key)}
                    disabled={apiKeyBusy === key.id}
                  >
                    {key.enabled ? <PowerOff /> : <Power />}
                    {key.enabled ? t('apiKeys.action.disable') : t('apiKeys.action.enable')}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleRotateApiKey(key)}
                    disabled={apiKeyBusy === key.id}
                  >
                    <RefreshCw />
                    {t('apiKeys.action.rotate')}
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => handleDeleteApiKey(key)}
                    disabled={apiKeyBusy === key.id}
                  >
                    <Trash2 />
                    {t('apiKeys.action.delete')}
                  </Button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      <Dialog
        open={Boolean(editingApiKey)}
        onOpenChange={(open) => {
          if (!open) {
            setEditingApiKey(null)
            setEditingInstanceIds([])
          }
        }}
      >
        <DialogContent className="sm:max-w-xl">
          {editingApiKey && (
            <>
              <DialogHeader>
                <DialogTitle>{t('apiKeys.edit.title', { name: editingApiKey.name })}</DialogTitle>
                <DialogDescription>{t('apiKeys.edit.description')}</DialogDescription>
              </DialogHeader>

              <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{editingApiKey.name}</span>
                  <Badge variant={editingApiKey.enabled ? 'secondary' : 'outline'}>
                    {editingApiKey.enabled ? t('apiKeys.status.enabled') : t('apiKeys.status.disabled')}
                  </Badge>
                  <Badge variant="outline">{t(`apiKeys.scope.${editingApiKey.scope}`)}</Badge>
                </div>
                <div className="mt-1 font-mono text-xs text-muted-foreground">
                  {editingApiKey.key_prefix}...
                </div>
              </div>

              <div>
                <div className="mb-2 text-sm font-medium">{t('apiKeys.edit.instances')}</div>
                {instances.length === 0 ? (
                  <p className="rounded-md border border-border px-3 py-2 text-sm text-muted-foreground">
                    {t('apiKeys.edit.noInstances')}
                  </p>
                ) : (
                  <div className="grid max-h-64 gap-2 overflow-auto pr-1 md:grid-cols-2">
                    {instances.map((instance) => (
                      <label
                        key={instance.id}
                        className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm"
                      >
                        <input
                          type="checkbox"
                          checked={editingInstanceIds.includes(instance.id)}
                          onChange={() => toggleEditingInstance(instance.id)}
                          className="h-4 w-4 accent-primary"
                        />
                        <span className="truncate">{instance.name}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>

              <DialogFooter>
                <Button
                  variant="secondary"
                  onClick={() => {
                    setEditingApiKey(null)
                    setEditingInstanceIds([])
                  }}
                >
                  {t('apiKeys.edit.cancel')}
                </Button>
                <Button
                  onClick={handleSaveApiKeyPermissions}
                  disabled={instances.length === 0 || apiKeyBusy === `edit:${editingApiKey.id}`}
                >
                  {apiKeyBusy === `edit:${editingApiKey.id}` && <Loader2 className="animate-spin" />}
                  {t('apiKeys.edit.save')}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(secretNotice)}
        onOpenChange={(open) => {
          if (!open) closeSecretDialog()
        }}
      >
        <DialogContent className="sm:max-w-xl">
          {secretNotice && (
            <>
              <DialogHeader>
                <DialogTitle>{t(`apiKeys.secret.title.${secretNotice.mode}`, { name: secretNotice.keyName })}</DialogTitle>
                <DialogDescription>{t('apiKeys.secret.description')}</DialogDescription>
              </DialogHeader>

              <div className="space-y-3">
                <div className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
                  {t('apiKeys.secret.warning')}
                </div>
                <div className="flex gap-2">
                  <Input value={secretNotice.secret} readOnly className="font-mono text-xs" />
                  <Button variant="secondary" size="icon" onClick={copyCreatedSecret} title={t('apiKeys.secret.copy')}>
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                {secretCopyStatus && (
                  <p
                    className={
                      secretCopyStatus === 'copied'
                        ? 'text-sm text-success'
                        : 'text-sm text-destructive'
                    }
                  >
                    {t(`apiKeys.secret.${secretCopyStatus}`)}
                  </p>
                )}
              </div>

              <DialogFooter>
                <Button onClick={closeSecretDialog}>
                  {t('apiKeys.secret.close')}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
