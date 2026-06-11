import { Component, type ReactNode, type ErrorInfo } from 'react'
import i18n from '@/i18n'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback

      let title = 'Something went wrong'
      let description = 'An unexpected error occurred'
      let tryAgain = 'Try Again'
      try {
        title = i18n.t('common:error.title')
        description = i18n.t('common:error.description')
        tryAgain = i18n.t('common:tryAgain')
      } catch {
        // fallback to hardcoded values if i18n fails
      }
      const message = import.meta.env.PROD ? description : this.state.error?.message || description

      return (
        <div className="flex flex-col items-center justify-center min-h-[200px] p-8 text-center">
          <div className="text-error text-4xl mb-4">!</div>
          <h2 className="text-lg font-semibold mb-2">{title}</h2>
          <p className="text-sm text-muted-foreground mb-4 max-w-md">
            {message}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm hover:opacity-90"
          >
            {tryAgain}
          </button>
        </div>
      )
    }

    return this.props.children
  }
}
