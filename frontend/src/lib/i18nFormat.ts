import type { TFunction } from 'i18next'

export class ApiError extends Error {
  code?: string
  detail?: string
  status?: number

  constructor(message: string, options: { code?: string; detail?: string; status?: number } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = options.code
    this.detail = options.detail
    this.status = options.status
  }
}

function formatEnum(t: TFunction, keyPrefix: string, value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return ''
  const raw = String(value)
  const translated = t(`${keyPrefix}.${raw}`, { defaultValue: raw })
  return typeof translated === 'string' ? translated : raw
}

export function formatVerification(t: TFunction, value: string | null | undefined) {
  return formatEnum(t, 'common:enums.verification', value)
}

export function formatNoteType(t: TFunction, value: string | null | undefined) {
  return formatEnum(t, 'common:enums.noteType', value)
}

export function formatDomain(t: TFunction, value: string | null | undefined) {
  return formatEnum(t, 'common:enums.domain', value)
}

export function formatKind(t: TFunction, value: string | null | undefined) {
  return formatEnum(t, 'common:enums.kind', value)
}

export function formatRelationType(t: TFunction, value: string | null | undefined) {
  return formatEnum(t, 'common:enums.relation', value)
}

export function formatJobStatus(t: TFunction, value: string | null | undefined) {
  return formatEnum(t, 'common:enums.jobStatus', value)
}

export function formatGraphLayer(t: TFunction, value: number | string | null | undefined) {
  return formatEnum(t, 'common:enums.graphLayer', value)
}

export function formatSearchIntent(t: TFunction, value: string | null | undefined) {
  return formatEnum(t, 'common:enums.searchIntent', value)
}

export function formatSearchPath(t: TFunction, value: string | null | undefined) {
  return formatEnum(t, 'common:enums.searchPath', value)
}

export function formatApiError(t: TFunction, error: unknown) {
  if (error instanceof ApiError) {
    if (error.code) {
      const translated = t(`common:apiErrors.${error.code}`, { defaultValue: '' })
      if (translated) return translated
    }
    return error.detail || error.message
  }

  if (error instanceof Error) return error.message
  return String(error)
}

export function formatLLMTestError(t: TFunction, error: string | null | undefined) {
  if (!error) return ''
  if (error.startsWith('LLM configuration is incomplete:')) {
    const fields = error.replace('LLM configuration is incomplete:', '').trim()
    return t('settings:test.errors.INCOMPLETE_CONFIGURATION', { fields, defaultValue: error })
  }
  if (error.startsWith('Unsupported LLM provider:')) {
    const provider = error.replace('Unsupported LLM provider:', '').trim()
    return t('settings:test.errors.UNSUPPORTED_PROVIDER', { provider, defaultValue: error })
  }
  const knownErrors: Record<string, string> = {
    'API key is not configured': 'settings:test.errors.API_KEY_NOT_CONFIGURED',
  }
  const key = knownErrors[error]
  if (!key) return error
  return t(key, { defaultValue: error })
}
