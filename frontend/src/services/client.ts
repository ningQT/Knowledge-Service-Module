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
          throw new ApiError(payload.error || payload.detail || `HTTP ${response.status}`, {
            code: payload.code,
            detail: payload.detail,
            status: response.status,
          })
        }
      },
    ],
  },
})

export default api
