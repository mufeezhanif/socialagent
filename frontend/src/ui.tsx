import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from 'react'
import { Loader2 } from 'lucide-react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'wa' | 'ig'

const variants: Record<Variant, string> = {
  primary: 'bg-brand-600 text-on-brand hover:bg-brand-700 shadow-sm',
  secondary: 'bg-surface text-ink border border-line hover:border-brand-200 hover:bg-surface-2 shadow-xs',
  ghost: 'text-ink-soft hover:bg-surface-2 hover:text-ink',
  danger: 'bg-surface text-danger border border-danger/30 hover:bg-danger-soft',
  wa: 'bg-wa text-[#0b2e1f] hover:brightness-95 shadow-sm',
  ig: 'ig-gradient text-white hover:brightness-110 shadow-sm',
}

export function Button({
  variant = 'primary',
  loading,
  className = '',
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  )
}

export function Card({ className = '', children }: { className?: string; children: ReactNode }) {
  return <div className={`rounded-2xl border border-line bg-surface p-5 shadow-sm ${className}`}>{children}</div>
}

const field =
  'w-full rounded-xl border border-line bg-surface-2/50 px-3.5 py-2.5 text-sm text-ink outline-none transition placeholder:text-ink-faint hover:border-brand-200 focus:border-brand-500 focus:bg-surface focus:ring-4 focus:ring-brand-500/15'

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${field} ${props.className || ''}`} />
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${field} ${props.className || ''}`} />
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-semibold text-ink-soft">{label}</span>
      {children}
      {hint && <span className="block text-xs text-ink-faint">{hint}</span>}
    </label>
  )
}

export function Spinner({ className = '' }: { className?: string }) {
  return <Loader2 className={`h-5 w-5 animate-spin text-brand-600 ${className}`} />
}

const working = 'bg-warn-soft text-warn'
const waiting = 'bg-brand-100 text-brand-800'

const statusColors: Record<string, string> = {
  processing: working,
  revising: working,
  captioning: working,
  publishing: working,
  awaiting_video_approval: waiting,
  awaiting_change_notes: waiting,
  awaiting_context: waiting,
  awaiting_caption_choice: waiting,
  awaiting_publish_choice: waiting,
  awaiting_schedule_time: waiting,
  scheduled: 'bg-info-soft text-info',
  published: 'bg-success-soft text-success',
  saved: 'bg-surface-2 text-ink-soft',
  discarded: 'bg-surface-2 text-ink-faint',
  failed: 'bg-danger-soft text-danger',
}

export function StatusBadge({ status, label }: { status: string; label: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-black/5 ring-inset dark:ring-white/5 ${statusColors[status] || 'bg-surface-2 text-ink-soft'}`}>
      {label}
    </span>
  )
}

export function Logo({ name = 'SocialAgent' }: { name?: string }) {
  const initial = (name || 'S').trim().charAt(0).toUpperCase() || 'S'
  return (
    <span className="inline-flex items-center gap-2.5 text-ink">
      <span
        aria-hidden
        className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand-500 to-brand-800 pt-0.5 font-display text-xl font-bold text-on-brand italic shadow-sm ring-1 ring-gold/40 dark:from-brand-800 dark:to-brand-500"
      >
        {initial}
      </span>
      <span className="font-script text-[1.85rem] leading-none whitespace-nowrap">{name}</span>
    </span>
  )
}

export function fmtDate(iso: string | null | undefined) {
  if (!iso) return ''
  return new Date(iso).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}
