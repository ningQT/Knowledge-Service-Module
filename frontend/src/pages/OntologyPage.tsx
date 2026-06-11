import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle, Database, Edit3, Loader2, Plus, Search, Trash2, XCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '@/components/shared/EmptyState'
import { LoadingState } from '@/components/shared/LoadingState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatApiError } from '@/lib/i18nFormat'
import {
  batchUpdateEntityStatus,
  batchUpdateRelationStatus,
  batchUpdateTypeStatus,
  createOntologyAlias,
  createOntologyEntity,
  createOntologyRelation,
  createOntologyType,
  deleteOntologyAlias,
  deleteOntologyEntity,
  deleteOntologyRelation,
  deleteOntologyType,
  getOntologyStats,
  getOntologySwitchStatus,
  listOntologyAliases,
  listOntologyEntities,
  listOntologyRelations,
  listOntologyTypes,
  enableOntology,
  disableOntology,
  updateOntologyEntity,
  updateOntologyRelation,
  updateOntologyType,
} from '@/services/ontology'
import { useInstanceStore } from '@/stores/useInstanceStore'
import type {
  OntologyAlias,
  OntologyEntity,
  OntologyRelation,
  OntologyRelationType,
  OntologyStatsResponse,
  OntologySwitchStatusResponse,
  OntologyType,
} from '@/types/api'

// =============================================================================
// Types
// =============================================================================

interface TypeForm {
  name: string
  description: string
}

interface EntityForm {
  name: string
  description: string
  entity_type_id: string
}

interface RelationForm {
  source_entity_id: string
  target_entity_id: string
  relation_type: OntologyRelationType
  description: string
}

const emptyTypeForm: TypeForm = { name: '', description: '' }
const emptyEntityForm: EntityForm = { name: '', description: '', entity_type_id: '' }
const emptyRelationForm: RelationForm = { source_entity_id: '', target_entity_id: '', relation_type: 'related_to', description: '' }
const ENTITY_TYPE_NONE = '__none__'

const RELATION_TYPES: OntologyRelationType[] = ['is_a', 'has_role', 'part_of', 'related_to', 'caused_by', 'influenced_by']
const STATUS_OPTIONS = ['active', 'candidate', 'deprecated'] as const

// =============================================================================
// Types Tab
// =============================================================================

