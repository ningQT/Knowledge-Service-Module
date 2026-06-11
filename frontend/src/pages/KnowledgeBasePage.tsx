import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { AlertTriangle, ArrowDownAZ, BookOpen, CheckCircle2, FileText, Filter, Loader2, Plus, Search, Trash2, X } from 'lucide-react'
import { useInstanceStore } from '@/stores/useInstanceStore'
import { deleteNote, listNoteFacets, listNotes, type ListNotesFilters, type NoteListItem } from '@/services/notes'
import { getInstanceDiagnostics, listInstances } from '@/services/instances'
import type { Instance, InstanceDiagnostics } from '@/types/api'
import { LoadingState } from '@/components/shared/LoadingState'
import { EmptyState } from '@/components/shared/EmptyState'
import { CreateInstanceDialog } from '@/components/shared/CreateInstanceDialog'
import { VerificationBadge } from '@/components/shared/VerificationBadge'
import { LayerBadge } from '@/components/shared/LayerBadge'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatApiError, formatDomain, formatKind, formatNoteType, formatVerification } from '@/lib/i18nFormat'
import { useTranslation } from 'react-i18next'

const ALL = 'all'
const NOTE_TYPES = ['source', 'card', 'map']
const VERIFICATIONS = ['verified', 'unverified', 'draft', 'truncated']
type SortKey = 'title' | 'type' | 'layer' | 'verification' | 'indexed'

function valueOrAll(value: string | null) {
  return value && value.trim() ? value : ALL
}

function queryValue(value: string) {
  return value === ALL ? '' : value
}

function getSortValue(note: NoteListItem, sort: SortKey) {
  if (sort === 'type') return note.type || ''
  if (sort === 'layer') return String(note.graph_layer || 0)
  if (sort === 'verification') return note.verification || ''
  if (sort === 'indexed') return note.indexed_at || ''
  return note.title || ''
}

function sortNotes(notes: NoteListItem[], sort: SortKey) {
  return [...notes].sort((a, b) => {
    const left = getSortValue(a, sort)
    const right = getSortValue(b, sort)
    if (sort === 'indexed') return right.localeCompare(left) || a.title.localeCompare(b.title)
    return left.localeCompare(right) || a.title.localeCompare(b.title)
  })
}

function useKnowledgeFilters() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = {
    domain: valueOrAll(searchParams.get('domain')),
    graphLayer: valueOrAll(searchParams.get('layer')),
    kind: valueOrAll(searchParams.get('kind')),
    query: searchParams.get('q') || '',
    sort: (searchParams.get('sort') as SortKey) || 'title',
    type: valueOrAll(searchParams.get('type')),
    verification: valueOrAll(searchParams.get('verification')),
  }

  const updateFilter = useCallback(
    (key: string, value: string) => {
      const next = new URLSearchParams(searchParams)
      if (!value || value === ALL) next.delete(key)
      else next.set(key, value)
      setSearchParams(next)
    },
    [searchParams, setSearchParams]
  )

  const clearFilters = useCallback(() => setSearchParams(new URLSearchParams()), [setSearchParams])

  return { clearFilters, filters, searchParams, updateFilter }
}

