import { useEffect, useRef, useState } from 'react'
import { Keyboard, X } from 'lucide-react'

/*
 * Single-key shortcuts for the review step (A = approve, 1-3 = pick a caption, ...), a hint chip at the
 * bottom of the screen and a "?" help sheet. Keys are ignored while typing in a field or with a modifier held.
 * Hidden on touch screens.
 */

export interface Hotkey {
  /** Single key, case-insensitive: 'a', '1', 'n'. */
  key: string
  label: string
  run: () => void
  /** Default true. Disabled keys are hidden and do nothing. */
  enabled?: boolean
  /** Show this key in the floating chip (default true; the chip shows at most 3). */
  chip?: boolean
}

function isTyping(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

export function Kbd({ children, pressed = false }: { children: string; pressed?: boolean }) {
  return (
    <kbd
      className={`inline-grid h-6 min-w-6 place-items-center rounded-md border border-b-2 px-1.5 font-sans text-xs font-bold uppercase transition-colors motion-reduce:transition-none ${
        pressed ? 'border-brand-600 bg-brand-600 text-on-brand' : 'border-line bg-surface text-ink'
      }`}
    >
      {children}
    </kbd>
  )
}

/** Binds the keys without rendering anything. KeyboardShortcuts uses it; use it directly if you want no chip. */
export function useHotkeys(hotkeys: Hotkey[], onFire?: (key: string) => void, onHelp?: () => void) {
  const latest = useRef({ hotkeys, onFire, onHelp })
  useEffect(() => {
    latest.current = { hotkeys, onFire, onHelp }
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.repeat || e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return
      const { hotkeys: list, onFire: fire, onHelp: help } = latest.current
      if (e.key === '?') {
        if (document.querySelector('[aria-modal="true"]:not([data-shortcuts-help])')) return
        e.preventDefault()
        help?.()
        return
      }
      if (document.querySelector('[aria-modal="true"]')) return
      const hit = list.find((h) => h.enabled !== false && h.key.toLowerCase() === e.key.toLowerCase())
      if (!hit) return
      e.preventDefault()
      fire?.(hit.key)
      hit.run()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}

export default function KeyboardShortcuts({ hotkeys, className = '' }: { hotkeys: Hotkey[]; className?: string }) {
  const [help, setHelp] = useState(false)
  const [flash, setFlash] = useState<string | null>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const returnTo = useRef<Element | null>(null)
  const active = hotkeys.filter((h) => h.enabled !== false)

  useHotkeys(
    hotkeys,
    (key) => {
      setFlash(key)
      window.setTimeout(() => setFlash((k) => (k === key ? null : k)), 450)
    },
    () => setHelp((h) => !h),
  )

  useEffect(() => {
    if (!help) return
    returnTo.current = document.activeElement
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setHelp(false)
      if (e.key === 'Tab') {
        e.preventDefault()
        closeRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      if (returnTo.current instanceof HTMLElement) returnTo.current.focus()
    }
  }, [help])

  if (active.length === 0) return null
  const chip = active.filter((h) => h.chip !== false).slice(0, 3)

  return (
    <>
      <div
        className={`fixed bottom-4 left-1/2 z-30 hidden -translate-x-1/2 items-center gap-3 rounded-full border border-line bg-surface/90 py-1.5 pr-1.5 pl-4 text-xs text-ink-soft shadow-lg backdrop-blur sm:flex [@media(hover:none)]:hidden ${className}`}
      >
        {chip.map((h) => (
          <span key={h.key} className="inline-flex items-center gap-1.5 whitespace-nowrap">
            <Kbd pressed={flash === h.key}>{h.key}</Kbd>
            {h.label}
          </span>
        ))}
        <button
          type="button"
          onClick={() => setHelp(true)}
          className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-3 py-1.5 font-semibold text-ink transition hover:bg-brand-100 focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:outline-none"
          aria-label="Show keyboard shortcuts"
        >
          <Keyboard className="h-3.5 w-3.5" aria-hidden /> ?
        </button>
      </div>

      {help && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4 backdrop-blur-sm" onClick={() => setHelp(false)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="shortcuts-title"
            data-shortcuts-help
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-sm rounded-2xl border border-line bg-surface p-5 shadow-2xl"
          >
            <div className="flex items-center justify-between">
              <h2 id="shortcuts-title" className="font-display text-xl font-semibold text-ink">
                Keyboard shortcuts
              </h2>
              <button
                ref={closeRef}
                type="button"
                onClick={() => setHelp(false)}
                aria-label="Close"
                className="rounded-lg p-1.5 text-ink-soft hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:outline-none"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>
            <ul className="mt-3 divide-y divide-line">
              {active.map((h) => (
                <li key={h.key} className="flex items-center justify-between gap-3 py-2 text-sm text-ink">
                  {h.label}
                  <Kbd>{h.key}</Kbd>
                </li>
              ))}
              <li className="flex items-center justify-between gap-3 py-2 text-sm text-ink-soft">
                Show or hide this list
                <Kbd>?</Kbd>
              </li>
            </ul>
            <p className="mt-3 text-xs text-ink-faint">Shortcuts pause while you type. Posting always needs a click.</p>
          </div>
        </div>
      )}
    </>
  )
}
