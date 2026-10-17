import type { ReactNode } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, LayoutGrid, LogOut, MessageCircle, Palette, Shield } from 'lucide-react'
import { api, type Me } from './api'
import { Logo, Spinner } from './ui'
import { ThemeToggle } from './theme'
import Landing from './pages/Landing'
import { Login, Signup } from './pages/Auth'
import Onboarding from './pages/Onboarding'
import Dashboard from './pages/Dashboard'
import DraftDetailPage from './pages/DraftDetail'
import Chat from './pages/Chat'
import Calendar from './pages/Calendar'
import BrandPage from './pages/Brand'
import Admin from './pages/Admin'
import { DataDeletion, Privacy, Terms } from './pages/Legal'

export function useMe() {
  return useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/api/me') })
}

function Protected({ children }: { children: ReactNode }) {
  const me = useMe()
  const location = useLocation()
  if (me.isLoading) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner />
      </div>
    )
  }
  if (me.isError || !me.data) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

function Shell({ children }: { children: ReactNode }) {
  const me = useMe()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const logout = async () => {
    await api('/api/auth/logout', { method: 'POST' })
    qc.clear()
    navigate('/')
  }
  const link = ({ isActive }: { isActive: boolean }) =>
    `inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-2 text-sm font-semibold transition ${isActive ? 'bg-brand-100 text-brand-800 shadow-xs ring-1 ring-brand-200' : 'text-ink-soft hover:bg-surface-2 hover:text-ink'}`
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-3">
          <Link to="/app" className="rounded-full">
            <Logo name={me.data?.app_name} />
          </Link>
          <div className="flex items-center gap-1.5 md:order-last">
            <ThemeToggle />
            <button onClick={logout} className="grid h-9 w-9 place-items-center rounded-full text-ink-soft transition hover:bg-surface-2 hover:text-ink" title="Log out" aria-label="Log out">
              <LogOut className="h-4 w-4" />
            </button>
          </div>
          <nav className="-mx-1 flex w-full items-center gap-1 overflow-x-auto px-1 pb-0.5 md:mx-0 md:w-auto md:flex-1 md:justify-end md:overflow-visible md:p-0">
            <NavLink to="/app" end className={link}>
              <LayoutGrid className="h-4 w-4" /> Drafts
            </NavLink>
            <NavLink to="/app/chat" className={link}>
              <MessageCircle className="h-4 w-4" /> Chat
            </NavLink>
            <NavLink to="/app/calendar" className={link}>
              <CalendarDays className="h-4 w-4" /> Calendar
            </NavLink>
            <NavLink to="/app/brand" className={link}>
              <Palette className="h-4 w-4" /> Brand kit
            </NavLink>
            {me.data?.is_admin && (
              <NavLink to="/app/admin" className={link}>
                <Shield className="h-4 w-4" /> Admin
              </NavLink>
            )}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  )
}

const inApp = (page: ReactNode) => (
  <Protected>
    <Shell>{page}</Shell>
  </Protected>
)

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/privacy" element={<Privacy />} />
      <Route path="/terms" element={<Terms />} />
      <Route path="/data-deletion" element={<DataDeletion />} />
      <Route path="/onboarding" element={<Protected><Onboarding /></Protected>} />
      <Route path="/app" element={inApp(<Dashboard />)} />
      <Route path="/app/drafts/:id" element={inApp(<DraftDetailPage />)} />
      <Route path="/app/chat" element={inApp(<Chat />)} />
      <Route path="/app/calendar" element={inApp(<Calendar />)} />
      <Route path="/app/brand" element={inApp(<BrandPage />)} />
      <Route path="/app/admin" element={inApp(<Admin />)} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
