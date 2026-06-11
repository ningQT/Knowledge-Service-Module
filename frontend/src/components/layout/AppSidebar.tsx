import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { BookMarked, BookOpen, Database, KeyRound, LayoutDashboard, Network, Upload, Search, Settings, Menu, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useTranslation } from 'react-i18next'

const navItems = [
  { icon: LayoutDashboard, labelKey: 'nav.dashboard', to: '/' },
  { icon: Network, labelKey: 'nav.graph', to: '/graph' },
  { icon: BookOpen, labelKey: 'nav.knowledge', to: '/knowledge' },
  { icon: Upload, labelKey: 'nav.ingest', to: '/ingest' },
  { icon: Search, labelKey: 'nav.search', to: '/search' },
  { icon: BookMarked, labelKey: 'nav.searchLexicon', to: '/search-lexicon' },
  { icon: Database, labelKey: 'nav.ontology', to: '/ontology' },
  { icon: KeyRound, labelKey: 'nav.apiManagement', to: '/api-management' },
  { icon: Settings, labelKey: 'nav.settings', to: '/settings' },
]

interface NoteRouteState {
  returnTo?: string
}

function getNoteSourcePath(pathname: string, state: unknown) {
  if (!pathname.startsWith('/note/')) return null

  const stateReturnTo = (state as NoteRouteState | null)?.returnTo
  const returnTo = typeof stateReturnTo === 'string' ? stateReturnTo : ''

  if (returnTo.startsWith('/graph')) return '/graph'
  if (returnTo.startsWith('/search')) return '/search'
  return '/knowledge'
}

function NavLinks({ onClick }: { onClick?: () => void }) {
  const { t } = useTranslation('layout')
  const location = useLocation()
  const noteSourcePath = getNoteSourcePath(location.pathname, location.state)

  return (
    <nav className="flex-1 py-4 space-y-1 px-3">
      {navItems.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === '/'}
          onClick={onClick}
          className={({ isActive }) => {
            const active = isActive || noteSourcePath === item.to

            return cn(
              'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
              active
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted'
            )
          }}
        >
          <item.icon className="w-5 h-5" />
          {t(item.labelKey)}
        </NavLink>
      ))}
    </nav>
  )
}

export function AppSidebar() {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const { t } = useTranslation('layout')

  return (
    <>
      {/* Mobile hamburger */}
      <button
        className="lg:hidden fixed top-3 left-3 z-50 p-2 rounded-md bg-card border border-border"
        onClick={() => setDrawerOpen(true)}
        aria-label={t('aria.openMenu')}
      >
        <Menu className="w-5 h-5" />
      </button>

      {/* Mobile drawer overlay */}
      {drawerOpen && (
        <div
          className="lg:hidden fixed inset-0 z-40 bg-black/50"
          onClick={() => setDrawerOpen(false)}
        />
      )}

      {/* Mobile drawer */}
      <aside
        className={cn(
          'lg:hidden fixed inset-y-0 left-0 z-50 w-60 flex flex-col bg-card border-r border-border transition-transform',
          drawerOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <span className="text-primary-foreground font-bold text-sm">K</span>
            </div>
            <span className="font-semibold text-foreground">{t('brand')}</span>
          </div>
          <button onClick={() => setDrawerOpen(false)} aria-label={t('aria.closeMenu')}>
            <X className="w-5 h-5 text-muted-foreground" />
          </button>
        </div>
        <NavLinks onClick={() => setDrawerOpen(false)} />
      </aside>

      {/* Desktop sidebar */}
      <aside className="hidden lg:flex w-60 flex-col bg-card border-r border-border">
        <div className="flex items-center gap-2 px-6 py-4 border-b border-border">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
            <span className="text-primary-foreground font-bold text-sm">K</span>
          </div>
          <span className="font-semibold text-foreground">{t('brand')}</span>
        </div>
        <NavLinks />
      </aside>
    </>
  )
}
