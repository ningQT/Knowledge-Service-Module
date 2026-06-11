import { useTranslation } from 'react-i18next'

export function EmptyState({ title, description }: { title?: string; description?: string }) {
  const { t } = useTranslation('common')
  const displayTitle = title ?? t('noData')

  return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center">
        <p className="text-muted-foreground text-sm">{displayTitle}</p>
        {description && <p className="text-muted-foreground text-xs mt-1">{description}</p>}
      </div>
    </div>
  )
}
