import { cn } from '@/lib/utils'
import { formatGraphLayer } from '@/lib/i18nFormat'
import { useTranslation } from 'react-i18next'

const layerColors: Record<number, string> = {
  1: '#3b82f6',
  2: '#8b5cf6',
  3: '#f59e0b',
}

export function LayerBadge({
  layer,
  className,
}: {
  layer: number
  className?: string
}) {
  const { t } = useTranslation('common')
  const color = layerColors[layer] || '#6b7280'

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 text-xs px-1.5 py-0.5 rounded font-mono',
        className
      )}
      style={{ backgroundColor: color + '20', color }}
    >
      <span
        className="w-2 h-2 rounded-full"
        style={{ backgroundColor: color }}
      />
      {formatGraphLayer(t, layer) || `L${layer}`}
    </span>
  )
}