function TypesTab({ instanceId }: { instanceId: string }) {
  const { t } = useTranslation(['ontology', 'common'])
  const [types, setTypes] = useState<OntologyType[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<OntologyType | null>(null)
  const [form, setForm] = useState<TypeForm>(emptyTypeForm)
  const [deleteTarget, setDeleteTarget] = useState<OntologyType | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [pendingId, setPendingId] = useState<string | null>(null)

  const reload = useCallback(() => {
    setLoading(true)
    setError(null)
    listOntologyTypes(instanceId)
      .then(setTypes)
      .catch((e) => setError(formatApiError(t, e)))
      .finally(() => setLoading(false))
  }, [instanceId, t])

  useEffect(() => {
    queueMicrotask(reload)
  }, [reload])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return types
    return types.filter((item) => item.name.toLowerCase().includes(q) || item.description.toLowerCase().includes(q))
  }, [types, query])

  const openCreate = () => { setEditing(null); setForm(emptyTypeForm); setDialogOpen(true); setError(null) }
  const openEdit = (item: OntologyType) => { setEditing(item); setForm({ name: item.name, description: item.description }); setDialogOpen(true); setError(null) }

  const save = async () => {
    if (saving) return
    setSaving(true)
    setError(null)
    try {
      const saved = editing
        ? await updateOntologyType(instanceId, editing.id, { name: form.name, description: form.description })
        : await createOntologyType(instanceId, { name: form.name, description: form.description })
      setTypes((cur) => {
        const rest = cur.filter((item) => item.id !== saved.id)
        return [...rest, saved].sort((a, b) => a.name.localeCompare(b.name))
      })
      setDialogOpen(false)
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setSaving(false)
    }
  }

  const toggleSearchable = async (item: OntologyType) => {
    if (pendingId) return
    setPendingId(item.id)
    setError(null)
    try {
      const saved = await updateOntologyType(instanceId, item.id, { searchable: !item.searchable })
      setTypes((cur) => cur.map((i) => (i.id === saved.id ? saved : i)))
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setPendingId(null)
    }
  }

  const toggleStatus = async (item: OntologyType, status: string) => {
    if (pendingId) return
    setPendingId(item.id)
    setError(null)
    try {
      const saved = await updateOntologyType(instanceId, item.id, { status })
      setTypes((cur) => cur.map((i) => (i.id === saved.id ? saved : i)))
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setPendingId(null)
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return
    setDeleting(true)
    setError(null)
    try {
      await deleteOntologyType(instanceId, deleteTarget.id)
      setTypes((cur) => cur.filter((i) => i.id !== deleteTarget.id))
      setDeleteTarget(null)
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-48 flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('form.searchPlaceholder')} className="pl-9" />
        </div>
        <Button onClick={openCreate}><Plus className="h-4 w-4" />{t('actions.create')}</Button>
      </div>

      {error && <div className="rounded-md border border-error/30 bg-error/10 p-3 text-sm text-error">{error}</div>}

      <div className="overflow-hidden rounded-lg border border-border bg-card">
        {loading ? (
          <LoadingState />
        ) : visible.length === 0 ? (
          <EmptyState title={t('empty.default')} description={t('empty.description')} />
        ) : (
          <div className="divide-y divide-border">
            {visible.map((item) => (
              <div key={item.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium">{item.name}</p>
                    <Badge variant={item.status === 'active' ? 'default' : item.status === 'candidate' ? 'secondary' : 'outline'}>
                      {t(`status.${item.status}`)}
                    </Badge>
                  </div>
                  {item.description && <p className="mt-1 text-xs text-muted-foreground">{item.description}</p>}
                </div>
                <div className="flex items-center gap-2">
                  <Switch checked={item.searchable} onCheckedChange={() => void toggleSearchable(item)} disabled={Boolean(pendingId)} />
                  <span className="text-xs text-muted-foreground">{item.searchable ? t('searchable.on') : t('searchable.off')}</span>
                </div>
                <Select value={item.status} onValueChange={(v) => void toggleStatus(item, v)} disabled={Boolean(pendingId)}>
                  <SelectTrigger className="w-24"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {STATUS_OPTIONS.map((s) => <SelectItem key={s} value={s}>{t(`status.${s}`)}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Button variant="ghost" size="sm" onClick={() => openEdit(item)}><Edit3 className="h-4 w-4" /></Button>
                <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(item)}><Trash2 className="h-4 w-4" /></Button>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editing ? t('dialog.editType') : t('dialog.createType')}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder={t('form.name')} />
            <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder={t('form.description')} />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>{t('common:cancel')}</Button>
            <Button onClick={() => void save()} disabled={saving || !form.name.trim()}>
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}{t('actions.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t('delete.title')}</DialogTitle></DialogHeader>
          <p className="text-sm text-muted-foreground">{t('delete.description', { name: deleteTarget?.name })}</p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)} disabled={deleting}>{t('common:cancel')}</Button>
            <Button variant="destructive" onClick={() => void confirmDelete()} disabled={deleting}>
              {deleting && <Loader2 className="h-4 w-4 animate-spin" />}{t('actions.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// =============================================================================
// Entities Tab
// =============================================================================

function EntitiesTab({ instanceId }: { instanceId: string }) {
  const { t } = useTranslation(['ontology', 'common'])
  const [entities, setEntities] = useState<OntologyEntity[]>([])
  const [types, setTypes] = useState<OntologyType[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [filterType, setFilterType] = useState<string>('all')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<OntologyEntity | null>(null)
  const [form, setForm] = useState<EntityForm>(emptyEntityForm)
  const [deleteTarget, setDeleteTarget] = useState<OntologyEntity | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [aliases, setAliases] = useState<OntologyAlias[]>([])
  const [aliasText, setAliasText] = useState('')
  const [aliasSaving, setAliasSaving] = useState(false)

  const reload = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([listOntologyEntities(instanceId), listOntologyTypes(instanceId)])
      .then(([ents, typs]) => { setEntities(ents); setTypes(typs) })
      .catch((e) => setError(formatApiError(t, e)))
      .finally(() => setLoading(false))
  }, [instanceId, t])

  useEffect(() => {
    queueMicrotask(reload)
  }, [reload])

  const typeName = useCallback((typeId: string | null) => {
    if (!typeId) return ''
    return types.find((tp) => tp.id === typeId)?.name || typeId
  }, [types])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return entities.filter((item) => {
      if (filterType !== 'all' && item.entity_type_id !== filterType) return false
      if (!q) return true
      return item.name.toLowerCase().includes(q) || item.description.toLowerCase().includes(q)
    })
  }, [entities, filterType, query])

  const openCreate = () => { setEditing(null); setForm(emptyEntityForm); setDialogOpen(true); setError(null) }
  const openEdit = (item: OntologyEntity) => {
    setEditing(item)
    setForm({ name: item.name, description: item.description, entity_type_id: item.entity_type_id || '' })
    setDialogOpen(true)
    setError(null)
  }

  const save = async () => {
    if (saving) return
    setSaving(true)
    setError(null)
    try {
      const saved = editing
        ? await updateOntologyEntity(instanceId, editing.id, {
            name: form.name,
            description: form.description,
            entity_type_id: form.entity_type_id || null,
          })
        : await createOntologyEntity(instanceId, {
            name: form.name,
            description: form.description,
            ...(form.entity_type_id ? { entity_type_id: form.entity_type_id } : {}),
          })
      setEntities((cur) => {
        const rest = cur.filter((item) => item.id !== saved.id)
        return [...rest, saved].sort((a, b) => a.name.localeCompare(b.name))
      })
      setDialogOpen(false)
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setSaving(false)
    }
  }

  const toggleSearchable = async (item: OntologyEntity) => {
    if (pendingId) return
    setPendingId(item.id)
    setError(null)
    try {
      const saved = await updateOntologyEntity(instanceId, item.id, { searchable: !item.searchable })
      setEntities((cur) => cur.map((i) => (i.id === saved.id ? saved : i)))
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setPendingId(null)
    }
  }

  const toggleStatus = async (item: OntologyEntity, status: string) => {
    if (pendingId) return
    setPendingId(item.id)
    setError(null)
    try {
      const saved = await updateOntologyEntity(instanceId, item.id, { status })
      setEntities((cur) => cur.map((i) => (i.id === saved.id ? saved : i)))
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setPendingId(null)
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return
    setDeleting(true)
    setError(null)
    try {
      await deleteOntologyEntity(instanceId, deleteTarget.id)
      setEntities((cur) => cur.filter((i) => i.id !== deleteTarget.id))
      setDeleteTarget(null)
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setDeleting(false)
    }
  }

  const toggleExpand = async (entityId: string) => {
    if (expandedId === entityId) {
      setExpandedId(null)
      setAliases([])
      return
    }
    setExpandedId(entityId)
    try {
      const als = await listOntologyAliases(instanceId, entityId)
      setAliases(als)
    } catch {
      setAliases([])
    }
  }

  const addAlias = async (entityId: string) => {
    if (!aliasText.trim() || aliasSaving) return
    setAliasSaving(true)
    try {
      const created = await createOntologyAlias(instanceId, entityId, { alias_text: aliasText.trim() })
      setAliases((cur) => [...cur, created])
      setAliasText('')
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setAliasSaving(false)
    }
  }

  const removeAlias = async (entityId: string, aliasId: string) => {
    try {
      await deleteOntologyAlias(instanceId, entityId, aliasId)
      setAliases((cur) => cur.filter((a) => a.id !== aliasId))
    } catch (e) {
      setError(formatApiError(t, e))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-48 flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('form.searchPlaceholder')} className="pl-9" />
        </div>
        <Select value={filterType} onValueChange={setFilterType}>
          <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('form.entityType')}</SelectItem>
            {types.map((tp) => <SelectItem key={tp.id} value={tp.id}>{tp.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Button onClick={openCreate}><Plus className="h-4 w-4" />{t('actions.create')}</Button>
      </div>

      {error && <div className="rounded-md border border-error/30 bg-error/10 p-3 text-sm text-error">{error}</div>}

      <div className="overflow-hidden rounded-lg border border-border bg-card">
        {loading ? (
          <LoadingState />
        ) : visible.length === 0 ? (
          <EmptyState title={t('empty.default')} description={t('empty.description')} />
        ) : (
          <div className="divide-y divide-border">
            {visible.map((item) => (
              <div key={item.id}>
                <div className="flex items-center gap-3 px-4 py-3">
                  <button className="min-w-0 flex-1 text-left" onClick={() => void toggleExpand(item.id)}>
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium">{item.name}</p>
                      {item.entity_type_id && <Badge variant="secondary">{typeName(item.entity_type_id)}</Badge>}
                      <Badge variant={item.status === 'active' ? 'default' : item.status === 'candidate' ? 'secondary' : 'outline'}>
                        {t(`status.${item.status}`)}
                      </Badge>
                    </div>
                    {item.description && <p className="mt-1 text-xs text-muted-foreground">{item.description}</p>}
                  </button>
                  <div className="flex items-center gap-2">
                    <Switch checked={item.searchable} onCheckedChange={() => void toggleSearchable(item)} disabled={Boolean(pendingId)} />
                    <span className="text-xs text-muted-foreground">{item.searchable ? t('searchable.on') : t('searchable.off')}</span>
                  </div>
                  <Select value={item.status} onValueChange={(v) => void toggleStatus(item, v)} disabled={Boolean(pendingId)}>
                    <SelectTrigger className="w-24"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {STATUS_OPTIONS.map((s) => <SelectItem key={s} value={s}>{t(`status.${s}`)}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Button variant="ghost" size="sm" onClick={() => openEdit(item)}><Edit3 className="h-4 w-4" /></Button>
                  <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(item)}><Trash2 className="h-4 w-4" /></Button>
                </div>
                {expandedId === item.id && (
                  <div className="border-t border-border bg-muted/30 px-4 py-3 space-y-2">
                    <p className="text-xs font-medium text-muted-foreground">{t('actions.addAlias')}</p>
                    <div className="flex gap-2">
                      <Input value={aliasText} onChange={(e) => setAliasText(e.target.value)} placeholder={t('form.aliasText')} className="h-8 text-sm" />
                      <Button size="sm" onClick={() => void addAlias(item.id)} disabled={aliasSaving || !aliasText.trim()}>
                        {aliasSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                      </Button>
                    </div>
                    {aliases.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {aliases.map((a) => (
                          <span key={a.id} className="inline-flex items-center gap-1 rounded bg-background px-2 py-0.5 text-xs border border-border">
                            {a.alias_text}
                            <button className="text-muted-foreground hover:text-error" onClick={() => void removeAlias(item.id, a.id)}>&times;</button>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editing ? t('dialog.editEntity') : t('dialog.createEntity')}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder={t('form.name')} />
            <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder={t('form.description')} />
            <Select
              value={form.entity_type_id}
              onValueChange={(v) => setForm({ ...form, entity_type_id: v === ENTITY_TYPE_NONE ? '' : v })}
            >
              <SelectTrigger><SelectValue placeholder={t('form.entityType')} /></SelectTrigger>
              <SelectContent>
                <SelectItem value={ENTITY_TYPE_NONE}>{t('form.entityTypeUnset')}</SelectItem>
                {types.map((tp) => <SelectItem key={tp.id} value={tp.id}>{tp.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>{t('common:cancel')}</Button>
            <Button onClick={() => void save()} disabled={saving || !form.name.trim()}>
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}{t('actions.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t('delete.title')}</DialogTitle></DialogHeader>
          <p className="text-sm text-muted-foreground">{t('delete.description', { name: deleteTarget?.name })}</p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)} disabled={deleting}>{t('common:cancel')}</Button>
            <Button variant="destructive" onClick={() => void confirmDelete()} disabled={deleting}>
              {deleting && <Loader2 className="h-4 w-4 animate-spin" />}{t('actions.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// =============================================================================
// Relations Tab
// =============================================================================

function RelationsTab({ instanceId }: { instanceId: string }) {
  const { t } = useTranslation(['ontology', 'common'])
  const [relations, setRelations] = useState<OntologyRelation[]>([])
  const [entities, setEntities] = useState<OntologyEntity[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<OntologyRelation | null>(null)
  const [form, setForm] = useState<RelationForm>(emptyRelationForm)
  const [deleteTarget, setDeleteTarget] = useState<OntologyRelation | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [pendingId, setPendingId] = useState<string | null>(null)

  const reload = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([listOntologyRelations(instanceId), listOntologyEntities(instanceId)])
      .then(([rels, ents]) => { setRelations(rels); setEntities(ents) })
      .catch((e) => setError(formatApiError(t, e)))
      .finally(() => setLoading(false))
  }, [instanceId, t])

  useEffect(() => {
    queueMicrotask(reload)
  }, [reload])

  const entityName = useCallback((entityId: string) => {
    return entities.find((e) => e.id === entityId)?.name || entityId
  }, [entities])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return relations
    return relations.filter((item) => {
      const src = entityName(item.source_entity_id).toLowerCase()
      const tgt = entityName(item.target_entity_id).toLowerCase()
      return src.includes(q) || tgt.includes(q) || item.description.toLowerCase().includes(q)
    })
  }, [relations, query, entityName])

  const openCreate = () => { setEditing(null); setForm(emptyRelationForm); setDialogOpen(true); setError(null) }
  const openEdit = (item: OntologyRelation) => {
    setEditing(item)
    setForm({ source_entity_id: item.source_entity_id, target_entity_id: item.target_entity_id, relation_type: item.relation_type as OntologyRelationType, description: item.description })
    setDialogOpen(true)
    setError(null)
  }

  const save = async () => {
    if (saving) return
    setSaving(true)
    setError(null)
    try {
      const saved = editing
        ? await updateOntologyRelation(instanceId, editing.id, { description: form.description })
        : await createOntologyRelation(instanceId, form)
      setRelations((cur) => {
        const rest = cur.filter((item) => item.id !== saved.id)
        return [saved, ...rest]
      })
      setDialogOpen(false)
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setSaving(false)
    }
  }

  const toggleSearchable = async (item: OntologyRelation) => {
    if (pendingId) return
    setPendingId(item.id)
    setError(null)
    try {
      const saved = await updateOntologyRelation(instanceId, item.id, { searchable: !item.searchable })
      setRelations((cur) => cur.map((i) => (i.id === saved.id ? saved : i)))
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setPendingId(null)
    }
  }

  const toggleStatus = async (item: OntologyRelation, status: string) => {
    if (pendingId) return
    setPendingId(item.id)
    setError(null)
    try {
      const saved = await updateOntologyRelation(instanceId, item.id, { status })
      setRelations((cur) => cur.map((i) => (i.id === saved.id ? saved : i)))
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setPendingId(null)
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return
    setDeleting(true)
    setError(null)
    try {
      await deleteOntologyRelation(instanceId, deleteTarget.id)
      setRelations((cur) => cur.filter((i) => i.id !== deleteTarget.id))
      setDeleteTarget(null)
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-48 flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('form.searchPlaceholder')} className="pl-9" />
        </div>
        <Button onClick={openCreate}><Plus className="h-4 w-4" />{t('actions.create')}</Button>
      </div>

      {error && <div className="rounded-md border border-error/30 bg-error/10 p-3 text-sm text-error">{error}</div>}

      <div className="overflow-hidden rounded-lg border border-border bg-card">
        {loading ? (
          <LoadingState />
        ) : visible.length === 0 ? (
          <EmptyState title={t('empty.default')} description={t('empty.description')} />
        ) : (
          <div className="divide-y divide-border">
            {visible.map((item) => (
              <div key={item.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium">{entityName(item.source_entity_id)}</p>
                    <Badge variant="secondary">{t(`relationTypes.${item.relation_type}`)}</Badge>
                    <p className="font-medium">{entityName(item.target_entity_id)}</p>
                    <Badge variant={item.status === 'active' ? 'default' : item.status === 'candidate' ? 'secondary' : 'outline'}>
                      {t(`status.${item.status}`)}
                    </Badge>
                  </div>
                  {item.description && <p className="mt-1 text-xs text-muted-foreground">{item.description}</p>}
                </div>
                <div className="flex items-center gap-2">
                  <Switch checked={item.searchable} onCheckedChange={() => void toggleSearchable(item)} disabled={Boolean(pendingId)} />
                  <span className="text-xs text-muted-foreground">{item.searchable ? t('searchable.on') : t('searchable.off')}</span>
                </div>
                <Select value={item.status} onValueChange={(v) => void toggleStatus(item, v)} disabled={Boolean(pendingId)}>
                  <SelectTrigger className="w-24"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {STATUS_OPTIONS.map((s) => <SelectItem key={s} value={s}>{t(`status.${s}`)}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Button variant="ghost" size="sm" onClick={() => openEdit(item)}><Edit3 className="h-4 w-4" /></Button>
                <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(item)}><Trash2 className="h-4 w-4" /></Button>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editing ? t('dialog.editRelation') : t('dialog.createRelation')}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            {!editing && (
              <>
                <Select value={form.source_entity_id} onValueChange={(v) => setForm({ ...form, source_entity_id: v })}>
                  <SelectTrigger><SelectValue placeholder={t('form.sourceEntity')} /></SelectTrigger>
                  <SelectContent>
                    {entities.map((e) => <SelectItem key={e.id} value={e.id}>{e.name}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Select value={form.relation_type} onValueChange={(v) => setForm({ ...form, relation_type: v as OntologyRelationType })}>
                  <SelectTrigger><SelectValue placeholder={t('form.relationType')} /></SelectTrigger>
                  <SelectContent>
                    {RELATION_TYPES.map((rt) => <SelectItem key={rt} value={rt}>{t(`relationTypes.${rt}`)}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Select value={form.target_entity_id} onValueChange={(v) => setForm({ ...form, target_entity_id: v })}>
                  <SelectTrigger><SelectValue placeholder={t('form.targetEntity')} /></SelectTrigger>
                  <SelectContent>
                    {entities.map((e) => <SelectItem key={e.id} value={e.id}>{e.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </>
            )}
            <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder={t('form.description')} />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>{t('common:cancel')}</Button>
            <Button onClick={() => void save()} disabled={saving || (!editing && (!form.source_entity_id || !form.target_entity_id))}>
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}{t('actions.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t('delete.title')}</DialogTitle></DialogHeader>
          <p className="text-sm text-muted-foreground">{t('delete.description', { name: deleteTarget ? `${entityName(deleteTarget.source_entity_id)} → ${entityName(deleteTarget.target_entity_id)}` : '' })}</p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)} disabled={deleting}>{t('common:cancel')}</Button>
            <Button variant="destructive" onClick={() => void confirmDelete()} disabled={deleting}>
              {deleting && <Loader2 className="h-4 w-4 animate-spin" />}{t('actions.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// =============================================================================
// Stats Panel
// =============================================================================

function StatsPanel({ instanceId }: { instanceId: string }) {
  const { t } = useTranslation(['ontology', 'common'])
  const [stats, setStats] = useState<OntologyStatsResponse | null>(null)
  const [switchStatus, setSwitchStatus] = useState<OntologySwitchStatusResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [switchSaving, setSwitchSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.allSettled([
      getOntologyStats(instanceId),
      getOntologySwitchStatus(instanceId),
    ])
      .then(([statsResult, switchResult]) => {
        if (statsResult.status === 'fulfilled') {
          setStats(statsResult.value)
        }
        if (switchResult.status === 'fulfilled') {
          setSwitchStatus(switchResult.value)
        }
        const errors: string[] = []
        if (statsResult.status === 'rejected') {
          errors.push(formatApiError(t, statsResult.reason))
        }
        if (switchResult.status === 'rejected') {
          errors.push(formatApiError(t, switchResult.reason))
        }
        setError(errors.length > 0 ? errors.join(' / ') : null)
      })
      .finally(() => setLoading(false))
  }, [instanceId, t])

  useEffect(() => {
    queueMicrotask(reload)
  }, [reload])

  const toggleInstanceSwitch = async (enabled: boolean) => {
    if (!switchStatus || !switchStatus.global_enabled || switchSaving) return
    setSwitchSaving(true)
    setError(null)
    try {
      if (enabled) {
        await enableOntology(instanceId)
      } else {
        await disableOntology(instanceId)
      }
      reload()
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setSwitchSaving(false)
    }
  }

  if (loading && !stats && !switchStatus) return <LoadingState />
  if (!stats && !switchStatus) {
    return error ? <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</div> : null
  }

  const cacheInfo = switchStatus?.cache ?? stats?.cache
  const totalEntities = stats
    ? stats.entities.active + stats.entities.candidate + stats.entities.deprecated
    : 0

  return (
    <section className="rounded-lg border border-border bg-card p-3">
      {error && <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}

      {(switchStatus || cacheInfo || stats) && (
        <div className="flex flex-wrap items-start justify-between gap-3">
          {switchStatus && (
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">{t('switch.globalEnabled')}</span>
                <Badge variant={switchStatus.global_enabled ? 'default' : 'secondary'}>
                  {switchStatus.global_enabled ? t('switch.enabled') : t('switch.disabled')}
                </Badge>
                <span className="text-xs text-muted-foreground">{t('switch.instanceEnabled')}</span>
                <Badge variant={switchStatus.instance_enabled ? 'default' : 'secondary'}>
                  {switchStatus.instance_enabled ? t('switch.enabled') : t('switch.disabled')}
                </Badge>
                {cacheInfo && (
                  <>
                    <span className="text-xs text-muted-foreground">{t('stats.cacheStatus')}</span>
                    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                      <span className={`h-2 w-2 rounded-full ${cacheInfo.cached ? 'bg-green-500' : 'bg-red-400'}`} />
                      <span className="font-medium text-foreground">
                        {cacheInfo.cached ? t('stats.cached') : t('stats.notCached')}
                      </span>
                    </span>
                  </>
                )}
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <span className="text-xs text-muted-foreground">
                  {switchStatus.global_enabled ? t('switch.enable') : t('switch.disabled')}
                </span>
                <Switch
                  checked={switchStatus.instance_enabled}
                  onCheckedChange={(checked) => void toggleInstanceSwitch(checked)}
                  disabled={!switchStatus.global_enabled || switchSaving}
                />
              </div>
            </div>
          )}

          {stats && (
            <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
              <span>{t('tabs.entities')} {stats.entities.active} / {stats.entities.candidate}</span>
              <span>{t('tabs.types')} {stats.types.active} / {stats.types.candidate}</span>
              <span>{t('tabs.relations')} {stats.relations.active} / {stats.relations.candidate}</span>
              {cacheInfo?.built_at && (
                <span>{new Date(cacheInfo.built_at).toLocaleString()}</span>
              )}
            </div>
          )}
        </div>
      )}

      {stats && (
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-lg border p-3">
            <div className="text-xs text-muted-foreground">{t('tabs.entities')}</div>
            <div className="mt-1 text-lg font-semibold">{totalEntities}</div>
            <div className="text-xs text-muted-foreground">
              {stats.entities.active} {t('stats.activeCount')} / {stats.entities.candidate} {t('stats.candidateCount')}
            </div>
          </div>
          <div className="rounded-lg border p-3">
            <div className="text-xs text-muted-foreground">{t('tabs.types')}</div>
            <div className="mt-1 text-lg font-semibold">{stats.types.active + stats.types.candidate + stats.types.deprecated}</div>
            <div className="text-xs text-muted-foreground">
              {stats.types.active} {t('stats.activeCount')} / {stats.types.candidate} {t('stats.candidateCount')}
            </div>
          </div>
          <div className="rounded-lg border p-3">
            <div className="text-xs text-muted-foreground">{t('tabs.relations')}</div>
            <div className="mt-1 text-lg font-semibold">{stats.relations.active + stats.relations.candidate + stats.relations.deprecated}</div>
            <div className="text-xs text-muted-foreground">
              {stats.relations.active} {t('stats.activeCount')} / {stats.relations.candidate} {t('stats.candidateCount')}
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

// =============================================================================
// Review Tab
// =============================================================================

interface ReviewItem {
  id: string
  name: string
  kind: 'entity' | 'relation' | 'type'
  source: string
  status: string
  confidence: number
  description: string
}

function ReviewTab({ instanceId }: { instanceId: string }) {
  const { t } = useTranslation(['ontology', 'common'])
  const [items, setItems] = useState<ReviewItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [filterSource, setFilterSource] = useState<string>('all')
  const [filterStatus, setFilterStatus] = useState<string>('candidate')
  const [processing, setProcessing] = useState(false)

  const reload = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      listOntologyEntities(instanceId, undefined),
      listOntologyRelations(instanceId),
      listOntologyTypes(instanceId),
    ])
      .then(([entities, relations, types]) => {
        // Build entity name lookup for relation display
        const entityMap = new Map(entities.map((e) => [e.id, e.name]))
        const entityName = (id: string) => entityMap.get(id) || id

        const reviewItems: ReviewItem[] = [
          ...entities.map((e) => ({
            id: e.id,
            name: e.name,
            kind: 'entity' as const,
            source: e.source,
            status: e.status,
            confidence: e.confidence,
            description: e.description,
          })),
          ...relations.map((r) => ({
            id: r.id,
            name: `${entityName(r.source_entity_id)} → ${entityName(r.target_entity_id)}`,
            kind: 'relation' as const,
            source: r.source,
            status: r.status,
            confidence: r.confidence,
            description: r.description,
          })),
          ...types.map((tp) => ({
            id: tp.id,
            name: tp.name,
            kind: 'type' as const,
            source: tp.source,
            status: tp.status,
            confidence: tp.confidence,
            description: tp.description,
          })),
        ]
        setItems(reviewItems)
      })
      .catch((e) => setError(formatApiError(t, e)))
      .finally(() => setLoading(false))
  }, [instanceId, t])

  useEffect(() => {
    queueMicrotask(reload)
  }, [reload])

  const filtered = useMemo(() => {
    return items.filter((item) => {
      if (filterStatus !== 'all' && item.status !== filterStatus) return false
      if (filterSource !== 'all' && item.source !== filterSource) return false
      return true
    })
  }, [items, filterStatus, filterSource])

  const allSelected = filtered.length > 0 && filtered.every((item) => selected.has(item.id))

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelected(new Set())
    } else {
      setSelected(new Set(filtered.map((item) => item.id)))
    }
  }

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const doBatch = async (status: string) => {
    if (selected.size === 0 || processing) return
    setProcessing(true)
    setError(null)
    try {
      const ids = Array.from(selected)
      const entityIds = ids.filter((id) => items.find((i) => i.id === id)?.kind === 'entity')
      const relationIds = ids.filter((id) => items.find((i) => i.id === id)?.kind === 'relation')
      const typeIds = ids.filter((id) => items.find((i) => i.id === id)?.kind === 'type')

      if (entityIds.length > 0) await batchUpdateEntityStatus(instanceId, { ids: entityIds, status })
      if (relationIds.length > 0) await batchUpdateRelationStatus(instanceId, { ids: relationIds, status })
      if (typeIds.length > 0) await batchUpdateTypeStatus(instanceId, { ids: typeIds, status })

      setSelected(new Set())
      reload()
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setProcessing(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Select value={filterStatus} onValueChange={setFilterStatus}>
          <SelectTrigger className="w-36"><SelectValue placeholder={t('review.filterStatus')} /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('review.filterStatus')}</SelectItem>
            <SelectItem value="candidate">{t('status.candidate')}</SelectItem>
            <SelectItem value="active">{t('status.active')}</SelectItem>
            <SelectItem value="deprecated">{t('status.deprecated')}</SelectItem>
          </SelectContent>
        </Select>
        <Select value={filterSource} onValueChange={setFilterSource}>
          <SelectTrigger className="w-36"><SelectValue placeholder={t('review.filterSource')} /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('review.filterSource')}</SelectItem>
            <SelectItem value="auto">{t('review.sourceAuto')}</SelectItem>
            <SelectItem value="manual">{t('review.sourceManual')}</SelectItem>
          </SelectContent>
        </Select>
        {selected.size > 0 && (
          <>
            <span className="text-sm text-muted-foreground">{t('review.selected', { count: selected.size })}</span>
            <Button size="sm" onClick={() => doBatch('active')} disabled={processing}>
              <CheckCircle className="h-4 w-4 mr-1" />{t('review.batchApprove')}
            </Button>
            <Button size="sm" variant="destructive" onClick={() => doBatch('deprecated')} disabled={processing}>
              <XCircle className="h-4 w-4 mr-1" />{t('review.batchReject')}
            </Button>
          </>
        )}
      </div>

      {error && <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}

      {loading ? (
        <LoadingState />
      ) : filtered.length === 0 ? (
        <EmptyState title={t('review.noPending')} description="" />
      ) : (
        <div className="rounded-md border">
          <div className="flex items-center gap-3 border-b px-4 py-2 text-sm font-medium">
            <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} />
            <span className="w-16">{t('form.entityType')}</span>
            <span className="flex-1">{t('form.name')}</span>
            <span className="w-20">{t('review.filterSource')}</span>
            <span className="w-20">{t('review.filterStatus')}</span>
          </div>
          {filtered.map((item) => (
            <div key={item.id} className="flex items-center gap-3 border-b px-4 py-2 last:border-b-0">
              <input
                type="checkbox"
                checked={selected.has(item.id)}
                onChange={() => toggleSelect(item.id)}
              />
              <span className="w-16">
                <Badge variant="outline">
                  {item.kind === 'entity'
                    ? t('tabs.entities')
                    : item.kind === 'type'
                      ? t('tabs.types')
                      : t('tabs.relations')}
                </Badge>
              </span>
              <span className="flex-1 text-sm">{item.name}</span>
              <span className="w-20">
                <Badge variant={item.source === 'auto' ? 'secondary' : 'default'}>
                  {item.source === 'auto' ? t('review.sourceAuto') : t('review.sourceManual')}
                </Badge>
              </span>
              <span className="w-20">
                <Badge variant={item.status === 'active' ? 'default' : item.status === 'candidate' ? 'secondary' : 'destructive'}>
                  {t(`status.${item.status}`)}
                </Badge>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// =============================================================================
// Main Page
// =============================================================================

export default function OntologyPage() {
  const { t } = useTranslation(['ontology', 'common'])
  const { instanceId } = useInstanceStore()

  if (!instanceId) {
    return <EmptyState title={t('empty.noInstanceTitle')} description={t('empty.noInstanceDescription')} />
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <Database className="h-5 w-5 text-primary" />
          {t('title')}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">{t('description')}</p>
      </div>

      <StatsPanel instanceId={instanceId} />

      <Tabs defaultValue="entities">
        <TabsList>
          <TabsTrigger value="entities">{t('tabs.entities')}</TabsTrigger>
          <TabsTrigger value="types">{t('tabs.types')}</TabsTrigger>
          <TabsTrigger value="relations">{t('tabs.relations')}</TabsTrigger>
          <TabsTrigger value="review">{t('tabs.review')}</TabsTrigger>
        </TabsList>
        <TabsContent value="entities">
          <EntitiesTab instanceId={instanceId} />
        </TabsContent>
        <TabsContent value="types">
          <TypesTab instanceId={instanceId} />
        </TabsContent>
        <TabsContent value="relations">
          <RelationsTab instanceId={instanceId} />
        </TabsContent>
        <TabsContent value="review">
          <ReviewTab instanceId={instanceId} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
