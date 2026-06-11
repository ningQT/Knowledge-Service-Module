import api from './client'
import type { LLMSettings, LLMTestResult } from '@/types/api'

export async function getLLMSettings(): Promise<LLMSettings> {
  return api.get('settings/llm').json<LLMSettings>()
}

export async function updateLLMSettings(data: {
  provider?: string
  base_url?: string
  api_key?: string
  model?: string
  temperature?: number
  max_tokens?: number
}): Promise<{ updated: boolean; settings: LLMSettings }> {
  return api.put('settings/llm', { json: data }).json()
}

export async function resetLLMSettings(): Promise<{ reset: boolean; message: string }> {
  return api.delete('settings/llm').json()
}

export async function testLLMConnection(data?: {
  provider?: string
  base_url?: string
  api_key?: string
  model?: string
  temperature?: number
  max_tokens?: number
}): Promise<LLMTestResult> {
  return api.post('settings/llm/test', { json: data || {} }).json<LLMTestResult>()
}
