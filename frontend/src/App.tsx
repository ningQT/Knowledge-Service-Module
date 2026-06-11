import { lazy, Suspense, type ReactNode, useEffect } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AppLayout } from '@/components/layout/AppLayout'
import { AuthGate } from '@/components/shared/AuthGate'
import { ErrorBoundary } from '@/components/shared/ErrorBoundary'

const Dashboard = lazy(() => import('@/pages/Dashboard'))
const GraphView = lazy(() => import('@/pages/GraphView'))
const KnowledgeBasePage = lazy(() => import('@/pages/KnowledgeBasePage'))
const NoteDetail = lazy(() => import('@/pages/NoteDetail'))
const IngestPage = lazy(() => import('@/pages/IngestPage'))
const SearchPage = lazy(() => import('@/pages/SearchPage'))
const SearchLexiconPage = lazy(() => import('@/pages/SearchLexiconPage'))
const OntologyPage = lazy(() => import('@/pages/OntologyPage'))
const ApiManagementPage = lazy(() => import('@/pages/ApiManagementPage'))
const SettingsPage = lazy(() => import('@/pages/SettingsPage'))

function RouteFallback() {
  return (
    <div className="flex min-h-[280px] items-center justify-center text-sm text-muted-foreground">
      Loading...
    </div>
  )
}

function withBoundary(el: ReactNode) {
  return (
    <ErrorBoundary>
      <Suspense fallback={<RouteFallback />}>{el}</Suspense>
    </ErrorBoundary>
  )
}

function DocumentTitle() {
  const location = useLocation()
  const { t, i18n } = useTranslation('layout')

  useEffect(() => {
    const brand = t('brand')
    const pageKey = getPageTitleKey(location.pathname)
    document.title = pageKey ? `${t(pageKey)} - ${brand}` : brand
  }, [location.pathname, t, i18n.language])

  return null
}

function getPageTitleKey(pathname: string) {
  if (pathname === '/') return 'nav.dashboard'
  if (pathname.startsWith('/graph')) return 'nav.graph'
  if (pathname.startsWith('/knowledge')) return 'nav.knowledge'
  if (pathname.startsWith('/note/')) return 'nav.knowledge'
  if (pathname.startsWith('/ingest')) return 'nav.ingest'
  if (pathname.startsWith('/search-lexicon')) return 'nav.searchLexicon'
  if (pathname.startsWith('/ontology')) return 'nav.ontology'
  if (pathname.startsWith('/search')) return 'nav.search'
  if (pathname.startsWith('/api-management')) return 'nav.apiManagement'
  if (pathname.startsWith('/settings')) return 'nav.settings'
  return ''
}

export default function App() {
  return (
    <BrowserRouter>
      <DocumentTitle />
      <AuthGate>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={withBoundary(<Dashboard />)} />
            <Route path="/graph" element={withBoundary(<GraphView />)} />
            <Route path="/knowledge" element={withBoundary(<KnowledgeBasePage />)} />
            <Route path="/note/:path" element={withBoundary(<NoteDetail />)} />
            <Route path="/ingest" element={withBoundary(<IngestPage />)} />
            <Route path="/search" element={withBoundary(<SearchPage />)} />
            <Route path="/search-lexicon" element={withBoundary(<SearchLexiconPage />)} />
            <Route path="/ontology" element={withBoundary(<OntologyPage />)} />
            <Route path="/api-management" element={withBoundary(<ApiManagementPage />)} />
            <Route path="/settings" element={withBoundary(<SettingsPage />)} />
          </Route>
        </Routes>
      </AuthGate>
    </BrowserRouter>
  )
}
