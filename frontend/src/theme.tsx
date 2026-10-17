import { useSyncExternalStore } from 'react'
import { Monitor, Moon, Sun } from 'lucide-react'

export type Theme = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

const KEY = 'sa-theme'
const ORDER: Theme[] = ['light', 'dark', 'system']
const LABELS: Record<Theme, string> = { light: 'Light', dark: 'Dark', system: 'System' }

const media = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null
const listeners = new Set<() => void>()

function readStored(): Theme {
  try {
    const value = localStorage.getItem(KEY)
    if (value === 'light' || value === 'dark' || value === 'system') return value
  } catch {
    // storage blocked (private mode): fall back to system
  }
  return 'system'
}

let theme: Theme = readStored()
let systemDark = media?.matches ?? false

const resolve = (): ResolvedTheme => (theme === 'dark' || (theme === 'system' && systemDark) ? 'dark' : 'light')

function apply() {
  if (typeof document === 'undefined') return
  const dark = resolve() === 'dark'
  const root = document.documentElement
  root.classList.toggle('dark', dark)
  root.style.colorScheme = dark ? 'dark' : 'light'
}

function emit() {
  apply()
  listeners.forEach((listener) => listener())
}

media?.addEventListener('change', (e) => {
  systemDark = e.matches
  if (theme === 'system') emit()
})

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key !== KEY) return
    theme = readStored()
    emit()
  })
}

apply()

export function setTheme(next: Theme) {
  theme = next
  try {
    localStorage.setItem(KEY, next)
  } catch {
    // ignore: theme still applies for this session
  }
  emit()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

const snapshot = () => `${theme}:${resolve()}`

export function useTheme() {
  const snap = useSyncExternalStore(subscribe, snapshot, snapshot)
  const [current, resolved] = snap.split(':') as [Theme, ResolvedTheme]
  return { theme: current, resolved, setTheme }
}

export function ThemeToggle({ className = '' }: { className?: string }) {
  const { theme: current, resolved } = useTheme()
  const next = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length]
  const Icon = current === 'light' ? Sun : current === 'dark' ? Moon : Monitor
  const label = `Theme: ${LABELS[current]}${current === 'system' ? ` (${resolved})` : ''}. Switch to ${LABELS[next].toLowerCase()}`
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={label}
      title={label}
      className={`grid h-9 w-9 shrink-0 place-items-center rounded-full border border-line bg-surface/70 text-ink-soft shadow-xs transition hover:border-brand-300 hover:bg-surface hover:text-brand-700 ${className}`}
    >
      <Icon className="h-4 w-4" />
    </button>
  )
}
