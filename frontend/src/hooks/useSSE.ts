import { useEffect, useRef, useState, useCallback } from 'react'

const DEFAULT_EVENT_TYPES = ['step_update', 'step_output', 'job_complete', 'job_start']

interface UseSSEOptions {
  onEvent?: (event: string, data: unknown) => void
  onError?: (error: Event) => void
  autoConnect?: boolean
  resolveUrl?: (url: string) => Promise<string>
  /** 自定义事件类型列表（S-03: 允许调用方传入，扩展性更好） */
  eventTypes?: string[]
}

export function useSSE(url: string | null, options?: UseSSEOptions) {
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<Event | null>(null)
  const sourceRef = useRef<EventSource | null>(null)
  const onEventRef = useRef(options?.onEvent)
  const onErrorRef = useRef(options?.onError)
  const resolveUrlRef = useRef(options?.resolveUrl)

  const autoConnectRef = useRef(options?.autoConnect)
  const eventTypesRef = useRef(options?.eventTypes)
  const connectionVersionRef = useRef(0)

  useEffect(() => {
    onEventRef.current = options?.onEvent
    onErrorRef.current = options?.onError
    resolveUrlRef.current = options?.resolveUrl
    autoConnectRef.current = options?.autoConnect
    eventTypesRef.current = options?.eventTypes
  }, [options?.autoConnect, options?.eventTypes, options?.onError, options?.onEvent, options?.resolveUrl])

  const disconnect = useCallback(() => {
    connectionVersionRef.current += 1
    if (sourceRef.current) {
      sourceRef.current.close()
      sourceRef.current = null
      setConnected(false)
    }
  }, [])

  const connect = useCallback(() => {
    if (!url) return
    disconnect()
    const connectionVersion = connectionVersionRef.current + 1
    connectionVersionRef.current = connectionVersion

    const open = async () => {
      let resolvedUrl = url
      try {
        if (resolveUrlRef.current) {
          resolvedUrl = await resolveUrlRef.current(url)
        }
      } catch {
        const errorEvent = new Event('error')
        setError(errorEvent)
        setConnected(false)
        onErrorRef.current?.(errorEvent)
        return
      }
      if (connectionVersionRef.current !== connectionVersion) return

      const source = new EventSource(resolvedUrl)
    sourceRef.current = source

    source.onopen = () => {
      setConnected(true)
      setError(null)
    }

    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onEventRef.current?.('message', data)
      } catch {
        onEventRef.current?.('message', event.data)
      }
    }

    source.onerror = (event) => {
      setError(event)
      setConnected(false)
      onErrorRef.current?.(event)
    }

    // Listen for custom event types (S-03: 使用调用方传入或默认的事件类型)
    const eventTypes = eventTypesRef.current || DEFAULT_EVENT_TYPES
    for (const eventType of eventTypes) {
      source.addEventListener(eventType, (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data)
          onEventRef.current?.(eventType, data)
        } catch {
          onEventRef.current?.(eventType, event.data)
        }
      })
    }
    }

    void open().catch((err) => {
      console.error('SSE connection setup failed', err)
      const errorEvent = new Event('error')
      setError(errorEvent)
      setConnected(false)
      onErrorRef.current?.(errorEvent)
    })
  }, [url, disconnect])

  useEffect(() => {
    if (url && autoConnectRef.current !== false) {
      connect()
    }
    return disconnect
  }, [url, connect, disconnect])

  return { connected, connect, disconnect, error }
}
