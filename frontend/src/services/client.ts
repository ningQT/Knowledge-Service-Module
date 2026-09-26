import ky from 'ky'
import { ApiError } from '@/lib/i18nFormat'

const api = ky.create({
  prefix: '/api/v1',
  timeout: 30000,
  credentials: 'include',
  hooks: {
    afterResponse: [
      async ({ response }) => {
        if (!response.ok) {
          const error = await response.json().catch(() => ({ error: 'Request failed', code: 'REQUEST_FAILED' }))
          const payload = error as { code?: string; error?: string; detail?: string }
          const apiError = new ApiError(payload.error || payload.detail || `HTTP ${response.status}`, {
            code: payload.code,
            detail: payload.detail,
            status: response.status,
          })
          if (response.status === 403 && typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('ksm:forbidden', { detail: apiError }))
          }
          throw apiError
        }
      },
    ],
  },
})

export default api
