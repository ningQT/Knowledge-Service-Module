import { useState, useCallback, useEffect, useRef } from 'react'
import { Upload, FileText, Loader2, StopCircle } from 'lucide-react'
import { useInstanceStore } from '@/stores/useInstanceStore'
import { useIngestStore } from '@/stores/useIngestStore'
import { useSSE } from '@/hooks/useSSE'
import { ingestAsync, getJob, getJobSSEUrl, createJobSSEToken, cancelJob } from '@/services/ingest'
import { getInstance } from '@/services/instances'
import { StepProgress } from '@/components/shared/StepProgress'
import type { IngestStep, Instance } from '@/types/api'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { formatApiError, formatJobStatus } from '@/lib/i18nFormat'
import { useTranslation } from 'react-i18next'

export default function IngestPage() {
  const { instanceId } = useInstanceStore()
  const [currentInstance, setCurrentInstance] = useState<Instance | null>(null)

  useEffect(() => {
    let cancelled = false
    if (!instanceId) {
      queueMicrotask(() => {
        if (!cancelled) setCurrentInstance(null)
      })
      return () => { cancelled = true }
    }
    getInstance(instanceId).then(setCurrentInstance).catch(() => setCurrentInstance(null))
    return () => { cancelled = true }
  }, [instanceId])
  const { currentJobId, status, steps, result, setJobId, updateStep, setResult, cancel, reset } = useIngestStore()
  const [file, setFile] = useState<File | null>(null)
  const [domainHint, setDomainHint] = useState('')
  const [autoMap, setAutoMap] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const { t } = useTranslation('ingest')
  // S-04: SSE 轮询回退机制
  const [polling, setPolling] = useState(false)
  const pollingRef = useRef(false)
  const uploadDisabled = !instanceId || submitting || status === 'running'

  const sseUrl = currentJobId && instanceId ? getJobSSEUrl(instanceId, currentJobId) : null

  useSSE(sseUrl, {
    resolveUrl: async (url) => {
      if (!currentJobId || !instanceId) return url
      const token = await createJobSSEToken(instanceId, currentJobId)
      return token.sse_url
    },
    eventTypes: ['step_update', 'step_output', 'job_complete', 'job_start', 'job_cancelled'],
    onEvent: (event: string, data: unknown) => {
      const d = data as { step?: number; status?: string; summary?: Record<string, unknown> }
      if (event === 'step_update' || event === 'step_output') {
        if (d.step && d.status) updateStep(d.step, d.status, d.summary)
      } else if (event === 'job_cancelled') {
        cancel()
        setFile(null)
      } else if (event === 'job_complete') {
        setResult(data as { status: string; created_files: string[]; generated_cards: string[]; generated_maps: string[]; warnings: string[] })
      }
    },
    onError: () => {
      // SSE 连接失败，切换到轮询回退（设计文档 §4.7.3 功能 #8）
      if (currentJobId && instanceId && status === 'running') {
        pollingRef.current = true
        setPolling(true)
      }
    },
  })

  // S-04: 轮询回退逻辑
  useEffect(() => {
    if (!polling || !currentJobId || !instanceId) return

    const interval = setInterval(async () => {
      try {
        const job = await getJob(instanceId, currentJobId)

        // 更新步骤状态
        for (const step of job.steps) {
          if (step.status === 'completed' || step.status === 'failed') {
            updateStep(step.step, step.status, step.summary)
          }
        }

        // 检查是否完成
        if (job.status === 'cancelled') {
          cancel()
          setFile(null)
          pollingRef.current = false
          setPolling(false)
        } else if (job.status === 'success' || job.status === 'partial_failed' || job.status === 'failed') {
          setResult({
            status: job.status,
            created_files: job.created_files,
            generated_cards: job.generated_cards,
            generated_maps: job.generated_maps,
            warnings: job.warnings,
          })
          pollingRef.current = false
          setPolling(false)
        }
      } catch (e) {
        console.error('Polling failed:', e)
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [polling, currentJobId, instanceId, updateStep, setResult, cancel])

  const handleSubmit = useCallback(async () => {
    if (!file || !instanceId) return
    setSubmitting(true)
    setError(null)
    try {
      const { job_id } = await ingestAsync(instanceId, file, {
        domain_hint: domainHint || undefined,
        auto_map: autoMap,
      })
      setJobId(job_id)
    } catch (e) {
      setError(formatApiError(t, e))
    }
    setSubmitting(false)
  }, [file, instanceId, domainHint, autoMap, setJobId, t])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    if (uploadDisabled) return
    const droppedFile = e.dataTransfer.files[0]
    if (droppedFile?.name.endsWith('.md')) {
      setFile(droppedFile)
    }
  }, [uploadDisabled])

  const handleCancel = useCallback(async () => {
    if (!currentJobId || !instanceId) return
    setCancelling(true)
    try {
      await cancelJob(instanceId, currentJobId)
      cancel()
      setFile(null)
    } catch (e) {
      console.error('Cancel failed:', e)
    }
    setCancelling(false)
    setCancelOpen(false)
  }, [currentJobId, instanceId, cancel])

  return (
    <div className="max-w-4xl space-y-6">
      <h2 className="text-xl font-semibold">{t('title')}</h2>

      <div className="flex items-center gap-2 text-sm">
        <span className="font-medium">{t('instance.current')}:</span>
        {currentInstance ? (
          <span className="text-primary">{currentInstance.name}</span>
        ) : (
          <span className="text-warning">{t('instance.noInstance')}</span>
        )}
        <span className="text-xs text-muted-foreground">({t('instance.switchHint')})</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Upload section */}
        <div className="space-y-4">
          <div
            className={`border-2 border-dashed border-border rounded-lg p-8 text-center transition-colors ${
              uploadDisabled
                ? 'opacity-60 cursor-not-allowed bg-muted/30'
                : 'hover:border-primary cursor-pointer'
            }`}
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
            onClick={() => {
              if (!uploadDisabled) document.getElementById('file-input')?.click()
            }}
          >
            <input
              id="file-input"
              type="file"
              accept=".md"
              className="hidden"
              disabled={uploadDisabled}
              onChange={(e) => {
                if (!uploadDisabled) setFile(e.target.files?.[0] || null)
              }}
            />
            {file ? (
              <div className="flex items-center justify-center gap-2">
                <FileText className="w-8 h-8 text-primary" />
                <span className="text-sm">{file.name}</span>
              </div>
            ) : (
              <div>
                <Upload className="w-8 h-8 mx-auto text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">
                  {t('upload.hint')}
                </p>
              </div>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">{t('form.domain')}</label>
            <Input
              value={domainHint}
              onChange={(e) => setDomainHint(e.target.value)}
              placeholder={t('form.domainPlaceholder')}
            />
          </div>

          <div className="flex items-center gap-2">
            <Switch
              id="auto-map"
              checked={autoMap}
              onCheckedChange={setAutoMap}
            />
            <label htmlFor="auto-map" className="text-sm">
              {t('form.autoMap')}
            </label>
          </div>

          <Button
            onClick={handleSubmit}
            disabled={!file || !instanceId || submitting || status === 'running'}
            className="w-full"
          >
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
            {t('action.startIngest')}
          </Button>

          {status === 'running' && (
            <Button
              onClick={() => setCancelOpen(true)}
              variant="destructive"
              className="w-full"
            >
              <StopCircle className="w-4 h-4" />
              {t('action.cancelIngest')}
            </Button>
          )}

          {error && (
            <div className="p-3 bg-error/10 text-error rounded-md text-sm">{error}</div>
          )}
        </div>

        {/* Progress section */}
        <div className="bg-card rounded-lg border border-border p-4">
          <h3 className="font-medium mb-3">{t('progress.title')}</h3>
          {status === 'idle' ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              {t('progress.idle')}
            </p>
          ) : (
            <div className="space-y-1">
              {steps.map((step: IngestStep) => (
                <StepProgress key={step.step} step={step} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Cancel confirmation dialog */}
      <Dialog open={cancelOpen} onOpenChange={setCancelOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('cancelDialog.title')}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground py-2">
            {t('cancelDialog.description')}
          </p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCancelOpen(false)}>
              {t('cancelDialog.dismiss')}
            </Button>
            <Button variant="destructive" onClick={handleCancel} disabled={cancelling}>
              {cancelling && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
              {t('cancelDialog.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Results */}
      {result && (
        <div className="bg-card rounded-lg border border-border p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-medium">{t('output.title')}</h3>
            <span className={`text-xs px-2 py-0.5 rounded ${
              result.status === 'failed'
                ? 'bg-error/10 text-error'
                : result.status === 'partial_failed'
                  ? 'bg-warning/10 text-warning'
                  : result.status === 'cancelled'
                    ? 'bg-muted text-muted-foreground'
                    : 'bg-success/10 text-success'
            }`}>
              {formatJobStatus(t, result.status)}
            </span>
          </div>
          <div className="space-y-1">
            {result.created_files.map((f: string, i: number) => (
              <div key={i} className="flex items-center gap-2 text-sm py-1">
                <FileText className="w-4 h-4 text-muted-foreground" />
                <span className="font-mono text-xs">{f}</span>
              </div>
            ))}
          </div>
          {result.warnings.length > 0 && (
            <div className="mt-3 p-2 bg-warning/10 rounded text-sm text-warning">
              {result.warnings.map((w: string, i: number) => (
                <p key={i}>{w}</p>
              ))}
            </div>
          )}
          <Button
            onClick={() => {
              reset()
              setFile(null)
            }}
            variant="ghost"
            className="mt-4"
          >
            {t('action.reset')}
          </Button>
        </div>
      )}
    </div>
  )
}
