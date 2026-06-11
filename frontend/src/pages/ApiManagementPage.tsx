import { useMemo, useState } from 'react'
import { BookOpen, Braces, CheckCircle2, Copy, Database, KeyRound, ListChecks, LockKeyhole, Search, UploadCloud } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ApiKeyManager, type ApiKeyManagerSummary } from '@/components/shared/ApiKeyManager'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

type ApiScope = 'read' | 'write'
type ApiMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE'

interface ApiEndpoint {
  method: ApiMethod
  path: string
  scope: ApiScope
  titleKey: string
  descriptionKey: string
  detailKey: string
  example: string
  recommended?: boolean
}

interface EndpointGroup {
  key: string
  icon: typeof Search
  endpoints: ApiEndpoint[]
}

const EMPTY_SUMMARY: ApiKeyManagerSummary = {
  totalKeys: 0,
  enabledKeys: 0,
  readKeys: 0,
  writeKeys: 0,
  instanceCount: 0,
  authorizedInstanceCount: 0,
  lastUsedAt: null,
}

const endpointGroups: EndpointGroup[] = [
  {
    key: 'search',
    icon: Search,
    endpoints: [
      {
        method: 'POST',
        path: '/api/v1/search',
        scope: 'read',
        titleKey: 'endpoints.search.title',
        descriptionKey: 'endpoints.search.description',
        detailKey: 'endpoints.search.detail',
        recommended: true,
        example: `curl -X POST "$KSM_BASE_URL/search" \\
  -H "Authorization: Bearer $KSM_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"query":"What does this knowledge base know about onboarding?","instance_ids":["inst_xxx"],"include_comprehension":true}'`,
      },
      {
        method: 'POST',
        path: '/api/v1/search/answer',
        scope: 'read',
        titleKey: 'endpoints.searchAnswer.title',
        descriptionKey: 'endpoints.searchAnswer.description',
        detailKey: 'endpoints.searchAnswer.detail',
        recommended: true,
        example: `curl -X POST "$KSM_BASE_URL/search/answer" \\
  -H "Authorization: Bearer $KSM_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"query":"Summarize onboarding knowledge","instance_ids":["inst_xxx"],"include_search_result":false,"include_comprehension":false}'`,
      },
      {
        method: 'POST',
        path: '/api/v1/search/answer-jobs',
        scope: 'read',
        titleKey: 'endpoints.searchAnswerJob.title',
        descriptionKey: 'endpoints.searchAnswerJob.description',
        detailKey: 'endpoints.searchAnswerJob.detail',
        example: `curl -X POST "$KSM_BASE_URL/search/answer-jobs" \\
  -H "Authorization: Bearer $KSM_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"query":"Summarize onboarding knowledge","instance_ids":["inst_xxx"]}'`,
      },
      {
        method: 'GET',
        path: '/api/v1/search/answer-jobs/{job_id}',
        scope: 'read',
        titleKey: 'endpoints.searchAnswerJobStatus.title',
        descriptionKey: 'endpoints.searchAnswerJobStatus.description',
        detailKey: 'endpoints.searchAnswerJobStatus.detail',
        example: `curl "$KSM_BASE_URL/search/answer-jobs/answer_20260510_abcdef" \\
  -H "Authorization: Bearer $KSM_API_KEY"`,
      },
      {
        method: 'GET',
        path: '/api/v1/search/answer-jobs/{job_id}/sse',
        scope: 'read',
        titleKey: 'endpoints.searchAnswerJobSse.title',
        descriptionKey: 'endpoints.searchAnswerJobSse.description',
        detailKey: 'endpoints.searchAnswerJobSse.detail',
        example: `# Browser clients first exchange a short-lived one-time SSE token:
curl -X POST "$KSM_BASE_URL/search/answer-jobs/answer_20260510_abcdef/sse-token" \\
  -H "Authorization: Bearer $KSM_API_KEY"

curl -N "$KSM_BASE_URL/search/answer-jobs/answer_20260510_abcdef/sse?sse_token=$KSM_SSE_TOKEN"`,
      },
    ],
  },
  {
    key: 'instances',
    icon: Database,
    endpoints: [
      {
        method: 'GET',
        path: '/api/v1/instances',
        scope: 'read',
        titleKey: 'endpoints.instanceList.title',
        descriptionKey: 'endpoints.instanceList.description',
        detailKey: 'endpoints.instanceList.detail',
        example: `curl "$KSM_BASE_URL/instances" \\
  -H "Authorization: Bearer $KSM_API_KEY"`,
      },
      {
        method: 'GET',
        path: '/api/v1/instances/{instance_id}',
        scope: 'read',
        titleKey: 'endpoints.instanceDetail.title',
        descriptionKey: 'endpoints.instanceDetail.description',
        detailKey: 'endpoints.instanceDetail.detail',
        example: `curl "$KSM_BASE_URL/instances/inst_xxx" \\
  -H "Authorization: Bearer $KSM_API_KEY"`,
      },
      {
        method: 'GET',
        path: '/api/v1/instances/{instance_id}/stats',
        scope: 'read',
        titleKey: 'endpoints.instanceStats.title',
        descriptionKey: 'endpoints.instanceStats.description',
        detailKey: 'endpoints.instanceStats.detail',
        example: `curl "$KSM_BASE_URL/instances/inst_xxx/stats" \\
  -H "Authorization: Bearer $KSM_API_KEY"`,
      },
    ],
  },
  {
    key: 'notes',
    icon: BookOpen,
    endpoints: [
      {
        method: 'GET',
        path: '/api/v1/instances/{instance_id}/notes',
        scope: 'read',
        titleKey: 'endpoints.noteList.title',
        descriptionKey: 'endpoints.noteList.description',
        detailKey: 'endpoints.noteList.detail',
        example: `curl "$KSM_BASE_URL/instances/inst_xxx/notes?verification=verified&q=pricing" \\
  -H "Authorization: Bearer $KSM_API_KEY"`,
      },
      {
        method: 'GET',
        path: '/api/v1/instances/{instance_id}/notes/facets',
        scope: 'read',
        titleKey: 'endpoints.noteFacets.title',
        descriptionKey: 'endpoints.noteFacets.description',
        detailKey: 'endpoints.noteFacets.detail',
        example: `curl "$KSM_BASE_URL/instances/inst_xxx/notes/facets" \\
  -H "Authorization: Bearer $KSM_API_KEY"`,
      },
      {
        method: 'GET',
        path: '/api/v1/instances/{instance_id}/notes/{path}',
        scope: 'read',
        titleKey: 'endpoints.noteDetail.title',
        descriptionKey: 'endpoints.noteDetail.description',
        detailKey: 'endpoints.noteDetail.detail',
        example: `curl "$KSM_BASE_URL/instances/inst_xxx/notes/03-%E7%9F%A5%E8%AF%86%E5%9C%B0%E5%9B%BE/example.md" \\
  -H "Authorization: Bearer $KSM_API_KEY"`,
      },
      {
        method: 'PATCH',
        path: '/api/v1/instances/{instance_id}/notes/{path}/verification',
        scope: 'write',
        titleKey: 'endpoints.noteVerification.title',
        descriptionKey: 'endpoints.noteVerification.description',
        detailKey: 'endpoints.noteVerification.detail',
        example: `curl -X PATCH "$KSM_BASE_URL/instances/inst_xxx/notes/path/to/note.md/verification" \\
  -H "Authorization: Bearer $KSM_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"verification":"verified"}'`,
      },
      {
        method: 'PATCH',
        path: '/api/v1/instances/{instance_id}/notes/{path}/metadata',
        scope: 'write',
        titleKey: 'endpoints.noteMetadata.title',
        descriptionKey: 'endpoints.noteMetadata.description',
        detailKey: 'endpoints.noteMetadata.detail',
        example: `curl -X PATCH "$KSM_BASE_URL/instances/inst_xxx/notes/path/to/note.md/metadata" \\
  -H "Authorization: Bearer $KSM_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"domain":"客户服务","kind":"流程说明","verification":"verified"}'`,
      },
      {
        method: 'DELETE',
        path: '/api/v1/instances/{instance_id}/notes/{path}',
        scope: 'write',
        titleKey: 'endpoints.noteDelete.title',
        descriptionKey: 'endpoints.noteDelete.description',
        detailKey: 'endpoints.noteDelete.detail',
        example: `curl -X DELETE "$KSM_BASE_URL/instances/inst_xxx/notes/path/to/note.md" \\
  -H "Authorization: Bearer $KSM_API_KEY"`,
      },
    ],
  },
  {
    key: 'graph',
    icon: Braces,
    endpoints: [
      {
        method: 'GET',
        path: '/api/v1/instances/{instance_id}/graph',
        scope: 'read',
        titleKey: 'endpoints.graph.title',
        descriptionKey: 'endpoints.graph.description',
        detailKey: 'endpoints.graph.detail',
        example: `curl "$KSM_BASE_URL/instances/inst_xxx/graph?include_unresolved=true" \\
  -H "Authorization: Bearer $KSM_API_KEY"`,
      },
    ],
  },
  {
    key: 'ingest',
    icon: UploadCloud,
    endpoints: [
      {
        method: 'POST',
        path: '/api/v1/instances/{instance_id}/ingest',
        scope: 'write',
        titleKey: 'endpoints.ingest.title',
        descriptionKey: 'endpoints.ingest.description',
        detailKey: 'endpoints.ingest.detail',
        example: `curl -X POST "$KSM_BASE_URL/instances/inst_xxx/ingest" \\
  -H "Authorization: Bearer $KSM_API_KEY" \\
  -F "file=@brief.md" \\
  -F "domain_hint=客户服务" \\
  -F "auto_map=true"`,
      },
      {
        method: 'POST',
        path: '/api/v1/instances/{instance_id}/ingest/async',
        scope: 'write',
        titleKey: 'endpoints.ingestAsync.title',
        descriptionKey: 'endpoints.ingestAsync.description',
        detailKey: 'endpoints.ingestAsync.detail',
        recommended: true,
        example: `curl -X POST "$KSM_BASE_URL/instances/inst_xxx/ingest/async" \\
  -H "Authorization: Bearer $KSM_API_KEY" \\
  -F "file=@brief.md"`,
      },
      {
        method: 'GET',
        path: '/api/v1/instances/{instance_id}/ingest/jobs/{job_id}',
        scope: 'read',
        titleKey: 'endpoints.jobStatus.title',
        descriptionKey: 'endpoints.jobStatus.description',
        detailKey: 'endpoints.jobStatus.detail',
        example: `curl "$KSM_BASE_URL/instances/inst_xxx/ingest/jobs/job_20260510_abcdef" \\
  -H "Authorization: Bearer $KSM_API_KEY"`,
      },
      {
        method: 'GET',
        path: '/api/v1/instances/{instance_id}/ingest/jobs/{job_id}/sse',
        scope: 'read',
        titleKey: 'endpoints.jobSse.title',
        descriptionKey: 'endpoints.jobSse.description',
        detailKey: 'endpoints.jobSse.detail',
        example: `# Browser clients first exchange a short-lived one-time SSE token:
curl -X POST "$KSM_BASE_URL/instances/inst_xxx/ingest/jobs/job_20260510_abcdef/sse-token" \\
  -H "Authorization: Bearer $KSM_API_KEY"

curl -N "$KSM_BASE_URL/instances/inst_xxx/ingest/jobs/job_20260510_abcdef/sse?sse_token=$KSM_SSE_TOKEN"`,
      },
      {
        method: 'POST',
        path: '/api/v1/instances/{instance_id}/ingest/jobs/{job_id}/cancel',
        scope: 'write',
        titleKey: 'endpoints.jobCancel.title',
        descriptionKey: 'endpoints.jobCancel.description',
        detailKey: 'endpoints.jobCancel.detail',
        example: `curl -X POST "$KSM_BASE_URL/instances/inst_xxx/ingest/jobs/job_20260510_abcdef/cancel" \\
  -H "Authorization: Bearer $KSM_API_KEY"`,
      },
    ],
  },
  {
    key: 'maintenance',
    icon: ListChecks,
    endpoints: [
      {
        method: 'POST',
        path: '/api/v1/instances/{instance_id}/sync',
        scope: 'write',
        titleKey: 'endpoints.sync.title',
        descriptionKey: 'endpoints.sync.description',
        detailKey: 'endpoints.sync.detail',
        example: `curl -X POST "$KSM_BASE_URL/instances/inst_xxx/sync?git=false" \\
  -H "Authorization: Bearer $KSM_API_KEY"`,
      },
      {
        method: 'POST',
        path: '/api/v1/instances/{instance_id}/reindex',
        scope: 'write',
        titleKey: 'endpoints.reindex.title',
        descriptionKey: 'endpoints.reindex.description',
        detailKey: 'endpoints.reindex.detail',
        example: `curl -X POST "$KSM_BASE_URL/instances/inst_xxx/reindex" \\
  -H "Authorization: Bearer $KSM_API_KEY"`,
      },
    ],
  },
]

