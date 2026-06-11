import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle, ExternalLink, Eye, EyeOff, Loader2, XCircle } from 'lucide-react'
import { getLLMSettings, resetLLMSettings, testLLMConnection, updateLLMSettings } from '@/services/settings'
import type { LLMProviderOption, LLMSettings, LLMTestResult } from '@/types/api'
import { LoadingState } from '@/components/shared/LoadingState'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { formatApiError, formatLLMTestError } from '@/lib/i18nFormat'
import { useTranslation } from 'react-i18next'

export default function SettingsPage() {
  const [settings, setSettings] = useState<LLMSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<LLMTestResult | null>(null)
  const [showApiKey, setShowApiKey] = useState(false)
  const [error, setError] = useState('')
  const { t } = useTranslation('settings')

  const [provider, setProvider] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [temperature, setTemperature] = useState(0.3)
  const [maxTokens, setMaxTokens] = useState(4096)

  const selectedProvider = useMemo(
    () => settings?.provider_options.find((item) => item.id === provider) ?? null,
    [provider, settings?.provider_options]
  )

  const loadSettings = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getLLMSettings()
      setSettings(data)
      applySettings(data)
    } catch (e) {
      setError(formatApiError(t, e))
    }
    setLoading(false)
  }, [t])

  useEffect(() => {
    queueMicrotask(loadSettings)
  }, [loadSettings])

  function applySettings(data: LLMSettings) {
    setProvider(data.provider)
    setBaseUrl(data.base_url)
    setModel(data.model)
    setTemperature(data.temperature)
    setMaxTokens(data.max_tokens)
  }

  function handleProviderChange(nextProviderId: string) {
    const option = settings?.provider_options.find((item) => item.id === nextProviderId)
    setProvider(nextProviderId)
    setBaseUrl(option?.default_base_url ?? '')
    setTestResult(null)
  }

  async function handleSave() {
    setSaving(true)
    setError('')
    try {
      const updates: Record<string, unknown> = {}
      if (provider !== settings?.provider) updates.provider = provider
      if (baseUrl !== settings?.base_url) updates.base_url = baseUrl
      if (apiKey) updates.api_key = apiKey
      if (model !== settings?.model) updates.model = model
      if (temperature !== settings?.temperature) updates.temperature = temperature
      if (maxTokens !== settings?.max_tokens) updates.max_tokens = maxTokens

      if (Object.keys(updates).length === 0) return

      const result = await updateLLMSettings(updates)
      setSettings(result.settings)
      applySettings(result.settings)
      setApiKey('')
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setSaving(false)
    }
  }

  async function handleReset() {
    setError('')
    setTestResult(null)
    try {
      await resetLLMSettings()
      await loadSettings()
      setApiKey('')
    } catch (e) {
      setError(formatApiError(t, e))
    }
  }

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    setError('')
    try {
      const result = await testLLMConnection({
        provider,
        base_url: baseUrl,
        ...(apiKey ? { api_key: apiKey } : {}),
        model,
        temperature,
        max_tokens: maxTokens,
      })
      setTestResult(result)
    } catch (e) {
      setTestResult({ success: false, model, latency_ms: null, error: formatApiError(t, e) })
    }
    setTesting(false)
  }

  if (loading) return <LoadingState />

  const providerOptions = settings?.provider_options ?? []
  const baseUrlRequired = selectedProvider?.required_fields.includes('base_url') ?? false
  const modelExamples = selectedProvider?.model_examples ?? []

  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold">{t('title')}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t('description')}</p>
      </div>

      {error && (
        <div className="rounded-md border border-error/30 bg-error/10 px-3 py-2 text-sm text-error">
          {error}
        </div>
      )}

      <div className="bg-card rounded-lg border border-border p-6 space-y-5">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div>
            <label className="block text-sm font-medium mb-1">{t('field.provider')}</label>
            <Select value={provider} onValueChange={handleProviderChange}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder={t('field.providerPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {providerOptions.map((option) => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.display_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">{t('field.model')}</label>
            <Input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={modelExamples[0] || t('field.modelPlaceholder')}
            />
          </div>
        </div>

        {selectedProvider && (
          <ProviderSummary option={selectedProvider} />
        )}

        <div>
          <label className="block text-sm font-medium mb-1">
            {t('field.apiKey')}
          </label>
          <div className="relative">
            <Input
              type={showApiKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={settings?.api_key_masked || t('field.apiKeyPlaceholder')}
              className="pr-10"
            />
            <button
              type="button"
              onClick={() => setShowApiKey(!showApiKey)}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground"
              aria-label={showApiKey ? t('field.hideApiKey') : t('field.showApiKey')}
              title={showApiKey ? t('field.hideApiKey') : t('field.showApiKey')}
            >
              {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">
            {t('field.baseUrl')}
            {baseUrlRequired && <span className="ml-1 text-error">*</span>}
          </label>
          <Input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={selectedProvider?.default_base_url || t('field.baseUrlPlaceholder')}
          />
          <p className="mt-1 text-xs text-muted-foreground">
            {selectedProvider?.default_base_url
              ? t('field.baseUrlDefault', { url: selectedProvider.default_base_url })
              : t(baseUrlRequired ? 'field.baseUrlRequired' : 'field.baseUrlOptional')}
          </p>
        </div>

        {modelExamples.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">{t('field.modelExamples')}</span>
            {modelExamples.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setModel(example)}
                className="rounded border border-border bg-muted/40 px-2 py-1 font-mono text-muted-foreground transition-colors hover:border-primary/60 hover:text-foreground"
              >
                {example}
              </button>
            ))}
          </div>
        )}

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_180px]">
          <div>
            <label className="block text-sm font-medium mb-1">
              {t('field.temperature', { value: temperature.toFixed(2) })}
            </label>
            <Slider
              value={[temperature]}
              onValueChange={([v]) => setTemperature(v)}
              min={0}
              max={2}
              step={0.1}
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>0.0</span>
              <span>2.0</span>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">{t('field.maxTokens')}</label>
            <Input
              type="number"
              value={maxTokens}
              min={1}
              onChange={(e) => setMaxTokens(Number.parseInt(e.target.value, 10) || 1)}
            />
          </div>
        </div>

        <div className="flex flex-wrap gap-3 pt-2">
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            {t('action.save')}
          </Button>
          <Button onClick={handleTest} disabled={testing} variant="secondary">
            {testing && <Loader2 className="w-4 h-4 animate-spin" />}
            {t('action.test')}
          </Button>
          <Button onClick={handleReset} variant="secondary">
            {t('action.reset')}
          </Button>
        </div>

        {testResult && (
          <div
            className={`flex items-center gap-2 rounded-md p-3 text-sm ${
              testResult.success ? 'bg-success/10 text-success' : 'bg-error/10 text-error'
            }`}
          >
            {testResult.success ? <CheckCircle className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
            {testResult.success
              ? t('test.connected', { latency: testResult.latency_ms })
              : t('test.failed', { error: formatLLMTestError(t, testResult.error) })}
          </div>
        )}
      </div>

      <div className="bg-card rounded-lg border border-border p-6">
        <h3 className="font-medium">{t('status.title')}</h3>
        <div className="mt-4 grid gap-3 text-sm md:grid-cols-2">
          <StatusRow label={t('status.provider')} value={settings?.provider_display_name || '-'} />
          <StatusRow label={t('status.state')} value={settings?.configured ? t('status.configured') : t('status.unconfigured')} />
          <StatusRow label={t('status.model')} value={settings?.model || '-'} mono />
          <StatusRow label={t('status.baseUrl')} value={settings?.base_url || '-'} mono />
        </div>
        {!settings?.configured && (
          <div className="mt-4 rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
            {t('status.missing', { fields: (settings?.missing_fields ?? []).map((field) => t(`fieldNames.${field}`, field)).join(', ') })}
          </div>
        )}
      </div>
    </div>
  )

  function ProviderSummary({ option }: { option: LLMProviderOption }) {
    return (
      <div className="rounded-md border border-border bg-muted/30 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-sm font-medium">{option.display_name}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{t('provider.managedByBackend')}</p>
          </div>
          <a
            href={option.docs_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            {t('provider.docs')}
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {option.capabilities.map((capability) => (
            <span
              key={capability}
              className="rounded-full border border-border bg-background px-2 py-0.5 text-xs text-muted-foreground"
            >
              {t(`capability.${capability}`, capability)}
            </span>
          ))}
        </div>
      </div>
    )
  }

  function StatusRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
    return (
      <div className="flex min-w-0 items-center justify-between gap-3 rounded-md border border-border/60 px-3 py-2">
        <span className="shrink-0 text-muted-foreground">{label}</span>
        <span className={`min-w-0 truncate text-right ${mono ? 'font-mono text-xs' : 'font-medium'}`}>
          {value}
        </span>
      </div>
    )
  }
}
