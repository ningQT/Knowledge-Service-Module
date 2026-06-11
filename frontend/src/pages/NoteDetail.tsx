import { useEffect, useState } from 'react'
import { useLocation, useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2, Pencil, Trash2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkWikiLink from '@/plugins/remarkWikiLink'
import rehypeHighlight from 'rehype-highlight'
import { useInstanceStore } from '@/stores/useInstanceStore'
import { getGraph } from '@/services/graph'
import { deleteNote, getNote, updateNoteMetadata, updateNoteVerification, type NoteData, type UserVerification } from '@/services/notes'
import { LoadingState } from '@/components/shared/LoadingState'
import { VerificationBadge } from '@/components/shared/VerificationBadge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ApiError, formatApiError, formatDomain, formatGraphLayer, formatKind, formatNoteType, formatRelationType, formatVerification } from '@/lib/i18nFormat'
import { useTranslation } from 'react-i18next'

interface RelatedNode {
  id: string
  title: string
  relCounts: Record<string, number>
}

interface NoteReturnState {
  returnLabelKey?: string
  returnTo?: string
}

interface NoteLookupNode {
  id: string
  title: string
}

const EDITABLE_VERIFICATIONS: UserVerification[] = ['verified', 'unverified', 'draft']

type MarkdownLinkProps = React.AnchorHTMLAttributes<HTMLAnchorElement> & {
  node?: unknown
  'data-wiki-target'?: string
}

function getPrimaryReviewAction(verification: string): UserVerification {
  if (verification === 'verified') return 'unverified'
  if (verification === 'truncated') return 'draft'
  return 'verified'
}

function getReviewActionLabelKey(target: UserVerification) {
  if (target === 'verified') return 'review.markReviewed'
  if (target === 'unverified') return 'review.markUnreviewed'
  return 'review.markNeedsRevision'
}

function normalizeNoteLookupKey(value: string) {
  return value.trim().replace(/\\/g, '/').replace(/^\/+/, '')
}

function withoutMarkdownExtension(value: string) {
  return value.replace(/\.md$/i, '')
}

function getFileName(value: string) {
  const normalized = normalizeNoteLookupKey(value)
  return normalized.split('/').filter(Boolean).at(-1) || normalized
}

function addLookupKey(lookup: Map<string, string>, key: string | null | undefined, canonicalPath: string) {
  if (!key) return
  const normalized = normalizeNoteLookupKey(key)
  if (!normalized) return
  if (!lookup.has(normalized)) lookup.set(normalized, canonicalPath)
  const folded = normalized.toLowerCase()
  if (!lookup.has(folded)) lookup.set(folded, canonicalPath)
}

function buildNotePathLookup(nodes: NoteLookupNode[]) {
  const lookup = new Map<string, string>()

  for (const node of nodes) {
    const canonicalPath = normalizeNoteLookupKey(node.id)
    const fileName = getFileName(canonicalPath)
    addLookupKey(lookup, canonicalPath, canonicalPath)
    addLookupKey(lookup, withoutMarkdownExtension(canonicalPath), canonicalPath)
    addLookupKey(lookup, fileName, canonicalPath)
    addLookupKey(lookup, withoutMarkdownExtension(fileName), canonicalPath)
  }

  for (const node of nodes) {
    addLookupKey(lookup, node.title, normalizeNoteLookupKey(node.id))
  }

  return lookup
}

function resolveWikiTarget(target: string, lookup: Map<string, string>) {
  const normalized = normalizeNoteLookupKey(target)
  return lookup.get(normalized) || lookup.get(normalized.toLowerCase()) || null
}

export default function NoteDetail() {
  const { path } = useParams<{ path: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { instanceId } = useInstanceStore()
  const [note, setNote] = useState<NoteData | null>(null)
  const [loading, setLoading] = useState(true)
  const [relatedNodes, setRelatedNodes] = useState<RelatedNode[]>([])
  const [reviewUpdating, setReviewUpdating] = useState<UserVerification | null>(null)
  const [reviewMessage, setReviewMessage] = useState<string | null>(null)
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [notePathLookup, setNotePathLookup] = useState<Map<string, string>>(new Map())
  const [metadataOpen, setMetadataOpen] = useState(false)
  const [editDomain, setEditDomain] = useState('')
  const [editKind, setEditKind] = useState('')
  const [editVerification, setEditVerification] = useState<UserVerification>('unverified')
  const [metadataUpdating, setMetadataUpdating] = useState(false)
  const [metadataMessage, setMetadataMessage] = useState<string | null>(null)
  const [metadataError, setMetadataError] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const { t } = useTranslation(['noteDetail', 'common'])
  const returnState = (location.state || {}) as NoteReturnState
  const returnTo = returnState.returnTo || '/knowledge'
  const returnLabelKey = returnState.returnLabelKey || 'return.knowledge'

  useEffect(() => {
    let cancelled = false
    if (!instanceId || !path) {
      queueMicrotask(() => {
        if (!cancelled) setLoading(false)
      })
      return () => { cancelled = true }
    }

    const controller = new AbortController()
    const normPath = decodeURIComponent(path).trim()

    getNote(instanceId, normPath, controller.signal)
      .then(setNote)
      .catch((err) => {
        if (controller.signal.aborted) return
        if ((err instanceof ApiError && err.status === 404) || err?.response?.status === 404) {
          setNote(null)
        } else {
          console.error('Failed to load note:', err)
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })

    // Fetch related nodes from graph
    getGraph(instanceId)
      .then((data) => {
        if (controller.signal.aborted) return
        const nodesById = new Map(data.nodes.map((node) => [node.id, node]))
        const related = new Map<string, RelatedNode>()
        for (const edge of data.edges) {
          const src = edge.source.trim()
          const tgt = edge.target.trim()
          let relatedId: string | null = null
          if (src === normPath) {
            relatedId = tgt
          } else if (tgt === normPath) {
            relatedId = src
          }
          if (!relatedId) continue
          const relatedNode = nodesById.get(relatedId)
          if (!relatedNode) continue
          const current = related.get(relatedId) || {
            id: relatedId,
            relCounts: {},
            title: relatedNode.title,
          }
          current.relCounts[edge.rel_type] = (current.relCounts[edge.rel_type] || 0) + 1
          related.set(relatedId, current)
        }
        setRelatedNodes([...related.values()].sort((a, b) => a.title.localeCompare(b.title)))
        setNotePathLookup(buildNotePathLookup(data.nodes))
      })
      .catch(() => {})

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [instanceId, path])

  if (loading) return <LoadingState />
  if (!note) return <p className="text-muted-foreground">{t('notFound')}</p>

  const concepts = (note.frontmatter?.concepts as string[]) || []
  const primaryReviewAction = getPrimaryReviewAction(note.verification)
  const showNeedsRevisionAction = primaryReviewAction !== 'draft'
  const handleBack = () => {
    navigate(returnTo)
  }
  const openRelatedNode = (id: string) => {
    navigate(`/note/${encodeURIComponent(id)}`, {
      replace: true,
      state: { returnLabelKey, returnTo },
    })
  }
  function LinkRenderer(props: MarkdownLinkProps) {
    const {
      'data-wiki-target': wikiTarget,
      children,
      className,
      href,
      node,
      ...anchorProps
    } = props
    void node

    if (!wikiTarget) {
      return <a {...anchorProps} href={href} className={className} target="_blank" rel="noopener noreferrer">{children}</a>
    }

    const canonicalPath = resolveWikiTarget(wikiTarget, notePathLookup)
    const isResolved = Boolean(canonicalPath)
    return (
      <a
        {...anchorProps}
        href={isResolved ? `/note/${encodeURIComponent(canonicalPath!)}` : href}
        className={[
          'wiki-link cursor-pointer transition-colors',
          isResolved
            ? 'text-primary underline decoration-primary/30 hover:decoration-primary/80'
            : 'wiki-link-unresolved text-muted-foreground opacity-70 decoration-dashed underline',
        ].join(' ')}
        onClick={(e) => {
          e.preventDefault()
          if (canonicalPath) {
            navigate(`/note/${encodeURIComponent(canonicalPath)}`, {
              state: { returnLabelKey, returnTo },
            })
          }
        }}
        title={wikiTarget}
      >
        {children}
      </a>
    )
  }
  const updateReviewStatus = async (verification: UserVerification) => {
    if (!instanceId || !note || verification === note.verification || reviewUpdating) return
    setReviewUpdating(verification)
    setReviewMessage(null)
    setReviewError(null)
    try {
      const updatedNote = await updateNoteVerification(instanceId, note.file_path, verification)
      setNote(updatedNote)
      setReviewMessage(t('review.updated'))
    } catch (e) {
      setReviewError(formatApiError(t, e) || t('review.failed'))
    } finally {
      setReviewUpdating(null)
    }
  }
  const openMetadataDialog = () => {
    setEditDomain(note.domain || '')
    setEditKind(note.kind || '')
    setEditVerification(
      EDITABLE_VERIFICATIONS.includes(note.verification as UserVerification)
        ? note.verification as UserVerification
        : 'draft'
    )
    setMetadataMessage(null)
    setMetadataError(null)
    setMetadataOpen(true)
  }
  const saveMetadata = async () => {
    if (!instanceId || !note || metadataUpdating) return
    setMetadataUpdating(true)
    setMetadataError(null)
    setMetadataMessage(null)
    try {
      const metadata: { domain: string; kind: string; verification?: UserVerification } = {
        domain: editDomain,
        kind: editKind,
      }
      if (EDITABLE_VERIFICATIONS.includes(note.verification as UserVerification) || editVerification !== 'draft') {
        metadata.verification = editVerification
      }
      const updatedNote = await updateNoteMetadata(instanceId, note.file_path, metadata)
      setNote(updatedNote)
      setMetadataOpen(false)
      setMetadataMessage(t('metadata.updated'))
    } catch (e) {
      setMetadataError(formatApiError(t, e) || t('metadata.failed'))
    } finally {
      setMetadataUpdating(false)
    }
  }
  const handleDeleteNote = async () => {
    if (!instanceId || !note || deleting) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteNote(instanceId, note.file_path)
      navigate(returnTo)
    } catch (e) {
      setDeleteError(formatApiError(t, e) || t('delete.failed'))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <button
        onClick={handleBack}
        className="flex w-full shrink-0 items-center gap-3 rounded-lg border border-border bg-card/95 px-3 py-2 text-sm text-muted-foreground shadow-sm backdrop-blur transition-colors hover:text-foreground"
      >
        <ArrowLeft className="w-4 h-4" />
        <span className="shrink-0">{t(returnLabelKey)}</span>
        <span className="min-w-0 truncate border-l border-border pl-3 font-medium text-foreground">{note.title}</span>
      </button>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
          {/* Metadata panel */}
          <aside className="sticky top-0 self-start space-y-4">
            <div className="bg-card rounded-lg border border-border p-4 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <h3 className="font-medium text-sm">{t('metadata.title')}</h3>
                <Button variant="ghost" size="icon-xs" title={t('metadata.edit')} onClick={openMetadataDialog}>
                  <Pencil className="h-3 w-3" />
                </Button>
              </div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{t('metadata.type')}</span>
                  <span>{formatNoteType(t, note.type)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{t('metadata.layer')}</span>
                  <span>{formatGraphLayer(t, note.graph_layer)}</span>
                </div>
                {note.domain && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{t('metadata.domain')}</span>
                    <span>{formatDomain(t, note.domain)}</span>
                  </div>
                )}
                {note.kind && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{t('metadata.kind')}</span>
                    <span>{formatKind(t, note.kind)}</span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{t('metadata.verification')}</span>
                  <VerificationBadge verification={note.verification} />
                </div>
              </div>
              {metadataMessage && <p className="text-xs text-success">{metadataMessage}</p>}
            </div>

            <div className="bg-card rounded-lg border border-border p-4 space-y-3">
              <h3 className="font-medium text-sm">{t('review.title')}</h3>
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => void updateReviewStatus(primaryReviewAction)}
                  disabled={Boolean(reviewUpdating)}
                  className="w-full rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
                >
                  {reviewUpdating === primaryReviewAction ? '...' : t(getReviewActionLabelKey(primaryReviewAction))}
                </button>
                {showNeedsRevisionAction && (
                  <button
                    type="button"
                    onClick={() => void updateReviewStatus('draft')}
                    disabled={note.verification === 'draft' || Boolean(reviewUpdating)}
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-60"
                  >
                    {reviewUpdating === 'draft' ? '...' : t('review.markNeedsRevision')}
                  </button>
                )}
                {reviewMessage && <p className="text-xs text-success">{reviewMessage}</p>}
                {reviewError && <p className="text-xs text-error">{reviewError}</p>}
              </div>
            </div>

            <div className="bg-card rounded-lg border border-border p-4 space-y-3">
              <h3 className="font-medium text-sm">{t('delete.title')}</h3>
              <Button variant="destructive" size="sm" className="w-full" onClick={() => setDeleteOpen(true)}>
                <Trash2 className="h-4 w-4" />
                {t('delete.button')}
              </Button>
            </div>

            {concepts.length > 0 && (
              <div className="bg-card rounded-lg border border-border p-4">
                <h3 className="font-medium text-sm mb-2">{t('concepts.title')}</h3>
                <div className="flex max-h-48 flex-wrap gap-1 overflow-hidden">
                  {concepts.map((c) => (
                    <span key={c} className="text-xs bg-muted px-2 py-1 rounded">
                      {c}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {relatedNodes.length > 0 && (
              <div className="bg-card rounded-lg border border-border p-4">
                <h3 className="font-medium text-sm mb-2">{t('relatedNodes.title')}</h3>
                <div className="max-h-[min(360px,40vh)] space-y-1.5 overflow-hidden">
                  {relatedNodes.map((rn) => (
                    <button
                      key={rn.id}
                      onClick={() => openRelatedNode(rn.id)}
                      className="w-full text-left space-y-1 rounded px-2 py-2 hover:bg-muted transition-colors"
                    >
                      <span className="block truncate text-xs font-medium">{rn.title}</span>
                      <span className="flex flex-wrap gap-1">
                        {Object.entries(rn.relCounts).map(([relType, count]) => (
                          <span key={relType} className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                            {formatRelationType(t, relType)} x{count}
                          </span>
                        ))}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </aside>

          {/* Content */}
          <div className="rounded-lg border border-border bg-card p-6">
            <article className="note-markdown prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm, remarkWikiLink]} rehypePlugins={[rehypeHighlight]} components={{ a: LinkRenderer }}>{note.body}</ReactMarkdown>
            </article>
          </div>
        </div>
      </div>
      <Dialog open={metadataOpen} onOpenChange={setMetadataOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('metadata.edit')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <label className="block text-sm font-medium mb-1">{t('metadata.domain')}</label>
              <Input value={editDomain} onChange={(e) => setEditDomain(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">{t('metadata.kind')}</label>
              <Input value={editKind} onChange={(e) => setEditKind(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">{t('metadata.verification')}</label>
              <Select value={editVerification} onValueChange={(value) => setEditVerification(value as UserVerification)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EDITABLE_VERIFICATIONS.map((value) => (
                    <SelectItem key={value} value={value}>{formatVerification(t, value)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {metadataError && (
              <div className="rounded bg-destructive/10 p-2 text-sm text-destructive">{metadataError}</div>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setMetadataOpen(false)}>
              {t('delete.cancel')}
            </Button>
            <Button onClick={() => void saveMetadata()} disabled={metadataUpdating}>
              {metadataUpdating && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('metadata.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('delete.title')}</DialogTitle>
            <DialogDescription>{t('delete.description')}</DialogDescription>
          </DialogHeader>
          {deleteError && (
            <div className="rounded bg-destructive/10 p-2 text-sm text-destructive">{deleteError}</div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteOpen(false)}>
              {t('delete.cancel')}
            </Button>
            <Button variant="destructive" onClick={() => void handleDeleteNote()} disabled={deleting}>
              {deleting && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('delete.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
