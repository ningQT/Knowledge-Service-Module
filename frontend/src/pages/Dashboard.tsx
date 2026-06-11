import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileText, Map, BookOpen, GitBranch, Upload, Search, Network, Plus, Loader2, Pencil, Trash2, Copy, Check } from 'lucide-react'
import { useInstanceStore } from '@/stores/useInstanceStore'
import { listInstances, getInstanceStats, updateInstance, deleteInstance } from '@/services/instances'
import type { Instance, InstanceStats } from '@/types/api'
import { LoadingState } from '@/components/shared/LoadingState'
import { CreateInstanceDialog } from '@/components/shared/CreateInstanceDialog'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { formatApiError } from '@/lib/i18nFormat'
import { useTranslation } from 'react-i18next'

export default function Dashboard() {
  const navigate = useNavigate()
  const { instances, setInstances, instanceId, setInstanceId } = useInstanceStore()
  const [stats, setStats] = useState<InstanceStats | null>(null)
  const [instanceStats, setInstanceStats] = useState<Record<string, InstanceStats>>({})
  const [loading, setLoading] = useState(true)
  const { t } = useTranslation('dashboard')

  const [createOpen, setCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Instance | null>(null)
  const [editName, setEditName] = useState('')
  const [editAutoMap, setEditAutoMap] = useState(true)
  const [editing, setEditing] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Instance | null>(null)
  const [deleteFiles, setDeleteFiles] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [manageMessage, setManageMessage] = useState<string | null>(null)
  const [copiedInstanceId, setCopiedInstanceId] = useState<string | null>(null)

  const refreshInstances = useCallback(async () => {
    const list = await listInstances()
    setInstances(list)
    const results = await Promise.allSettled(list.map((inst) => getInstanceStats(inst.id)))
    const statsMap: Record<string, InstanceStats> = {}
    results.forEach((r, i) => {
      if (r.status === 'fulfilled') statsMap[list[i].id] = r.value
    })
    setInstanceStats(statsMap)
    return list
  }, [setInstances])

  const handleCreated = useCallback((instance: Instance) => {
    setInstanceId(instance.id)
    setManageMessage(null)
    void refreshInstances()
  }, [refreshInstances, setInstanceId])

  const openEdit = useCallback((instance: Instance) => {
    setEditTarget(instance)
    setEditName(instance.name)
    setEditAutoMap(instance.auto_map)
    setEditError(null)
    setManageMessage(null)
  }, [])

  const handleEdit = useCallback(async () => {
    if (!editTarget || !editName.trim() || editing) return
    setEditing(true)
    setEditError(null)
    try {
      const updated = await updateInstance(editTarget.id, {
        name: editName.trim(),
        auto_map: editAutoMap,
      })
      setEditTarget(null)
      setManageMessage(t('manage.updated'))
      if (instanceId === updated.id) setInstanceId(updated.id)
      void refreshInstances()
    } catch (e) {
      setEditError(formatApiError(t, e))
    } finally {
      setEditing(false)
    }
  }, [editAutoMap, editName, editTarget, editing, instanceId, refreshInstances, setInstanceId, t])

  const openDelete = useCallback((instance: Instance) => {
    setDeleteTarget(instance)
    setDeleteFiles(false)
    setDeleteError(null)
    setManageMessage(null)
  }, [])

  const handleDelete = useCallback(async () => {
    if (!deleteTarget || deleting) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteInstance(deleteTarget.id, { deleteFiles })
      const list = await refreshInstances()
      if (instanceId === deleteTarget.id) {
        setInstanceId(list[0]?.id ?? null)
      }
      setDeleteTarget(null)
      setManageMessage(t('manage.deleted'))
    } catch (e) {
      setDeleteError(formatApiError(t, e))
    } finally {
      setDeleting(false)
    }
  }, [deleteFiles, deleteTarget, deleting, instanceId, refreshInstances, setInstanceId, t])

  const copyInstanceId = useCallback(async (id: string) => {
    try {
      await navigator.clipboard.writeText(id)
      setCopiedInstanceId(id)
      setManageMessage(t('table.copy.copied'))
      window.setTimeout(() => setCopiedInstanceId((current) => current === id ? null : current), 1600)
    } catch (e) {
      console.error('Failed to copy instance id:', e)
    }
  }, [t])

  useEffect(() => {
    listInstances().then((list: Instance[]) => {
      setInstances(list)
      if (list.length > 0 && !instanceId) {
        setInstanceId(list[0].id)
      }
      setLoading(false)

      // Load stats for all instances in parallel
      Promise.allSettled(list.map((inst) => getInstanceStats(inst.id))).then((results) => {
        const statsMap: Record<string, InstanceStats> = {}
        results.forEach((r, i) => {
          if (r.status === 'fulfilled') statsMap[list[i].id] = r.value
        })
        setInstanceStats(statsMap)
      })
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (instanceId) {
      getInstanceStats(instanceId).then(setStats).catch((e) => { console.error('Failed to load stats:', e); setStats(null) })
    }
  }, [instanceId])

  if (loading) return <LoadingState />

  const statCards = [
    { label: t('statCards.cards'), value: stats?.by_type?.card || 0, icon: FileText, color: 'text-layer-card' },
    { label: t('statCards.maps'), value: stats?.by_type?.map || 0, icon: Map, color: 'text-layer-map' },
    { label: t('statCards.sources'), value: stats?.by_type?.source || 0, icon: BookOpen, color: 'text-layer-source' },
    { label: t('statCards.relations'), value: stats?.total_relations || 0, icon: GitBranch, color: 'text-primary' },
  ]

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="w-4 h-4 mr-1" />
          {t('createInstance')}
        </Button>
      </div>
      {manageMessage && <p className="text-sm text-success">{manageMessage}</p>}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((card) => (
          <div key={card.label} className="bg-card rounded-lg border border-border p-4">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground text-sm">{card.label}</span>
              <card.icon className={`w-5 h-5 ${card.color}`} />
            </div>
            <p className="text-3xl font-bold font-mono mt-2">{card.value}</p>
          </div>
        ))}
      </div>

      <div className="bg-card rounded-lg border border-border">
        <div className="px-4 py-3 border-b border-border">
          <h2 className="font-semibold">{t('table.title')}</h2>
        </div>
        <div className="divide-y divide-border">
          <div className="hidden lg:grid grid-cols-[minmax(240px,1fr)_76px_72px_72px_72px_84px_110px_90px] items-center gap-3 px-4 py-2 text-xs text-muted-foreground font-medium border-b border-border">
            <span>{t('table.col.instance')}</span>
            <span>{t('table.col.language')}</span>
            <span className="text-right">{t('table.col.cards')}</span>
            <span className="text-right">{t('table.col.maps')}</span>
            <span className="text-right">{t('table.col.sources')}</span>
            <span className="text-right">{t('table.col.relations')}</span>
            <span className="text-right">{t('table.col.updated')}</span>
            <span className="text-right">{t('table.col.actions')}</span>
          </div>
          {instances.map((inst) => {
            const s = instanceStats[inst.id]
            const languageLabel = inst.language === 'en' ? t('createDialog.languageEn') : t('createDialog.languageZh')
            return (
              <div
                key={inst.id}
                className="flex cursor-pointer items-center justify-between gap-3 px-4 py-3 hover:bg-muted/50 lg:grid lg:grid-cols-[minmax(240px,1fr)_76px_72px_72px_72px_84px_110px_90px]"
                onClick={() => {
                  setInstanceId(inst.id)
                  navigate('/graph')
                }}
              >
                <div className="min-w-0">
                  <p className="font-medium">{inst.name}</p>
                  <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5">
                    <span className="text-xs text-muted-foreground">{t('table.instanceId')}</span>
                    <code className="max-w-full truncate rounded border border-border bg-muted/40 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                      {inst.id}
                    </code>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      title={t('table.copy.title')}
                      onClick={(e) => {
                        e.stopPropagation()
                        void copyInstanceId(inst.id)
                      }}
                    >
                      {copiedInstanceId === inst.id ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                    </Button>
                    <span className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-[11px] text-muted-foreground lg:hidden">
                      {languageLabel}
                    </span>
                  </div>
                </div>
                <span className="hidden lg:block text-sm text-muted-foreground">{languageLabel}</span>
                <span className="hidden lg:block text-right text-sm font-mono tabular-nums">{s?.by_type?.card ?? '-'}</span>
                <span className="hidden lg:block text-right text-sm font-mono tabular-nums">{s?.by_type?.map ?? '-'}</span>
                <span className="hidden lg:block text-right text-sm font-mono tabular-nums">{s?.by_type?.source ?? '-'}</span>
                <span className="hidden lg:block text-right text-sm font-mono tabular-nums">{s?.total_relations ?? '-'}</span>
                <span className="text-xs text-muted-foreground text-right">
                  {new Date(inst.updated_at).toLocaleDateString()}
                </span>
                <div className="flex justify-end gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    title={t('manage.edit')}
                    onClick={(e) => {
                      e.stopPropagation()
                      openEdit(inst)
                    }}
                  >
                    <Pencil className="h-3 w-3" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    title={t('manage.delete')}
                    onClick={(e) => {
                      e.stopPropagation()
                      openDelete(inst)
                    }}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            )
          })}
          {instances.length === 0 && (
            <p className="px-4 py-8 text-center text-muted-foreground text-sm">{t('noInstances')}</p>
          )}
        </div>
      </div>

      <div className="flex gap-4">
        <button
          onClick={() => navigate('/ingest')}
          className="flex-1 flex items-center justify-center gap-2 bg-card hover:bg-muted border border-border rounded-lg py-4 transition-colors"
        >
          <Upload className="w-5 h-5" />
          <span>{t('action.upload')}</span>
        </button>
        <button
          onClick={() => navigate('/search')}
          className="flex-1 flex items-center justify-center gap-2 bg-card hover:bg-muted border border-border rounded-lg py-4 transition-colors"
        >
          <Search className="w-5 h-5" />
          <span>{t('action.search')}</span>
        </button>
        <button
          onClick={() => navigate('/graph')}
          className="flex-1 flex items-center justify-center gap-2 bg-card hover:bg-muted border border-border rounded-lg py-4 transition-colors"
        >
          <Network className="w-5 h-5" />
          <span>{t('action.graph')}</span>
        </button>
      </div>

      <CreateInstanceDialog open={createOpen} onOpenChange={setCreateOpen} onCreated={handleCreated} />

      <Dialog open={Boolean(editTarget)} onOpenChange={(open) => { if (!open) setEditTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.edit')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <label className="block text-sm font-medium mb-1">{t('createDialog.name')}</label>
              <Input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder={t('createDialog.namePlaceholder')}
              />
            </div>
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium">{t('createDialog.autoMap')}</label>
              <Switch checked={editAutoMap} onCheckedChange={setEditAutoMap} />
            </div>
            {editError && (
              <div className="rounded bg-destructive/10 p-2 text-sm text-destructive">{editError}</div>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditTarget(null)}>
              {t('manage.cancel')}
            </Button>
            <Button onClick={handleEdit} disabled={!editName.trim() || editing}>
              {editing && <Loader2 className="h-4 w-4 animate-spin" />}
              {editing ? t('manage.saving') : t('manage.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.deleteTitle')}</DialogTitle>
            <DialogDescription>
              {deleteTarget?.name ? `${t('manage.deleteDescription')} (${deleteTarget.name})` : t('manage.deleteDescription')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <label className="flex items-center justify-between gap-3 rounded-md border border-border p-3 text-sm">
              <span>{t('manage.deleteFiles')}</span>
              <Switch checked={deleteFiles} onCheckedChange={setDeleteFiles} />
            </label>
            {deleteError && (
              <div className="rounded bg-destructive/10 p-2 text-sm text-destructive">{deleteError}</div>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              {t('manage.cancel')}
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('manage.confirmDelete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
