import { useTranslation } from 'react-i18next'

export function LoadingState({ text }: { text?: string }) {
  const { t } = useTranslation('common')
  const displayText = text ?? t('loading')

  return (
    <div className="flex items-center justify-center h-64">
      <div className="flex flex-col items-center gap-4">
        <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
        <p className="text-muted-foreground text-sm">{displayText}</p>
      </div>
    </div>
  )
}
