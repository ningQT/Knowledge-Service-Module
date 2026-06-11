import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import {
  Search,
  Loader2,
  FileText,
  Map as MapIcon,
  BookOpen,
  Zap,
  BarChart3,
  ChevronDown,
  ChevronRight,
  X,
  Sparkles,
  CheckCircle,
  Clock,
  XCircle,
  Link2,
} from 'lucide-react'
import { useInstanceStore } from '@/stores/useInstanceStore'
import { useSearchStore, type SearchTabKey } from '@/stores/useSearchStore'
import { createAnswerJobSSEToken, getAnswerJob, getAnswerJobSSEUrl, search, startAnswerJob } from '@/services/search'
import type { AnswerResult, AnswerSection, AnswerStep, BatchProcessDetail, ProcessSummary, SearchResult, SearchStats } from '@/types/api'
import { useSSE } from '@/hooks/useSSE'
import { VerificationBadge } from '@/components/shared/VerificationBadge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { formatApiError, formatNoteType, formatSearchIntent, formatSearchPath } from '@/lib/i18nFormat'
import remarkCitationLink from '@/plugins/remarkCitationLink'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'

type TabKey = SearchTabKey

function StatsBar({
  stats,
  intentType,
  elapsedMs,
  mapPriority,
}: {
  stats: SearchStats
  intentType: string
  elapsedMs?: number
  mapPriority: boolean
}) {
  const { t } = useTranslation('search')

  return (
    <div className="flex items-center gap-4 text-xs text-muted-foreground">
      <span className="px-2 py-0.5 bg-primary/10 text-primary rounded font-medium">{formatSearchIntent(t, intentType)}</span>
      <span>{t('stats.path', { path: formatSearchPath(t, stats.search_path) })}</span>
      <span>{t('stats.total', { count: stats.total })}</span>
      {elapsedMs !== undefined && (
        <span>{elapsedMs < 1000 ? t('stats.elapsedMs', { ms: elapsedMs }) : t('stats.elapsedS', { s: (elapsedMs / 1000).toFixed(1) })}</span>
      )}
      {stats.fallback_mode && (
        <span className="px-2 py-0.5 bg-warning/10 text-warning rounded">{t('stats.fallback')}</span>
      )}
      {mapPriority && (
        <span className="px-2 py-0.5 bg-success/10 text-success rounded">{t('stats.mapPriority')}</span>
      )}
      {stats.map_sourced_count > 0 && (
        <span>{t('stats.mapSourced', { count: stats.map_sourced_count })}</span>
      )}
    </div>
  )
}

function SearchContextPanel({ result }: { result: SearchResult }) {
  const { t } = useTranslation('search')
  const candidates = result.query_context?.concept_candidates || []
  const domainHint = result.query_context?.domain_hint
  const matchedFacets = result.query_context?.matched_facets || []
  const keyRelations = result.key_relations || []

  if (!candidates.length && !domainHint && !matchedFacets.length && !keyRelations.length) return null

  return (
    <div className="rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
      <div className="flex flex-wrap gap-2">
        {candidates.length > 0 && (
          <span>{t('context.candidates')}: <span className="text-foreground">{candidates.join(', ')}</span></span>
        )}
        {domainHint && (
          <span>{t('context.domain')}: <span className="text-foreground">{domainHint}</span></span>
        )}
        {matchedFacets.length > 0 && (
          <span>{t('context.facets', { count: matchedFacets.length })}</span>
        )}
        {keyRelations.length > 0 && (
          <span>{t('context.keyRelations', { count: keyRelations.length })}</span>
        )}
      </div>
    </div>
  )
}

function ResultCard({
  hit,
  onClick,
}: {
  hit: Record<string, unknown>
  onClick: () => void
}) {
  const { t } = useTranslation('search')
  const title: string = String(hit.title || hit.path || t('untitled'))
  const type: string = String(hit.type || hit.note_type || '')
  const domain: string | null = hit.domain ? String(hit.domain) : null
  const verification: string = String(hit.verification || 'unverified')
  const concepts: string[] = (hit.concepts as string[]) || []
  const score: number | null = typeof hit.score === 'number' ? hit.score : null
  const matchType = hit.match_type ? String(hit.match_type) : ''
  const matchKeyword = hit.match_keyword ? String(hit.match_keyword) : ''
  const mapSourced = Boolean(hit.map_sourced)
  const sourceMap = hit.source_map ? String(hit.source_map) : ''

  return (
    <div
      onClick={onClick}
      className="bg-card border border-border rounded-lg p-4 hover:border-primary/50 cursor-pointer transition-colors"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            {type && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary font-mono">
                {formatNoteType(t, type)}
              </span>
            )}
            <VerificationBadge verification={verification} className="text-[10px] px-1.5 py-0.5" />
            {score !== null && (
              <span className="text-[10px] text-muted-foreground">
                {t('stats.score', { score: score.toFixed(2) })}
              </span>
            )}
          </div>
          <p className="text-sm font-medium truncate">{String(title)}</p>
          {domain && <p className="text-xs text-muted-foreground mt-0.5">{String(domain)}</p>}
          {(matchType || matchKeyword || mapSourced) && (
            <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-muted-foreground">
              {matchType && <span className="rounded bg-muted px-1.5 py-0.5">{t('basis.matchType', { type: matchType })}</span>}
              {matchKeyword && <span className="rounded bg-muted px-1.5 py-0.5">{t('basis.keyword', { keyword: matchKeyword })}</span>}
              {mapSourced && <span className="rounded bg-success/10 px-1.5 py-0.5 text-success">{sourceMap || t('basis.mapSourced')}</span>}
            </div>
          )}
        </div>
      </div>
      {concepts.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {concepts.slice(0, 4).map((c) => (
            <span key={c} className="text-[10px] bg-muted px-1.5 py-0.5 rounded">
              {c}
            </span>
          ))}
          {concepts.length > 4 && (
            <span className="text-[10px] text-muted-foreground">+{concepts.length - 4}</span>
          )}
        </div>
      )}
    </div>
  )
}