const methodStyles: Record<ApiMethod, string> = {
  GET: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  POST: 'border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300',
  PATCH: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  DELETE: 'border-destructive/30 bg-destructive/10 text-destructive',
}

function StatCard({ label, value, helper }: { label: string; value: string | number; helper?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-foreground">{value}</div>
      {helper && <div className="mt-1 text-xs text-muted-foreground">{helper}</div>}
    </div>
  )
}

export default function ApiManagementPage() {
  const { t } = useTranslation('apiManagement')
  const [summary, setSummary] = useState<ApiKeyManagerSummary>(EMPTY_SUMMARY)

  const baseUrl = useMemo(() => {
    if (typeof window === 'undefined') return '/api/v1'
    return `${window.location.origin}/api/v1`
  }, [])

  const lastUsed = summary.lastUsedAt
    ? new Date(summary.lastUsedAt).toLocaleString()
    : t('overview.neverUsed')

  async function copyBaseUrl() {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(baseUrl)
    }
  }

  return (
    <div className="max-w-6xl space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-xl font-semibold">{t('title')}</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t('description')}</p>
        </div>
        <Badge variant="outline" className="w-fit">
          <LockKeyhole className="h-3 w-3" />
          {t('auth.apiKeyOnly')}
        </Badge>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <StatCard
          label={t('overview.enabledKeys')}
          value={`${summary.enabledKeys}/${summary.totalKeys}`}
          helper={t('overview.keysHelper', { read: summary.readKeys, write: summary.writeKeys })}
        />
        <StatCard
          label={t('overview.authorizedInstances')}
          value={`${summary.authorizedInstanceCount}/${summary.instanceCount}`}
          helper={t('overview.authorizedHelper')}
        />
        <StatCard
          label={t('overview.lastUsed')}
          value={lastUsed}
          helper={t('overview.lastUsedHelper')}
        />
      </div>

      <div className="rounded-lg border border-border bg-card p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/10 text-primary">
              <KeyRound className="h-4 w-4" />
            </div>
            <div>
              <h3 className="font-medium">{t('auth.title')}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{t('auth.description')}</p>
            </div>
          </div>
          <div className="flex min-w-0 items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2">
            <code className="min-w-0 truncate text-xs">{baseUrl}</code>
            <Button variant="secondary" size="icon-sm" onClick={copyBaseUrl} title={t('overview.copyBaseUrl')}>
              <Copy className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <div className="rounded-md border border-border p-3 text-sm">
            <div className="font-medium">{t('auth.headerTitle')}</div>
            <code className="mt-2 block truncate rounded bg-muted px-2 py-1 text-xs">
              Authorization: Bearer $KSM_API_KEY
            </code>
          </div>
          <div className="rounded-md border border-border p-3 text-sm">
            <div className="font-medium">{t('auth.readTitle')}</div>
            <p className="mt-1 text-muted-foreground">{t('auth.readDescription')}</p>
          </div>
          <div className="rounded-md border border-border p-3 text-sm">
            <div className="font-medium">{t('auth.writeTitle')}</div>
            <p className="mt-1 text-muted-foreground">{t('auth.writeDescription')}</p>
          </div>
        </div>
      </div>

      <ApiKeyManager onSummaryChange={setSummary} />

      <section className="rounded-lg border border-border bg-card p-6">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/10 text-primary">
            <CheckCircle2 className="h-4 w-4" />
          </div>
          <div>
            <h3 className="font-medium">{t('quickStart.title')}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{t('quickStart.description')}</p>
          </div>
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-5">
          {['createKey', 'grant', 'search', 'read', 'write'].map((step, index) => (
            <div key={step} className="rounded-md border border-border p-3">
              <div className="mb-2 flex h-6 w-6 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                {index + 1}
              </div>
              <div className="text-sm font-medium">{t(`quickStart.steps.${step}.title`)}</div>
              <p className="mt-1 text-xs text-muted-foreground">{t(`quickStart.steps.${step}.description`)}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <div>
          <h3 className="font-medium">{t('catalog.title')}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{t('catalog.description')}</p>
        </div>

        {endpointGroups.map((group) => {
          const Icon = group.icon
          return (
            <div key={group.key} className="rounded-lg border border-border bg-card p-5">
              <div className="mb-4 flex items-center gap-2">
                <Icon className="h-4 w-4 text-primary" />
                <h4 className="font-medium">{t(`groups.${group.key}`)}</h4>
              </div>
              <div className="space-y-3">
                {group.endpoints.map((endpoint) => (
                  <details key={`${endpoint.method}-${endpoint.path}`} className="group rounded-md border border-border">
                    <summary className="flex cursor-pointer list-none flex-col gap-3 px-4 py-3 md:flex-row md:items-center md:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className={`rounded border px-2 py-0.5 font-mono text-xs font-semibold ${methodStyles[endpoint.method]}`}>
                            {endpoint.method}
                          </span>
                          <code className="break-all text-sm">{endpoint.path}</code>
                          <Badge variant={endpoint.scope === 'write' ? 'secondary' : 'outline'}>
                            {t(`scope.${endpoint.scope}`)}
                          </Badge>
                          {endpoint.recommended && <Badge>{t('catalog.recommended')}</Badge>}
                        </div>
                        <div className="mt-2 text-sm font-medium">{t(endpoint.titleKey)}</div>
                        <p className="mt-1 text-sm text-muted-foreground">{t(endpoint.descriptionKey)}</p>
                      </div>
                      <span className="text-xs text-muted-foreground group-open:hidden">{t('catalog.expand')}</span>
                    </summary>
                    <div className="border-t border-border px-4 py-4">
                      <div className="grid gap-4 lg:grid-cols-[1fr_1.15fr]">
                        <div className="space-y-3 text-sm">
                          <div>
                            <div className="font-medium">{t('catalog.details')}</div>
                            <p className="mt-1 text-muted-foreground">{t(endpoint.detailKey)}</p>
                          </div>
                          <div>
                            <div className="font-medium">{t('catalog.errors')}</div>
                            <p className="mt-1 text-muted-foreground">{t('catalog.errorDescription')}</p>
                          </div>
                        </div>
                        <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs text-muted-foreground">
                          <code>{endpoint.example}</code>
                        </pre>
                      </div>
                    </div>
                  </details>
                ))}
              </div>
            </div>
          )
        })}
      </section>
    </div>
  )
}
