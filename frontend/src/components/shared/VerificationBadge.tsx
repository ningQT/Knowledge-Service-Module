import { cn } from '@/lib/utils'
import { formatVerification } from '@/lib/i18nFormat'
import { useTranslation } from 'react-i18next'

const verificationStyles: Record<string, string> = {
  verified: 'bg-success/20 text-success',
  draft: 'bg-warning/20 text-warning',
  truncated: 'bg-error/10 text-error',
  unverified: 'bg-muted text-muted-foreground',
}

export function VerificationBadge({
  verification,
  className,
}: {
  verification: string
  className?: string
}) {
  const { t } = useTranslation('common')

  return (
    <span
      className={cn(
        'px-2 py-0.5 rounded text-xs',
        verificationStyles[verification] || verificationStyles.unverified,
        className
      )}
    >
      {formatVerification(t, verification)}
    </span>
  )
}