function ComprehensionPanel({ data }: { data: Record<string, unknown> }) {
  const { t } = useTranslation('search')
  const conceptCoverage = data.concept_coverage as Record<string, unknown> | undefined
  const documents = data.documents as Record<string, unknown>[] | undefined
  const duplicates = data.duplicates as Record<string, unknown>[] | undefined
  const mapInsights = data.map_insights as Record<string, unknown>[] | undefined
  const hierarchy = data.hierarchy as Record<string, unknown>[] | undefined
  const [expandedDocs, setExpandedDocs] = useState<Set<number>>(new Set())

  // Initialize expanded state for default-open documents
  useEffect(() => {
    if (!documents) return
    let cancelled = false
    const defaultOpen = new Set<number>()
    documents.forEach((doc, i) => {
      if (doc.group === 'core' || doc.is_primary) defaultOpen.add(i)
    })
    queueMicrotask(() => {
      if (!cancelled) setExpandedDocs(defaultOpen)
    })
    return () => { cancelled = true }
  }, [documents])

  const toggleDoc = (index: number) => {
    setExpandedDocs((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  // Sort: is_primary first, then graph_layer ascending
  const sortedDocs = documents
    ? [...documents]
        .map((doc, i) => ({ doc, origIndex: i }))
        .sort((a, b) => {
          const pa = a.doc.is_primary ? 0 : 1
          const pb = b.doc.is_primary ? 0 : 1
          if (pa !== pb) return pa - pb
          const la = (a.doc.graph_layer as number) ?? 99
          const lb = (b.doc.graph_layer as number) ?? 99
          return la - lb
        })
    : []

  return (
    <div className="bg-card border border-border rounded-lg p-4 space-y-4">
      <h3 className="font-medium flex items-center gap-2">
        <BarChart3 className="w-4 h-4" />
        {t('comprehension.title')}
      </h3>

      {conceptCoverage && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">{t('comprehension.conceptCoverage')}</p>
          <div className="flex items-center gap-3">
            <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-success rounded-full"
                style={{ width: `${((conceptCoverage.coverage_ratio as number) * 100) || 0}%` }}
              />
            </div>
            <span className="text-xs font-mono">
              {((conceptCoverage.coverage_ratio as number) * 100).toFixed(0)}%
            </span>
          </div>
          {Array.isArray(conceptCoverage.covered_concepts) && (
            <div className="flex flex-wrap gap-1">
              {(conceptCoverage.covered_concepts as string[]).map((c) => (
                <span key={c} className="text-[10px] bg-success/10 text-success px-1.5 py-0.5 rounded">
                  {c}
                </span>
              ))}
              {(conceptCoverage.gap_concepts as string[])?.map((c) => (
                <span key={c} className="text-[10px] bg-error/10 text-error px-1.5 py-0.5 rounded">
                  {c}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {documents && documents.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">
            {t('comprehension.understanding', { count: documents.length })}
          </p>
          <div className="space-y-2">
            {sortedDocs.map(({ doc, origIndex }) => {
              const isOpen = expandedDocs.has(origIndex)
              const content = doc.content as string | null | undefined
              const isMissing = Boolean(doc.missing)
              return (
                <div key={origIndex} className="border border-border rounded-md overflow-hidden">
                  <button
                    onClick={() => toggleDoc(origIndex)}
                    className="w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-muted/50 transition-colors"
                  >
                    {isOpen ? <ChevronDown className="w-3 h-3 shrink-0" /> : <ChevronRight className="w-3 h-3 shrink-0" />}
                    {Boolean(doc.group) && (
                      <span className="text-muted-foreground font-mono">{String(doc.group)}</span>
                    )}
                    <span className="font-medium truncate text-left flex-1">{String(doc.title || '')}</span>
                    {Boolean(doc.is_primary) && (
                      <span className="text-[10px] bg-primary/10 text-primary px-1 rounded">{t('primary')}</span>
                    )}
                    {Boolean(doc.truncated) && (
                      <span className="text-[10px] bg-warning/10 text-warning px-1 rounded">{t('common:truncated')}</span>
                    )}
                  </button>
                  {isOpen && (
                    <div className="px-3 pb-3 pt-1 border-t border-border">
                      {content && !isMissing ? (
                        <p className="text-xs text-muted-foreground whitespace-pre-wrap leading-relaxed">{content}</p>
                      ) : (
                        <p className="text-xs text-muted-foreground italic">{t('comprehension.noContent')}</p>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {duplicates && duplicates.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">{t('comprehension.duplicates')}</p>
          {duplicates.map((dup, i) => (
            <div key={i} className="text-xs flex items-center gap-2">
              <span className="font-mono text-muted-foreground">{dup.node_a as string}</span>
              <span>~</span>
              <span className="font-mono text-muted-foreground">{dup.node_b as string}</span>
              <span className="text-warning">({((dup.similarity as number) * 100).toFixed(0)}%)</span>
            </div>
          ))}
        </div>
      )}

      {mapInsights && mapInsights.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">{t('comprehension.mapInsights')}</p>
          {mapInsights.map((insight, i) => (
            <div key={i} className="text-xs">
              <p className="font-medium">{String(insight.map_title || '')}</p>
              {Boolean(insight.insight_preview) && (
                <p className="text-muted-foreground mt-0.5">{String(insight.insight_preview)}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {hierarchy && hierarchy.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">{t('comprehension.hierarchy')}</p>
          {hierarchy.map((h, i) => (
            <div key={i} className="text-xs flex items-center gap-1.5">
              <span className="font-medium truncate">{String(h.parent || '')}</span>
              <span className="text-muted-foreground">→</span>
              <span className="truncate">{String(h.child || '')}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const ANSWER_STEP_KEYS = [
  'question_understanding',
  'map_discovery',
  'card_reading',
  'citation_tracing',
  'batch_summarization',
  'answer_synthesis',
  'citation_validation',
]

const SYSTEM_STEP_NAMES = [
  'question_understanding',
  'map_discovery',
  'card_reading',
  'citation_tracing',
  'citation_validation',
] as const

const LLM_STEP_NAMES = [
  'batch_summarization',
  'answer_synthesis',
] as const

const LLM_STEP_NAME_SET = new Set<string>(LLM_STEP_NAMES)
const ACTIVE_ANSWER_STATUSES = new Set(['pending', 'running'])

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function asStringArray(value: unknown): string[] {
  return asArray(value).map((item) => String(item)).filter(Boolean)
}

function valueLabel(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (Array.isArray(value)) return value.map((item) => String(item)).join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function createAnswerSteps(): AnswerStep[] {
  return ANSWER_STEP_KEYS.map((name, index) => ({
    step: index + 1,
    name,
    status: 'pending',
    summary: null,
  }))
}

function mergeAnswerStep(steps: AnswerStep[], incoming: Partial<AnswerStep> & { step?: number }): AnswerStep[] {
  if (!incoming.step) return steps
  const next = steps.length ? [...steps] : createAnswerSteps()
  const index = next.findIndex((step) => step.step === incoming.step)
  const normalized = {
    step: incoming.step,
    name: incoming.name || ANSWER_STEP_KEYS[incoming.step - 1] || `step_${incoming.step}`,
    status: (incoming.status || 'pending') as AnswerStep['status'],
    summary: incoming.summary ?? null,
  }
  if (index >= 0) next[index] = { ...next[index], ...normalized }
  else next.push(normalized)
  return next.sort((a, b) => a.step - b.step)
}

function summaryFromStep(step: AnswerStep, title: string): ProcessSummary | null {
  if (!step.summary) return null
  return {
    step: step.name,
    title,
    summary: Object.entries(step.summary)
      .filter(([, value]) => value !== null && value !== undefined)
      .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(', ') : String(value)}`)
      .join(' · '),
    details: step.summary,
  }
}

function sortBatchDetails(batches: BatchProcessDetail[]): BatchProcessDetail[] {
  return [...batches].sort((a, b) => {
    const aMatch = String(a.batch_id || '').match(/\d+/)
    const bMatch = String(b.batch_id || '').match(/\d+/)
    if (aMatch && bMatch) return Number(aMatch[0]) - Number(bMatch[0])
    return String(a.batch_id || '').localeCompare(String(b.batch_id || ''))
  })
}

function replaceProcessSummary(prev: ProcessSummary[], next: ProcessSummary): ProcessSummary[] {
  const index = prev.findIndex((item) => item.step === next.step)
  if (index < 0) return [...prev, next]
  const updated = [...prev]
  updated[index] = next
  return updated
}

function mergeThoughtSummary(prev: ProcessSummary[], step: AnswerStep, title: string): ProcessSummary[] {
  if (!LLM_STEP_NAME_SET.has(step.name) || !step.summary) return prev

  const incoming = asRecord(step.summary)
  const type = String(incoming.type || '')
  const existing = prev.find((item) => item.step === step.name)
  let next: ProcessSummary = existing
    ? { ...existing, details: { ...existing.details } }
    : { step: step.name, title, summary: '', details: {} }

  if (type === 'batch_detail') {
    const batch = asRecord(incoming.batch) as unknown as BatchProcessDetail
    const batchId = String(batch.batch_id || '')
    if (!batchId) return prev
    const existingBatches = asArray(next.details.batches).map((item) => asRecord(item) as unknown as BatchProcessDetail)
    const existingBatch = existingBatches.find((item) => item.batch_id === batchId)
    const mergedBatch: BatchProcessDetail = { ...existingBatch, ...batch, batch_id: batchId }
    const batches = sortBatchDetails([
      ...existingBatches.filter((item) => item.batch_id !== batchId),
      mergedBatch,
    ])
    next = {
      ...next,
      summary: title,
      details: {
        ...next.details,
        summary_batches_total: incoming.total_batches ?? next.details.summary_batches_total,
        batches,
      },
    }
    return replaceProcessSummary(prev, next)
  }

  if (type === 'synthesis_input') {
    next = {
      ...next,
      summary: title,
      details: {
        ...next.details,
        used_batch_ids: incoming.used_batch_ids,
        total_cards_summarized: incoming.total_cards_summarized,
        citations_traced: incoming.citations_traced,
        citations_untraced: incoming.citations_untraced,
        topics: incoming.topics,
        synthesis_running: true,
      },
    }
    return replaceProcessSummary(prev, next)
  }

  if (type === 'synthesis_output') {
    next = {
      ...next,
      summary: title,
      details: {
        ...next.details,
        section_titles: incoming.section_titles,
        section_count: incoming.section_count,
        key_points_count: incoming.key_points_count,
        answer_chars: incoming.answer_chars,
        answer_md_chars: incoming.answer_md_chars,
        section_content_md_chars: incoming.section_content_md_chars,
        markdown_report: incoming.markdown_report,
        section_llm_success: incoming.section_llm_success,
        section_fallbacks: incoming.section_fallbacks,
        overview_fallback: incoming.overview_fallback,
        elapsed_ms: incoming.elapsed_ms,
        model: incoming.model,
        synthesis_running: false,
      },
    }
    return replaceProcessSummary(prev, next)
  }

  const legacy = summaryFromStep(step, title)
  if (!legacy) return prev
  if (!existing) return replaceProcessSummary(prev, legacy)
  return replaceProcessSummary(prev, {
    ...next,
    summary: legacy.summary || next.summary,
    details: {
      ...legacy.details,
      ...next.details,
    },
  })
}

function formatAnswerWarning(t: TFunction, warning: string): string {
  const value = warning.trim()
  if (value === 'No source note citation was produced.') {
    return t('answer.warnings.noSourceCitation')
  }
  if (value === 'No authorized knowledge bases are available.') {
    return t('answer.warnings.noAuthorizedInstance')
  }

  const untracedMatch = value.match(/^Citation (.+?) is not fully traced to a source note\.$/)
  if (untracedMatch) {
    return t('answer.warnings.citationUntraced', { id: untracedMatch[1] })
  }

  return warning
}

function formatAnswerWarnings(t: TFunction, warnings: string[]): string {
  return warnings.map((warning) => formatAnswerWarning(t, warning)).join(' · ')
}

function AnswerStepStatusIcon({ status }: { status: string }) {
  if (status === 'completed') return <CheckCircle className="h-4 w-4 text-success" />
  if (status === 'failed') return <XCircle className="h-4 w-4 text-error" />
  if (status === 'running' || status === 'processing') return <Loader2 className="h-4 w-4 animate-spin text-info" />
  return <Clock className="h-4 w-4 text-muted-foreground" />
}

function formatElapsedMs(value: unknown): string {
  if (typeof value !== 'number' || Number.isNaN(value) || value <= 0) return ''
  return value < 1000 ? `${Math.round(value)}ms` : `${(value / 1000).toFixed(1)}s`
}

function formatTokenUsage(value: unknown): string {
  const usage = asRecord(value)
  const prompt = Number(usage.prompt_tokens || 0)
  const completion = Number(usage.completion_tokens || 0)
  if (!prompt && !completion) return ''
  return `${prompt} / ${completion}`
}

function LLMProcessDetails({ item }: { item: ProcessSummary }) {
  const { t } = useTranslation('search')
  const details = asRecord(item.details)

  if (item.step === 'batch_summarization') {
    const batches = asArray(details.batches).map(asRecord)
    if (!batches.length) {
      return <p className="leading-relaxed">{item.summary || t('answer.llmProcess.empty')}</p>
    }
    return (
      <div className="space-y-3">
        {batches.map((batch, index) => {
          const cards = asArray(batch.cards).map(asRecord)
          const keyPoints = asStringArray(batch.key_points)
          const citationIds = asStringArray(batch.citation_ids)
          const fallback = Boolean(batch.fallback)
          const batchStatus = String(batch.status || (batch.summary ? 'completed' : 'processing'))
          const used = batch.used_for_synthesis
          const hasUsedFlag = typeof used === 'boolean'
          const elapsed = formatElapsedMs(batch.elapsed_ms)
          const tokenUsage = formatTokenUsage(batch.token_usage)
          return (
            <div key={`${batch.batch_id || index}`} className="rounded-md border border-border/70 bg-muted/20 p-2">
              <div className="flex flex-wrap items-center gap-2">
                <AnswerStepStatusIcon status={batchStatus} />
                <span className="font-medium text-foreground">{valueLabel(batch.batch_id) || t('answer.llmProcess.batch')}</span>
                <span className="rounded bg-muted px-1.5 py-0.5 text-[11px]">
                  {t('answer.llmProcess.cardsCount', { count: Number(batch.card_count || cards.length) })}
                </span>
                {hasUsedFlag && (
                  <span className={`rounded px-1.5 py-0.5 text-[11px] ${used ? 'bg-success/10 text-success' : 'bg-muted text-muted-foreground'}`}>
                    {used ? t('answer.llmProcess.used') : t('answer.llmProcess.skipped')}
                  </span>
                )}
                {fallback && (
                  <span className="rounded bg-warning/10 px-1.5 py-0.5 text-[11px] text-warning">
                    {t('answer.llmProcess.fallback')}
                  </span>
                )}
                {elapsed && (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[11px]">
                    {t('answer.llmProcess.elapsed')}: {elapsed}
                  </span>
                )}
                {Boolean(batch.model) && (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[11px]">
                    {t('answer.llmProcess.model')}: {String(batch.model)}
                  </span>
                )}
              </div>
              {batchStatus === 'processing' && (
                <p className="mt-2 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {t('answer.llmProcess.processing')}
                </p>
              )}
              {Boolean(batch.error) && (
                <p className="mt-2 rounded bg-warning/10 px-2 py-1 text-[11px] leading-relaxed text-warning">
                  {t('answer.llmProcess.error')}: {String(batch.error)}
                </p>
              )}
              {Boolean(batch.summary) && (
                <div className="mt-2">
                  <p className="text-[11px] font-medium text-muted-foreground">{t('answer.llmProcess.summary')}</p>
                  <p className="mt-1 whitespace-pre-wrap leading-relaxed">{String(batch.summary)}</p>
                </div>
              )}
              {keyPoints.length > 0 && (
                <div className="mt-2">
                  <p className="text-[11px] font-medium text-muted-foreground">{t('answer.llmProcess.keyPoints')}</p>
                  <ul className="mt-1 list-disc space-y-1 pl-4">
                    {keyPoints.map((point, pointIndex) => <li key={pointIndex}>{point}</li>)}
                  </ul>
                </div>
              )}
              {citationIds.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] font-medium text-muted-foreground">{t('answer.llmProcess.citations')}</span>
                  {citationIds.map((id) => (
                    <span key={id} className="rounded bg-primary/10 px-1.5 py-0.5 text-[11px] text-primary">{id}</span>
                  ))}
                </div>
              )}
              {tokenUsage && (
                <p className="mt-2 text-[11px] text-muted-foreground">
                  {t('answer.llmProcess.tokenUsage')}: {tokenUsage}
                </p>
              )}
              {cards.length > 0 && (
                <div className="mt-2 space-y-1">
                  <p className="text-[11px] font-medium text-muted-foreground">{t('answer.llmProcess.cards')}</p>
                  {cards.map((card, cardIndex) => {
                    const cardCitations = asStringArray(card.citation_ids)
                    return (
                      <div key={`${card.path || cardIndex}`} className="rounded border border-border/60 bg-card/70 px-2 py-1">
                        <p className="font-medium text-foreground">{valueLabel(card.title) || t('untitled')}</p>
                        {Boolean(card.path) && <p className="break-all font-mono text-[11px]">{String(card.path)}</p>}
                        {cardCitations.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {cardCitations.map((id) => (
                              <span key={id} className="rounded bg-primary/10 px-1 py-0.5 text-[10px] text-primary">{id}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>
    )
  }

  if (item.step === 'answer_synthesis') {
    const usedBatchIds = asStringArray(details.used_batch_ids)
    const topics = asArray(details.topics).map(asRecord)
    const sectionTitles = asStringArray(details.section_titles)
    const llmNotes = asArray(details.llm_notes).map(asRecord)
    const elapsed = formatElapsedMs(details.elapsed_ms)
    const running = Boolean(details.synthesis_running)
    return (
      <div className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded border border-border/70 bg-muted/20 p-2">
            <p className="text-[11px] text-muted-foreground">{t('answer.llmProcess.usedBatches')}</p>
            <p className="mt-1 font-medium text-foreground">{usedBatchIds.length}</p>
          </div>
          <div className="rounded border border-border/70 bg-muted/20 p-2">
            <p className="text-[11px] text-muted-foreground">{t('answer.llmProcess.topics')}</p>
            <p className="mt-1 font-medium text-foreground">{Number(details.topic_count || topics.length)}</p>
          </div>
          <div className="rounded border border-border/70 bg-muted/20 p-2">
            <p className="text-[11px] text-muted-foreground">{t('answer.llmProcess.sections')}</p>
            <p className="mt-1 font-medium text-foreground">{Number(details.section_count || sectionTitles.length)}</p>
          </div>
          <div className="rounded border border-border/70 bg-muted/20 p-2">
            <p className="text-[11px] text-muted-foreground">
              {details.answer_md_chars !== undefined ? t('answer.llmProcess.reportChars') : t('answer.llmProcess.answerChars')}
            </p>
            <p className="mt-1 font-medium text-foreground">{Number(details.answer_md_chars || details.answer_chars || 0)}</p>
          </div>
        </div>
        {running && (
          <p className="flex items-center gap-1.5 rounded border border-border/70 bg-muted/20 px-2 py-1.5 text-[11px] text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            {t('answer.llmProcess.synthesisRunning')}
          </p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {details.total_cards_summarized !== undefined && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[11px]">
              {t('answer.llmProcess.cardsSummarized')}: {Number(details.total_cards_summarized || 0)}
            </span>
          )}
          {details.section_llm_success !== undefined && (
            <span className="rounded bg-success/10 px-1.5 py-0.5 text-[11px] text-success">
              {t('answer.llmProcess.sectionSuccess')}: {Number(details.section_llm_success || 0)}
            </span>
          )}
          {details.section_content_md_chars !== undefined && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[11px]">
              {t('answer.llmProcess.sectionContentChars')}: {Number(details.section_content_md_chars || 0)}
            </span>
          )}
          {details.section_fallbacks !== undefined && (
            <span className="rounded bg-warning/10 px-1.5 py-0.5 text-[11px] text-warning">
              {t('answer.llmProcess.sectionFallbacks')}: {Number(details.section_fallbacks || 0)}
            </span>
          )}
          {details.overview_fallback !== undefined && Boolean(details.overview_fallback) && (
            <span className="rounded bg-warning/10 px-1.5 py-0.5 text-[11px] text-warning">
              {t('answer.llmProcess.overviewFallback')}
            </span>
          )}
          {elapsed && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[11px]">
              {t('answer.llmProcess.elapsed')}: {elapsed}
            </span>
          )}
          {Boolean(details.model) && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[11px]">
              {t('answer.llmProcess.model')}: {String(details.model)}
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          <span className="text-[11px] font-medium text-muted-foreground">{t('answer.llmProcess.usedBatches')}</span>
          {usedBatchIds.map((id) => (
            <span key={id} className="rounded bg-success/10 px-1.5 py-0.5 text-[11px] text-success">{id}</span>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5">
          <span className="text-[11px] font-medium text-muted-foreground">{t('answer.llmProcess.citations')}</span>
          <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[11px] text-primary">
            {t('answer.llmProcess.traced')}: {Number(details.citations_traced || 0)}
          </span>
          <span className="rounded bg-warning/10 px-1.5 py-0.5 text-[11px] text-warning">
            {t('answer.llmProcess.untraced')}: {Number(details.citations_untraced || 0)}
          </span>
        </div>
        {topics.length > 0 && (
          <div className="space-y-1">
            <p className="text-[11px] font-medium text-muted-foreground">{t('answer.llmProcess.topics')}</p>
            {topics.map((topic, index) => (
              <div key={`${topic.topic || index}`} className="rounded border border-border/70 bg-muted/20 px-2 py-1">
                <p className="font-medium text-foreground">{valueLabel(topic.topic || topic.name) || t('answer.sections.untitled', { index: index + 1 })}</p>
                <p className="mt-0.5 break-all text-[11px]">
                  {asStringArray(topic.batch_ids || topic.related_batches).join(', ')}
                </p>
              </div>
            ))}
          </div>
        )}
        {sectionTitles.length > 0 && (
          <div className="space-y-1">
            <p className="text-[11px] font-medium text-muted-foreground">{t('answer.llmProcess.sections')}</p>
            {sectionTitles.map((title) => (
              <span key={title} className="mr-1.5 inline-block rounded bg-muted px-1.5 py-0.5 text-[11px]">{title}</span>
            ))}
          </div>
        )}
        {llmNotes.length > 0 && (
          <div className="space-y-1">
            <p className="text-[11px] font-medium text-muted-foreground">{t('answer.llmProcess.llmNotes')}</p>
            {llmNotes.map((note, index) => (
              <p key={index} className="whitespace-pre-wrap rounded border border-border/70 bg-muted/20 px-2 py-1 leading-relaxed">
                {valueLabel(note.summary) || valueLabel(note.title)}
              </p>
            ))}
          </div>
        )}
      </div>
    )
  }

  return <p className="whitespace-pre-wrap leading-relaxed">{item.summary || t('answer.llmProcess.empty')}</p>
}

function AnswerProcessPanel({
  steps,
  summaries,
  status,
  error,
  notice,
}: {
  steps: AnswerStep[]
  summaries: ProcessSummary[]
  status: string
  error: string | null
  notice: string | null
}) {
  const summaryByStep = new Map<string, ProcessSummary>()
  for (const summary of summaries) {
    if (!LLM_STEP_NAME_SET.has(summary.step)) continue
    summaryByStep.set(summary.step, summary)
  }

  const systemSteps = SYSTEM_STEP_NAMES.map((name) => {
    const existing = steps.find((step) => step.name === name)
    if (existing) return existing
    const stepIndex = ANSWER_STEP_KEYS.indexOf(name)
    return {
      step: stepIndex >= 0 ? stepIndex + 1 : 99,
      name,
      status: 'pending' as AnswerStep['status'],
      summary: null,
    }
  }).sort((a, b) => a.step - b.step)

  const orderedLLMSteps = LLM_STEP_NAMES.map((name) => {
    const existing = steps.find((step) => step.name === name)
    if (existing) return existing
    const stepIndex = ANSWER_STEP_KEYS.indexOf(name)
    return {
      step: stepIndex >= 0 ? stepIndex + 1 : 99,
      name,
      status: 'pending' as AnswerStep['status'],
      summary: null,
    }
  })

  return (
    <div className="space-y-3">
      <SystemProgressStrip steps={systemSteps} status={status} />

      {orderedLLMSteps.map((step) => (
        <LLMStepCard
          key={step.name}
          step={step}
          summary={summaryByStep.get(step.name) || null}
        />
      ))}

      {notice && (
        <div className="rounded-md bg-warning/10 p-2 text-sm text-warning">
          {notice}
        </div>
      )}
      {error && (
        <div className="rounded-md bg-error/10 p-2 text-sm text-error">
          {error}
        </div>
      )}
    </div>
  )
}

function SystemProgressStrip({
  steps,
  status,
}: {
  steps: AnswerStep[]
  status: string
}) {
  const { t } = useTranslation('search')
  const [open, setOpen] = useState(status !== 'success')

  useEffect(() => {
    queueMicrotask(() => setOpen(status !== 'success'))
  }, [status])

  const visibleSteps = [...steps].sort((a, b) => a.step - b.step)

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <h3 className="flex items-center gap-2 font-medium">
          {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
          <Zap className="h-4 w-4 text-muted-foreground" />
          {t('answer.progressTitle')}
        </h3>
        <span className="text-xs text-muted-foreground">{t(`answer.status.${status}`, { defaultValue: status })}</span>
      </button>

      {open && (
        <div className="mt-3 space-y-1.5">
          {visibleSteps.length === 0 && (
            <p className="rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
              {t('answer.waitingForSteps')}
            </p>
          )}
          {visibleSteps.map((step) => (
            <div key={step.name} className="flex items-center gap-2 px-2 py-1">
              <AnswerStepStatusIcon status={step.status} />
              <span className="text-sm">{t(`answer.steps.${step.name}`, { defaultValue: step.name })}</span>
              <span className="ml-auto text-xs text-muted-foreground">
                {t(`answer.stepStatus.${step.status}`, { defaultValue: step.status })}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function LLMStepCard({
  step,
  summary,
}: {
  step: AnswerStep
  summary: ProcessSummary | null
}) {
  const { t } = useTranslation('search')
  const [detailOpen, setDetailOpen] = useState(false)
  const hasDetails = Boolean(summary)
  const showThought = hasDetails || ['running', 'completed', 'failed'].includes(step.status)

  useEffect(() => {
    if (step.status === 'pending' && !summary) {
      queueMicrotask(() => setDetailOpen(false))
    }
  }, [step.status, summary])

  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex items-center gap-2">
        <AnswerStepStatusIcon status={step.status} />
        <span className="text-sm font-medium">
          {t(`answer.thoughtSteps.${step.name}`, { defaultValue: t(`answer.steps.${step.name}`, { defaultValue: step.name }) })}
        </span>
        <span className="ml-auto text-xs text-muted-foreground">
          {t(`answer.stepStatus.${step.status}`, { defaultValue: step.status })}
        </span>
      </div>

      {showThought && (
        <div className="mt-2 rounded-md border border-border/70">
          <button
            type="button"
            onClick={() => setDetailOpen((prev) => !prev)}
            className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted/50"
          >
            {detailOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            <span className="font-medium">{t('answer.thoughtLabel')}</span>
          </button>
          {detailOpen && (
            <div className="border-t border-border px-2 py-2 text-xs text-muted-foreground">
              {summary ? (
                <LLMProcessDetails item={summary} />
              ) : (
                <p className="flex items-center gap-1.5 leading-relaxed">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {t('answer.llmProcess.waitingThoughtData')}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function sectionStatusClass(status: string): string {
  if (status === 'covered') return 'bg-success/10 text-success'
  if (status === 'partial') return 'bg-warning/10 text-warning'
  if (status === 'untraced') return 'bg-error/10 text-error'
  return 'bg-muted text-muted-foreground'
}

function AnswerSectionsPanel({ sections }: { sections?: AnswerSection[] }) {
  const { t } = useTranslation('search')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const visibleSections = sections || []

  if (!visibleSections.length) return null

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="mt-5 rounded-lg border border-border bg-muted/20 p-3">
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <FileText className="h-3.5 w-3.5" />
        {t('answer.sections.title')}
      </div>
      <div className="mt-3 space-y-2">
        {visibleSections.map((section, index) => {
          const sectionId = section.id || `section-${index + 1}`
          const open = expanded.has(sectionId)
          const keyPoints = section.key_points || []
          const citations = section.citations || []
          const batchIds = section.batch_ids || []
          const cardPaths = section.card_paths || []
          return (
            <div key={sectionId} className="rounded-lg border border-border bg-card">
              <button
                type="button"
                onClick={() => toggle(sectionId)}
                className="flex w-full items-start gap-3 px-3 py-3 text-left hover:bg-muted/40"
              >
                <span className="mt-0.5">
                  {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-foreground">{section.title || t('answer.sections.untitled', { index: index + 1 })}</span>
                    <span className={`rounded px-1.5 py-0.5 text-[11px] ${sectionStatusClass(section.coverage_status)}`}>
                      {t(`answer.sections.status.${section.coverage_status}`, { defaultValue: section.coverage_status })}
                    </span>
                  </span>
                  <span className="mt-1 line-clamp-2 block text-xs leading-5 text-muted-foreground">
                    {section.summary || t('answer.sections.emptySummary')}
                  </span>
                </span>
              </button>

              {open && (
                <div className="space-y-3 border-t border-border px-3 py-3 text-sm">
                  {section.summary && (
                    <p className="whitespace-pre-wrap leading-7 text-foreground">{section.summary}</p>
                  )}

                  {keyPoints.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-muted-foreground">{t('answer.sections.keyPoints')}</p>
                      <ul className="mt-2 list-disc space-y-1 pl-5">
                        {keyPoints.map((point, pointIndex) => <li key={pointIndex}>{point}</li>)}
                      </ul>
                    </div>
                  )}

                  {citations.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-muted-foreground">{t('answer.sections.citations')}</p>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {citations.map((citationId) => (
                          <span key={citationId} className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
                            {citationId}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {batchIds.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-muted-foreground">{t('answer.sections.batches')}</p>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {batchIds.map((batchId) => (
                          <span key={batchId} className="rounded-md border border-border bg-muted/60 px-2 py-1 font-mono text-[11px] text-muted-foreground">
                            {batchId}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {cardPaths.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-muted-foreground">{t('answer.sections.cards')}</p>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {cardPaths.map((cardPath) => (
                          <span key={cardPath} className="max-w-full break-all rounded-md border border-border bg-muted/60 px-2 py-1 font-mono text-[11px] leading-snug text-muted-foreground">
                            {cardPath}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {section.remaining_card_count > 0 && (
                    <p className="rounded-md bg-warning/10 px-2 py-1.5 text-xs text-warning">
                      {t('answer.sections.remaining', { count: section.remaining_card_count })}
                    </p>
                  )}
                  {section.continuation_hint && (
                    <p className="text-xs leading-5 text-muted-foreground">{section.continuation_hint}</p>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function AnswerResultPanel({ answer }: { answer: AnswerResult }) {
  const { t } = useTranslation('search')
  const coverage = answer.coverage_ledger
  const isMarkdown = Boolean(answer.answer_md?.trim())
  const coverageItems = coverage
    ? [
        { key: 'cardsRead', value: coverage.cards_read },
        { key: 'cardsSummarized', value: coverage.cards_summarized },
        { key: 'cardsUsed', value: coverage.cards_used_for_synthesis },
        { key: 'cardsSkipped', value: coverage.cards_skipped_by_budget },
        { key: 'summaryBatches', value: `${coverage.summary_batches_used}/${coverage.summary_batches_total}` },
        { key: 'citationsTraced', value: coverage.citations_traced },
      ]
    : []

  return (
    <div className="rounded-lg border border-primary/20 bg-card p-5">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary" />
        <h3 className="font-medium">{isMarkdown ? t('answer.reportTitle') : t('answer.resultTitle')}</h3>
      </div>

      {coverageItems.length > 0 && (
        <div className="mt-4 rounded-lg border border-border bg-muted/30 p-3">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <BarChart3 className="h-3.5 w-3.5" />
            {t('answer.coverage.title')}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {coverageItems.map((item) => (
              <div key={item.key} className="rounded-md border border-border/70 bg-card px-3 py-2">
                <p className="text-[11px] text-muted-foreground">{t(`answer.coverage.${item.key}`)}</p>
                <p className="mt-1 text-lg font-semibold text-foreground">{item.value}</p>
              </div>
            ))}
          </div>
          {coverage.cards_skipped_by_budget > 0 && (
            <p className="mt-2 text-xs text-warning">
              {t('answer.coverage.skippedHint', { count: coverage.cards_skipped_by_budget })}
            </p>
          )}
        </div>
      )}

      {isMarkdown ? (
        <article className="note-markdown prose prose-sm dark:prose-invert mt-5 max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm, remarkCitationLink]} rehypePlugins={[rehypeHighlight]}>
            {answer.answer_md}
          </ReactMarkdown>
        </article>
      ) : (
        <>
          <div className="mt-4 whitespace-pre-wrap text-sm leading-7 text-foreground">
            {answer.answer || t('answer.emptyAnswer')}
          </div>

          {answer.key_points.length > 0 && (
            <div className="mt-5">
              <p className="text-xs font-medium text-muted-foreground">{t('answer.keyPoints')}</p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
                {answer.key_points.map((point, index) => <li key={index}>{point}</li>)}
              </ul>
            </div>
          )}

          <AnswerSectionsPanel sections={answer.sections} />
        </>
      )}

      {answer.citations.length > 0 && (
        <div className="mt-5">
          <p className="text-xs font-medium text-muted-foreground">{t('answer.citations')}</p>
          <div className="mt-2 space-y-2">
            {answer.citations.map((citation) => (
              <div id={`citation-${citation.id}`} key={citation.id} className="scroll-mt-24 rounded-md border border-border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">{citation.id}</span>
                  <span className="font-medium">{citation.source_title || citation.source_note_path || t('answer.untraced')}</span>
                  {!citation.traced && <span className="rounded bg-warning/10 px-1.5 py-0.5 text-xs text-warning">{t('answer.untraced')}</span>}
                </div>
                {citation.source_note_path && (
                  <p className="mt-1 font-mono text-xs text-muted-foreground">{citation.source_note_path}</p>
                )}
                {citation.evidence_cards.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs font-medium text-muted-foreground">{t('answer.evidenceCards')}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {citation.evidence_cards.map((cardPath) => (
                        <span
                          key={cardPath}
                          className="max-w-full break-all rounded-md border border-border bg-muted/60 px-2 py-1 font-mono text-[11px] leading-snug text-muted-foreground"
                        >
                          {cardPath}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {citation.relation_chain.length > 0 && (
                  <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                    <Link2 className="h-3 w-3" />
                    {citation.relation_chain.join(' -> ')}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {answer.warnings.length > 0 && (
        <div className="mt-4 rounded-md bg-warning/10 p-3 text-xs text-warning">
          {formatAnswerWarnings(t, answer.warnings)}
        </div>
      )}
    </div>
  )
}

const HISTORY_KEY = 'ksm-search-history'
const HISTORY_MAX = 20

function loadHistory(): string[] {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  } catch {
    return []
  }
}

function saveHistory(items: string[]) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(items))
}

export default function SearchPage() {
  const navigate = useNavigate()
  const { instanceId } = useInstanceStore()
  const {
    query,
    searching,
    result,
    activeTab,
    error,
    elapsedMs,
    answerJobId,
    answerStatus,
    answerSteps,
    answerResult,
    answerError,
    answerNotice,
    liveSummaries,
    setQuery,
    setSearching,
    setResult,
    setActiveTab,
    setError,
    setElapsedMs,
    setSearchInstanceId,
    clearForInstance,
    resetSearch,
    resetAnswer,
    setAnswerJobId,
    setAnswerStatus,
    setAnswerSteps,
    setAnswerResult,
    setAnswerError,
    setAnswerNotice,
    setLiveSummaries,
  } = useSearchStore()
  const [history, setHistory] = useState<string[]>(loadHistory)
  const answerTerminalRef = useRef(false)
  const { t } = useTranslation(['search', 'common'])

  useEffect(() => {
    clearForInstance(instanceId)
  }, [clearForInstance, instanceId])

  useEffect(() => {
    answerTerminalRef.current = answerStatus === 'success' || answerStatus === 'failed' || Boolean(answerResult)
  }, [answerStatus, answerResult])

  const handleResetAnswer = useCallback(() => {
    resetAnswer()
    answerTerminalRef.current = false
  }, [resetAnswer])

  const handleClearSearch = useCallback(() => {
    resetSearch()
    answerTerminalRef.current = false
  }, [resetSearch])

  const tabs: { key: TabKey; label: string; icon: typeof FileText }[] = [
    { key: 'core', label: t('tabs.core'), icon: Zap },
    { key: 'related', label: t('tabs.related'), icon: FileText },
    { key: 'source', label: t('tabs.sources'), icon: BookOpen },
    { key: 'map', label: t('tabs.maps'), icon: MapIcon },
  ]

  const addHistory = useCallback((q: string) => {
    setHistory((prev) => {
      const next = [q, ...prev.filter((h) => h !== q)].slice(0, HISTORY_MAX)
      saveHistory(next)
      return next
    })
  }, [])

  const removeHistory = useCallback((q: string) => {
    setHistory((prev) => {
      const next = prev.filter((h) => h !== q)
      saveHistory(next)
      return next
    })
  }, [])

  const runSearch = useCallback(async (rawQuery: string) => {
    const searchQuery = rawQuery.trim()
    if (!searchQuery || !instanceId) return
    addHistory(searchQuery)
    setSearching(true)
    setError(null)
    const start = performance.now()
    try {
      const data = await search(searchQuery, [instanceId])
      setElapsedMs(Math.round(performance.now() - start))
      setSearchInstanceId(instanceId)
      setResult(data)
      setActiveTab('core')
      handleResetAnswer()
    } catch (e) {
      setElapsedMs(Math.round(performance.now() - start))
      setSearchInstanceId(instanceId)
      setError(formatApiError(t, e))
      setResult(null)
      handleResetAnswer()
    }
    setSearching(false)
  }, [instanceId, addHistory, handleResetAnswer, setActiveTab, setElapsedMs, setError, setResult, setSearchInstanceId, setSearching, t])

  const handleSearch = useCallback(async () => {
    await runSearch(query)
  }, [query, runSearch])

  const handleHistoryClick = useCallback((historyQuery: string) => {
    setQuery(historyQuery)
    void runSearch(historyQuery)
  }, [runSearch, setQuery])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch()
  }

  const goToNote = (hit: Record<string, unknown>) => {
    const path = String(hit.path || '')
    if (path) navigate(`/note/${encodeURIComponent(path)}`, {
      state: { returnLabelKey: 'noteDetail:return.search', returnTo: '/search' },
    })
  }

  const handleGenerateAnswer = useCallback(async () => {
    if (!result || !instanceId || answerStatus === 'running' || answerStatus === 'pending') return
    answerTerminalRef.current = false
    setAnswerError(null)
    setAnswerNotice(null)
    setAnswerResult(null)
    setLiveSummaries([])
    setAnswerSteps([])
    setAnswerStatus('pending')
    try {
      const job = await startAnswerJob(result.query || query, [instanceId], {
        include_search_result: false,
        include_comprehension: false,
      })
      setAnswerJobId(job.job_id)
      setAnswerStatus(job.status)
    } catch (e) {
      setAnswerStatus('failed')
      setAnswerError(formatApiError(t, e))
    }
  }, [
    answerStatus,
    instanceId,
    query,
    result,
    setAnswerError,
    setAnswerJobId,
    setAnswerNotice,
    setAnswerResult,
    setAnswerStatus,
    setAnswerSteps,
    setLiveSummaries,
    t,
  ])

  const sseUrl = answerJobId && ACTIVE_ANSWER_STATUSES.has(answerStatus) ? getAnswerJobSSEUrl(answerJobId) : null
  useSSE(sseUrl, {
    resolveUrl: async (url) => {
      if (!answerJobId) return url
      const token = await createAnswerJobSSEToken(answerJobId)
      return token.sse_url
    },
    eventTypes: ['job_start', 'step_update', 'step_output', 'thought_summary', 'job_complete', 'job_failed'],
    onEvent: (event, data) => {
      const payload = data as Record<string, unknown>
      setAnswerNotice(null)
      if (event === 'job_start') {
        setAnswerStatus('running')
        return
      }
      if (event === 'step_update' || event === 'step_output') {
        setAnswerStatus('running')
        setAnswerSteps((prev) => mergeAnswerStep(prev, payload as Partial<AnswerStep>))
        return
      }
      if (event === 'thought_summary') {
        const step = payload as Partial<AnswerStep>
        const name = String(step.name || '')
        const title = t(`answer.steps.${name}`, { defaultValue: name })
        setLiveSummaries((prev) => mergeThoughtSummary(prev, step as AnswerStep, title))
        return
      }
      if (event === 'job_complete') {
        const answer = payload as unknown as AnswerResult
        answerTerminalRef.current = true
        setAnswerResult(answer)
        setAnswerStatus('success')
        setAnswerJobId(null)
        setAnswerError(null)
        setLiveSummaries(answer.process_summaries || [])
        return
      }
      if (event === 'job_failed') {
        answerTerminalRef.current = true
        setAnswerStatus('failed')
        setAnswerJobId(null)
        setAnswerSteps((prev) => prev.map((step) => (
          step.status === 'running' ? { ...step, status: 'failed' } : step
        )))
        setAnswerError(formatAnswerWarning(t, String(payload.error || t('answer.failed'))))
      }
    },
    onError: () => {
      if (answerJobId && ACTIVE_ANSWER_STATUSES.has(answerStatus) && !answerTerminalRef.current) {
        setAnswerNotice(t('answer.sseFallback'))
      }
    },
  })

  useEffect(() => {
    if (!answerJobId || !['pending', 'running'].includes(answerStatus)) return
    const interval = setInterval(async () => {
      try {
        const job = await getAnswerJob(answerJobId)
        setAnswerStatus(job.status)
        setAnswerSteps(job.steps || [])
        if (job.result) {
          answerTerminalRef.current = true
          setAnswerResult(job.result)
          setLiveSummaries(job.result.process_summaries || [])
          setAnswerStatus(job.status === 'failed' ? 'failed' : 'success')
          setAnswerJobId(null)
          setAnswerNotice(null)
          setAnswerError(null)
        }
        if (job.warnings?.length && job.status === 'failed') {
          answerTerminalRef.current = true
          setAnswerJobId(null)
          setAnswerNotice(null)
          setAnswerError(formatAnswerWarnings(t, job.warnings))
        }
      } catch (e) {
        setAnswerError(formatApiError(t, e))
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [
    answerJobId,
    answerStatus,
    setAnswerError,
    setAnswerJobId,
    setAnswerNotice,
    setAnswerResult,
    setAnswerStatus,
    setAnswerSteps,
    setLiveSummaries,
    t,
  ])

  const getHits = (tab: TabKey): Record<string, unknown>[] => {
    if (!result) return []
    switch (tab) {
      case 'core':
        return result.core_hits
      case 'related':
        return result.related_cards
      case 'source':
        return result.source_notes
      case 'map':
        return result.maps
    }
  }

  const tabCounts: Record<TabKey, number> = {
    core: result?.stats.core_count || 0,
    related: result?.stats.related_count || 0,
    source: result?.stats.source_count || 0,
    map: result?.stats.map_count || 0,
  }

  return (
    <div className="max-w-5xl space-y-6">
      <h2 className="text-xl font-semibold">{t('title')}</h2>

      {/* Search input */}
      <div className="flex gap-3">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('placeholder')}
            className="pl-10"
          />
        </div>
        <Button
          onClick={handleSearch}
          disabled={!query.trim() || !instanceId || searching}
        >
          {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          {t('button.search')}
        </Button>
        {(result || error || answerStatus !== 'idle') && (
          <Button variant="secondary" onClick={handleClearSearch}>
            {t('button.clear')}
          </Button>
        )}
      </div>

      {history.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">{t('history.title')}</p>
          <div className="flex flex-wrap gap-2">
            {history.map((h) => (
              <span
                key={h}
                className="flex max-w-full items-center gap-1 rounded bg-muted px-2 py-1 text-xs transition-colors hover:bg-muted/80"
              >
                <button
                  type="button"
                  className="max-w-44 truncate text-left"
                  onClick={() => handleHistoryClick(h)}
                  title={h}
                >
                  {h}
                </button>
                <button
                  type="button"
                  className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
                  aria-label={t('history.deleteLabel', { query: h })}
                  title={t('history.deleteLabel', { query: h })}
                  onClick={(e) => {
                    e.stopPropagation()
                    removeHistory(h)
                  }}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      {!instanceId && (
        <p className="text-sm text-muted-foreground">{t('common:selectInstance')}</p>
      )}

      {error && (
        <div className="p-3 bg-error/10 text-error rounded-md text-sm">{error}</div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4">
          <StatsBar stats={result.stats} intentType={result.intent_type} elapsedMs={elapsedMs} mapPriority={result.map_priority} />
          <SearchContextPanel result={result} />

          <div className="rounded-lg border border-border bg-card p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="flex items-center gap-2 font-medium">
                  <Sparkles className="h-4 w-4 text-primary" />
                  {t('answer.actionTitle')}
                </h3>
                <p className="mt-1 text-sm text-muted-foreground">{t('answer.actionDescription')}</p>
              </div>
              <div className="flex gap-2">
                {answerResult && (
                  <Button variant="secondary" onClick={handleResetAnswer}>
                    {t('answer.reset')}
                  </Button>
                )}
                <Button
                  onClick={handleGenerateAnswer}
                  disabled={!instanceId || answerStatus === 'pending' || answerStatus === 'running'}
                >
                  {answerStatus === 'pending' || answerStatus === 'running'
                    ? <Loader2 className="h-4 w-4 animate-spin" />
                    : <Sparkles className="h-4 w-4" />}
                  {answerResult ? t('answer.regenerate') : t('answer.generate')}
                </Button>
              </div>
            </div>
          </div>

          {(answerStatus !== 'idle' || liveSummaries.length > 0) && (
            <AnswerProcessPanel
              steps={answerSteps}
              summaries={liveSummaries}
              status={answerStatus}
              error={answerError}
              notice={answerNotice}
            />
          )}

          {answerResult && <AnswerResultPanel answer={answerResult} />}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Main results area */}
            <div className="lg:col-span-2 space-y-4">
              <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as TabKey)}>
                <TabsList variant="line">
                  {tabs.map((tab) => (
                    <TabsTrigger key={tab.key} value={tab.key}>
                      <tab.icon className="w-3.5 h-3.5" />
                      {tab.label}
                      <span className="text-[10px] bg-muted px-1.5 py-0.5 rounded-full font-mono">
                        {tabCounts[tab.key]}
                      </span>
                    </TabsTrigger>
                  ))}
                </TabsList>
                {tabs.map((tab) => (
                  <TabsContent key={tab.key} value={tab.key}>
                    <div className="space-y-3">
                      {getHits(tab.key).length === 0 ? (
                        <p className="text-sm text-muted-foreground text-center py-8">
                          {t('noResults', { type: tab.label.toLowerCase() })}
                        </p>
                      ) : (
                        getHits(tab.key).map((hit, i) => (
                          <ResultCard key={i} hit={hit} onClick={() => goToNote(hit)} />
                        ))
                      )}
                    </div>
                  </TabsContent>
                ))}
              </Tabs>
            </div>

            {/* Comprehension sidebar */}
            <div className="space-y-4">
              {result.comprehension && <ComprehensionPanel data={result.comprehension as unknown as Record<string, unknown>} />}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
