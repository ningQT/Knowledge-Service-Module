import { useCallback, useEffect, useMemo, useState } from 'react'
import { BookMarked, Edit3, Loader2, Plus, Search, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '@/components/shared/EmptyState'
import { LoadingState } from '@/components/shared/LoadingState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { formatApiError } from '@/lib/i18nFormat'
import {
  createSearchLexicon,
  deleteSearchLexicon,
  listSearchLexicon,
  updateSearchLexicon,
} from '@/services/searchLexicon'
import { useInstanceStore } from '@/stores/useInstanceStore'
import type { SearchLexiconEntry, SearchLexiconRelationType } from '@/types/api'

const ALL = 'all'

interface FormState {
  relation_type: SearchLexiconRelationType
  canonical_term: string
  variant_terms: string
  enabled: boolean
  notes: string
}

const emptyForm: FormState = {
  relation_type: 'alias',
  canonical_term: '',
  variant_terms: '',
  enabled: true,
  notes: '',
}

function parseVariants(value: string) {
  return value
    .split(/[,\n，、]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function entryToForm(entry: SearchLexiconEntry): FormState {
  return {
    relation_type: entry.relation_type,
    canonical_term: entry.canonical_term,
    variant_terms: entry.variant_terms.join(', '),
    enabled: entry.enabled,
    notes: entry.notes || '',
  }
}

export default function SearchLexiconPage() {
  const { t } = useTranslation(['searchLexicon', 'common'])
  const { instanceId } = useInstanceStore()
  const [entries, setEntries] = useState<SearchLexiconEntry[]>([])
  const [filter, setFilter] = useState<string>(ALL)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<SearchLexiconEntry | null>(null)
  const [form, setForm] = useState<FormState>(emptyForm)
  const [deleteTarget, setDeleteTarget] = useState<SearchLexiconEntry | null>(null)
  const [pendingEntryId, setPendingEntryId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  const reload = useCallback(() => {
    if (!instanceId) return
    setLoading(true)
    setError(null)
    listSearchLexicon(instanceId)
      .then(setEntries)
      .catch((e) => setError(formatApiError(t, e)))
      .finally(() => setLoading(false))
  }, [instanceId, t])

  useEffect(() => {
    let cancelled = false
    if (!instanceId) {
      queueMicrotask(() => {
        if (!cancelled) setEntries([])
      })
      return () => { cancelled = true }
    }
    queueMicrotask(() => {
      if (!cancelled) reload()
    })
    return () => { cancelled = true }
  }, [instanceId, reload])

  const visibleEntries = useMemo(() => {
    const q = query.trim().toLowerCase()
    return entries.filter((entry) => {
      if (filter !== ALL && entry.relation_type !== filter) return false
      if (!q) return true
      return (
        entry.canonical_term.toLowerCase().includes(q) ||
        entry.variant_terms.some((item) => item.toLowerCase().includes(q)) ||
        entry.notes.toLowerCase().includes(q)
      )
    })
  }, [entries, filter, query])

  const openCreate = () => {
    setEditing(null)
    setForm(emptyForm)
    setDialogOpen(true)
    setError(null)
  }

  const openEdit = (entry: SearchLexiconEntry) => {
    setEditing(entry)
    setForm(entryToForm(entry))
    setDialogOpen(true)
    setError(null)
  }

  const saveEntry = async () => {
    if (!instanceId || saving) return
    setSaving(true)
    setError(null)
    const payload = {
      relation_type: form.relation_type,
      canonical_term: form.canonical_term,
      variant_terms: parseVariants(form.variant_terms),
      enabled: form.enabled,
      notes: form.notes,
    }
    try {
      const saved = editing
        ? await updateSearchLexicon(instanceId, editing.id, payload)
        : await createSearchLexicon(instanceId, payload)
      setEntries((current) => {
        const rest = current.filter((item) => item.id !== saved.id)
        return [...rest, saved].sort((a, b) => a.canonical_term.localeCompare(b.canonical_term))
      })
      setDialogOpen(false)
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setSaving(false)
    }
  }

  const toggleEntry = async (entry: SearchLexiconEntry) => {
    if (!instanceId || pendingEntryId) return
    setPendingEntryId(entry.id)
    setError(null)
    try {
      const saved = await updateSearchLexicon(instanceId, entry.id, { enabled: !entry.enabled })
      setEntries((current) => current.map((item) => (item.id === saved.id ? saved : item)))
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setPendingEntryId(null)
    }
  }

  const confirmDelete = async () => {
    if (!instanceId || !deleteTarget || deleting) return
    setDeleting(true)
    setError(null)
    try {
      await deleteSearchLexicon(instanceId, deleteTarget.id)
      setEntries((current) => current.filter((item) => item.id !== deleteTarget.id))
      setDeleteTarget(null)
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setDeleting(false)
    }
  }

  if (!instanceId) {
    return <EmptyState title={t('empty.noInstanceTitle')} description={t('empty.noInstanceDescription')} />
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <BookMarked className="h-5 w-5 text-primary" />
            {t('title')}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">{t('description')}</p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4" />
          {t('actions.create')}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-3">
        <div className="relative min-w-64 flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('searchPlaceholder')} className="pl-9" />
        </div>
        <Select value={filter} onValueChange={setFilter}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('filters.all')}</SelectItem>
            <SelectItem value="alias">{t('types.alias')}</SelectItem>
            <SelectItem value="synonym">{t('types.synonym')}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {error && <div className="rounded-md border border-error/30 bg-error/10 p-3 text-sm text-error">{error}</div>}

      <div className="overflow-hidden rounded-lg border border-border bg-card">
        {loading ? (
          <LoadingState />
        ) : visibleEntries.length === 0 ? (
          <EmptyState title={t('empty.default')} description={t('empty.description')} />
        ) : (
          <div className="divide-y divide-border">
            {visibleEntries.map((entry) => (
              <div key={entry.id} className="grid gap-3 px-4 py-3 md:grid-cols-[1fr_120px_96px_88px]">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium">{entry.canonical_term}</p>
                    <Badge variant={entry.relation_type === 'alias' ? 'default' : 'secondary'}>
                      {t(`types.${entry.relation_type}`)}
                    </Badge>
                    {!entry.enabled && <Badge variant="outline">{t('status.disabled')}</Badge>}
                  </div>
                  {entry.variant_terms.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {entry.variant_terms.map((term) => (
                        <span key={term} className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{term}</span>
                      ))}
                    </div>
                  )}
                  {entry.notes && <p className="mt-2 text-xs text-muted-foreground">{entry.notes}</p>}
                </div>
                <div className="flex items-center gap-2">
                  <Switch checked={entry.enabled} onCheckedChange={() => void toggleEntry(entry)} disabled={Boolean(pendingEntryId)} />
                  <span className="text-xs text-muted-foreground">{entry.enabled ? t('status.enabled') : t('status.disabled')}</span>
                </div>
                <Button variant="ghost" onClick={() => openEdit(entry)}>
                  <Edit3 className="h-4 w-4" />
                  {t('actions.edit')}
                </Button>
                <Button variant="ghost" onClick={() => setDeleteTarget(entry)}>
                  <Trash2 className="h-4 w-4" />
                  {t('actions.delete')}
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? t('dialog.editTitle') : t('dialog.createTitle')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Select value={form.relation_type} onValueChange={(value) => setForm({ ...form, relation_type: value as SearchLexiconRelationType })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="alias">{t('types.alias')}</SelectItem>
                <SelectItem value="synonym">{t('types.synonym')}</SelectItem>
              </SelectContent>
            </Select>
            <Input value={form.canonical_term} onChange={(e) => setForm({ ...form, canonical_term: e.target.value })} placeholder={t('form.canonical')} />
            <Input value={form.variant_terms} onChange={(e) => setForm({ ...form, variant_terms: e.target.value })} placeholder={t('form.variants')} />
            <Input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder={t('form.notes')} />
            <div className="flex items-center gap-2">
              <Switch checked={form.enabled} onCheckedChange={(checked) => setForm({ ...form, enabled: checked })} />
              <span className="text-sm text-muted-foreground">{form.enabled ? t('status.enabled') : t('status.disabled')}</span>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>{t('common:cancel')}</Button>
            <Button onClick={() => void saveEntry()} disabled={saving || !form.canonical_term.trim()}>
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('actions.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('delete.title')}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t('delete.description', { term: deleteTarget?.canonical_term })}</p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)} disabled={deleting}>{t('common:cancel')}</Button>
            <Button variant="destructive" onClick={() => void confirmDelete()} disabled={deleting}>
              {deleting && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('actions.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
