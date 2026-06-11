import { Clock, Loader2, CheckCircle, XCircle } from 'lucide-react'
import type { IngestStep } from '@/types/api'
import { formatJobStatus } from '@/lib/i18nFormat'
import { useTranslation } from 'react-i18next'

const statusColors: Record<string, string> = {
  pending: 'bg-muted',
  running: 'bg-info animate-pulse',
  completed: 'bg-success',
  failed: 'bg-error',
}

const statusIcons: Record<string, React.ReactNode> = {
  pending: <Clock className="w-4 h-4 text-muted-foreground" />,
  running: <Loader2 className="w-4 h-4 text-info animate-spin" />,
  completed: <CheckCircle className="w-4 h-4 text-success" />,
  failed: <XCircle className="w-4 h-4 text-error" />,
}

export function StepProgress({ step }: { step: IngestStep }) {
  const { t } = useTranslation('ingest')

  return (
    <div className="flex items-start gap-3 py-2">
      <div className="mt-0.5">{statusIcons[step.status]}</div>
      <div className="flex-1">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">
            {t('progress.step', { step: step.step })}: {t(`steps.step${step.step}`)}
          </span>
          <span className="text-xs text-muted-foreground capitalize">{formatJobStatus(t, step.status)}</span>
        </div>
        <div className="mt-1 h-1.5 bg-muted rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${statusColors[step.status]}`}
            style={{
              width: step.status === 'completed' ? '100%' : step.status === 'running' ? '60%' : '0%',
            }}
          />
        </div>
        {step.summary && (
          <p className="text-xs text-muted-foreground mt-1">
            {Object.entries(step.summary)
              .filter(([, v]) => v !== null && v !== undefined)
              .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
              .join(' · ')}
          </p>
        )}
      </div>
    </div>
  )
}