function KnowledgeFilters({
  domains,
  kinds,
  filters,
  onClear,
  onFilterChange,
}: {
  domains: string[]
  kinds: string[]
  filters: ReturnType<typeof useKnowledgeFilters>['filters']
  onClear: () => void
  onFilterChange: (key: string, value: string) => void
}) {
  const { t } = useTranslation(['knowledgeBase', 'common'])

  return (
    <aside className="w-full shrink-0 space-y-4 rounded-lg border border-border bg-card p-4 lg:w-64">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Filter className="h-4 w-4" />
          {t('filters.title')}
        </h2>
        <Button variant="ghost" size="xs" onClick={onClear}>
          <X className="h-3 w-3" />
          {t('filters.clear')}
        </Button>
      </div>

      <div className="space-y-2">
        <label className="text-xs font-medium text-muted-foreground">{t('filters.type')}</label>
        <Select value={filters.type} onValueChange={(value) => onFilterChange('type', value)}>
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('filters.all')}</SelectItem>
            {NOTE_TYPES.map((type) => (
              <SelectItem key={type} value={type}>{formatNoteType(t, type)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <label className="text-xs font-medium text-muted-foreground">{t('filters.layer')}</label>
        <Select value={filters.graphLayer} onValueChange={(value) => onFilterChange('layer', value)}>
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('filters.all')}</SelectItem>
            {[1, 2, 3].map((layer) => (
              <SelectItem key={layer} value={String(layer)}>{t(`common:enums.graphLayer.${layer}`)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <label className="text-xs font-medium text-muted-foreground">{t('filters.verification')}</label>
        <Select value={filters.verification} onValueChange={(value) => onFilterChange('verification', value)}>
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('filters.all')}</SelectItem>
            {VERIFICATIONS.map((value) => (
              <SelectItem key={value} value={value}>{formatVerification(t, value)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <label className="text-xs font-medium text-muted-foreground">{t('filters.domain')}</label>
        <Select value={filters.domain} onValueChange={(value) => onFilterChange('domain', value)}>
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('filters.all')}</SelectItem>
            {domains.map((domain) => (
              <SelectItem key={domain} value={domain}>{formatDomain(t, domain)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <label className="text-xs font-medium text-muted-foreground">{t('filters.kind')}</label>
        <Select value={filters.kind} onValueChange={(value) => onFilterChange('kind', value)}>
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('filters.all')}</SelectItem>
            {kinds.map((kind) => (
              <SelectItem key={kind} value={kind}>{formatKind(t, kind)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </aside>
  )
}

function WarningPill({ code }: { code: string }) {
  const { t } = useTranslation('knowledgeBase')
  return (
    <span className="inline-flex items-center gap-1 rounded bg-warning/10 px-1.5 py-0.5 text-[10px] font-medium text-warning">
      <AlertTriangle className="h-3 w-3" />
      {t(`quality.${code}`, { defaultValue: code })}
    </span>
  )
}

function NoteRow({
  deleting,
  note,
  onDelete,
  onOpen,
}: {
  deleting: boolean
  note: NoteListItem
  onDelete: () => void
  onOpen: () => void
}) {
  const { t } = useTranslation(['knowledgeBase', 'common'])

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onOpen()
      }}
      className="grid w-full cursor-pointer grid-cols-1 gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/50 md:grid-cols-[1fr_130px_120px_110px_44px]"
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
          <p className="truncate text-sm font-medium">{note.title}</p>
        </div>
        <p className="mt-1 truncate text-xs text-muted-foreground">{note.file_path}</p>
        {note.concepts.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {note.concepts.slice(0, 5).map((concept) => (
              <span key={concept} className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {concept}
              </span>
            ))}
            {note.concepts.length > 5 && (
              <span className="text-[10px] text-muted-foreground">+{note.concepts.length - 5}</span>
            )}
          </div>
        )}
        {(note.aliases.length > 0 || note.domain_values.length > 0 || note.kind_values.length > 0) && (
          <div className="mt-2 flex flex-wrap gap-1">
            {note.aliases.slice(0, 3).map((alias) => (
              <span key={`alias-${alias}`} className="rounded bg-secondary/10 px-1.5 py-0.5 text-[10px] text-secondary">
                {alias}
              </span>
            ))}
            {note.domain_values.slice(0, 2).map((domain) => (
              <span key={`domain-${domain}`} className="rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {formatDomain(t, domain)}
              </span>
            ))}
            {note.kind_values.slice(0, 2).map((kind) => (
              <span key={`kind-${kind}`} className="rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {formatKind(t, kind)}
              </span>
            ))}
          </div>
        )}
        {note.quality_warnings.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {note.quality_warnings.slice(0, 3).map((warning) => (
              <WarningPill key={warning} code={warning} />
            ))}
          </div>
        )}
      </div>
      <div className="flex items-start">
        <span className="rounded bg-primary/10 px-2 py-1 text-xs font-medium text-primary">
          {formatNoteType(t, note.type)}
        </span>
      </div>
      <div className="flex items-start">
        <LayerBadge layer={note.graph_layer} />
      </div>
      <div className="flex items-start justify-end">
        <VerificationBadge verification={note.verification} />
      </div>
      <div className="flex items-start justify-end">
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          title={t('actions.deleteNote')}
          disabled={deleting}
          onClick={(e) => {
            e.stopPropagation()
            onDelete()
          }}
        >
          {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
        </Button>
      </div>
    </div>
  )
}

function DiagnosticsPanel({
  diagnostics,
  error,
  loading,
}: {
  diagnostics: InstanceDiagnostics | null
  error: string | null
  loading: boolean
}) {
  const { t } = useTranslation('knowledgeBase')
  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-3">
        <LoadingState />
      </div>
    )
  }
  if (error) {
    return <div className="rounded-lg border border-error/30 bg-error/10 p-3 text-sm text-error">{error}</div>
  }
  if (!diagnostics) return null
  const { summary, issues } = diagnostics
  const topIssues = issues.slice(0, 4)
  const clean = summary.issue_count === 0

  return (
    <section className="rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {clean ? <CheckCircle2 className="h-4 w-4 text-success" /> : <AlertTriangle className="h-4 w-4 text-warning" />}
          <h2 className="text-sm font-semibold">{t('diagnostics.title')}</h2>
          <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            {t('diagnostics.issueCount', { count: summary.issue_count })}
          </span>
        </div>
        <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
          <span>{t('diagnostics.unresolved', { count: summary.unresolved_links })}</span>
          <span>{t('diagnostics.missingSources', { count: summary.missing_sources })}</span>
          <span>{t('diagnostics.unreviewed', { percent: Math.round(summary.unreviewed_ratio * 100) })}</span>
        </div>
      </div>
      {topIssues.length === 0 ? (
        <p className="mt-3 text-xs text-muted-foreground">{t('diagnostics.empty')}</p>
      ) : (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {topIssues.map((issue, index) => (
            <div key={`${issue.code}-${issue.file_path}-${index}`} className="min-w-0 rounded-md border border-border bg-background/40 p-2">
              <div className="flex items-center gap-2">
                <span className="rounded bg-warning/10 px-1.5 py-0.5 text-[10px] font-medium text-warning">
                  {t(`diagnostics.codes.${issue.code}`, { defaultValue: issue.code })}
                </span>
                {issue.file_path && <span className="truncate text-[10px] text-muted-foreground">{issue.file_path}</span>}
              </div>
              <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{issue.message}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

export default function KnowledgeBasePage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { instanceId, instances, setInstanceId, setInstances } = useInstanceStore()
  const { clearFilters, filters, searchParams, updateFilter } = useKnowledgeFilters()
  const [facets, setFacets] = useState<Record<string, string[]>>({})
  const [diagnostics, setDiagnostics] = useState<InstanceDiagnostics | null>(null)
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false)
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null)
  const [notes, setNotes] = useState<NoteListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [instancesLoading, setInstancesLoading] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<NoteListItem | null>(null)
  const [deletingPath, setDeletingPath] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const { t } = useTranslation(['knowledgeBase', 'common'])

  const requestFilters = useMemo<ListNotesFilters>(() => ({
    domain: queryValue(filters.domain) || undefined,
    graphLayer: queryValue(filters.graphLayer) ? Number(filters.graphLayer) : undefined,
    kind: queryValue(filters.kind) || undefined,
    query: filters.query.trim() || undefined,
    type: queryValue(filters.type) || undefined,
    verification: queryValue(filters.verification) || undefined,
  }), [filters.domain, filters.graphLayer, filters.kind, filters.query, filters.type, filters.verification])

  useEffect(() => {
    let cancelled = false
    if (instanceId || instances.length > 0) return () => { cancelled = true }
    queueMicrotask(() => {
      if (cancelled) return
      setInstancesLoading(true)
      listInstances()
        .then((list) => {
          if (!cancelled) setInstances(list)
        })
        .finally(() => { if (!cancelled) setInstancesLoading(false) })
    })
    return () => { cancelled = true }
  }, [instanceId, instances.length, setInstances])

  useEffect(() => {
    let cancelled = false
    if (!instanceId) {
      queueMicrotask(() => {
        if (!cancelled) {
          setFacets({})
          setDiagnostics(null)
        }
      })
      return () => { cancelled = true }
    }
    queueMicrotask(() => {
      if (cancelled) return
      setDiagnosticsLoading(true)
      setDiagnosticsError(null)
      Promise.allSettled([listNoteFacets(instanceId), getInstanceDiagnostics(instanceId)])
        .then(([facetResult, diagnosticsResult]) => {
          if (cancelled) return
          setFacets(facetResult.status === 'fulfilled' ? facetResult.value : {})
          if (diagnosticsResult.status === 'fulfilled') {
            setDiagnostics(diagnosticsResult.value)
          } else {
            setDiagnostics(null)
            setDiagnosticsError(formatApiError(t, diagnosticsResult.reason))
          }
        })
        .finally(() => { if (!cancelled) setDiagnosticsLoading(false) })
    })
    return () => { cancelled = true }
  }, [instanceId, t])

  useEffect(() => {
    let cancelled = false
    if (!instanceId) {
      queueMicrotask(() => {
        if (!cancelled) setNotes([])
      })
      return () => { cancelled = true }
    }
    queueMicrotask(() => {
      if (!cancelled) {
        setLoading(true)
        setError(null)
      }
    })
    listNotes(instanceId, requestFilters)
      .then((data) => { if (!cancelled) setNotes(data) })
      .catch((e) => { if (!cancelled) setError(formatApiError(t, e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [instanceId, requestFilters, t])

  const domains = useMemo(() => facets.domain || [], [facets])
  const kinds = useMemo(() => facets.kind || [], [facets])
  const sortedNotes = useMemo(() => sortNotes(notes, filters.sort), [filters.sort, notes])

  const openNote = (path: string) => {
    const returnTo = `${location.pathname}${location.search}`
    navigate(`/note/${encodeURIComponent(path)}`, {
      state: { returnLabelKey: 'noteDetail:return.knowledge', returnTo },
    })
  }

  const handleCreated = (instance: Instance) => {
    setInstanceId(instance.id)
    setInstances([...instances.filter((item) => item.id !== instance.id), instance])
  }

  const refreshFacetsAndDiagnostics = useCallback(() => {
    if (!instanceId) return
    setDiagnosticsLoading(true)
    setDiagnosticsError(null)
    Promise.allSettled([listNoteFacets(instanceId), getInstanceDiagnostics(instanceId)])
      .then(([facetResult, diagnosticsResult]) => {
        setFacets(facetResult.status === 'fulfilled' ? facetResult.value : {})
        if (diagnosticsResult.status === 'fulfilled') {
          setDiagnostics(diagnosticsResult.value)
        } else {
          setDiagnostics(null)
          setDiagnosticsError(formatApiError(t, diagnosticsResult.reason))
        }
      })
      .finally(() => setDiagnosticsLoading(false))
  }, [instanceId, t])

  const handleDeleteNote = async () => {
    if (!instanceId || !deleteTarget || deletingPath) return
    setDeletingPath(deleteTarget.file_path)
    setDeleteError(null)
    try {
      await deleteNote(instanceId, deleteTarget.file_path)
      setNotes((current) => current.filter((note) => note.file_path !== deleteTarget.file_path))
      setDeleteTarget(null)
      setActionMessage(t('actions.deleted'))
      refreshFacetsAndDiagnostics()
    } catch (e) {
      setDeleteError(formatApiError(t, e))
    } finally {
      setDeletingPath(null)
    }
  }

  if (!instanceId) {
    if (instancesLoading) return <LoadingState />
    if (instances.length === 0) {
      return (
        <div className="flex min-h-[420px] flex-col items-center justify-center gap-4 rounded-lg border border-dashed border-border bg-card/60 p-8 text-center">
          <EmptyState title={t('empty.noInstancesTitle')} description={t('empty.noInstancesDescription')} />
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t('empty.createFirst')}
          </Button>
          <CreateInstanceDialog open={createOpen} onOpenChange={setCreateOpen} onCreated={handleCreated} />
        </div>
      )
    }
    return <p className="text-sm text-muted-foreground">{t('common:selectInstance')}</p>
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <BookOpen className="h-5 w-5 text-primary" />
            {t('title')}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">{t('description')}</p>
        </div>
        <div className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
          <span className="font-mono text-foreground">{sortedNotes.length}</span>
          {t('countUnit')}
        </div>
      </div>
      {actionMessage && <p className="text-sm text-success">{actionMessage}</p>}

      <div className="flex flex-col gap-4 lg:flex-row">
        <KnowledgeFilters
          domains={domains}
          kinds={kinds}
          filters={filters}
          onClear={clearFilters}
          onFilterChange={updateFilter}
        />

        <section className="min-w-0 flex-1 space-y-3">
          <DiagnosticsPanel diagnostics={diagnostics} error={diagnosticsError} loading={diagnosticsLoading} />

          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-3">
            <div className="relative min-w-64 flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={filters.query}
                onChange={(e) => updateFilter('q', e.target.value)}
                placeholder={t('searchPlaceholder')}
                className="pl-9"
              />
            </div>
            <div className="flex items-center gap-2">
              <ArrowDownAZ className="h-4 w-4 text-muted-foreground" />
              <Select value={filters.sort} onValueChange={(value) => updateFilter('sort', value)}>
                <SelectTrigger className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="title">{t('sort.title')}</SelectItem>
                  <SelectItem value="type">{t('sort.type')}</SelectItem>
                  <SelectItem value="layer">{t('sort.layer')}</SelectItem>
                  <SelectItem value="verification">{t('sort.verification')}</SelectItem>
                  <SelectItem value="indexed">{t('sort.indexed')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="overflow-hidden rounded-lg border border-border bg-card">
            <div className="hidden grid-cols-[1fr_130px_120px_110px_44px] gap-3 border-b border-border px-4 py-2 text-xs font-medium text-muted-foreground md:grid">
              <span>{t('table.note')}</span>
              <span>{t('table.type')}</span>
              <span>{t('table.layer')}</span>
              <span className="text-right">{t('table.verification')}</span>
              <span />
            </div>
            {loading ? (
              <LoadingState />
            ) : error ? (
              <p className="px-4 py-8 text-center text-sm text-error">{error}</p>
            ) : sortedNotes.length === 0 ? (
              <EmptyState title={searchParams.toString() ? t('empty.filtered') : t('empty.default')} />
            ) : (
              <div className="divide-y divide-border">
                {sortedNotes.map((note) => (
                  <NoteRow
                    key={note.file_path}
                    deleting={deletingPath === note.file_path}
                    note={note}
                    onDelete={() => {
                      setDeleteTarget(note)
                      setDeleteError(null)
                      setActionMessage(null)
                    }}
                    onOpen={() => openNote(note.file_path)}
                  />
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('actions.deleteTitle')}</DialogTitle>
            <DialogDescription>
              {deleteTarget?.title ? `${t('actions.deleteDescription')} (${deleteTarget.title})` : t('actions.deleteDescription')}
            </DialogDescription>
          </DialogHeader>
          {deleteError && (
            <div className="rounded bg-destructive/10 p-2 text-sm text-destructive">{deleteError}</div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              {t('actions.cancel')}
            </Button>
            <Button variant="destructive" onClick={() => void handleDeleteNote()} disabled={Boolean(deletingPath)}>
              {deletingPath && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('actions.confirmDelete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
