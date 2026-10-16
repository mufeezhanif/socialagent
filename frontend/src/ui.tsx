import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from 'react'
import { Loader2 } from 'lucide-react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'wa' | 'ig'

const variants: Record<Variant, string> = {
  primary: 'bg-brand-600 text-white hover:bg-brand-700 shadow-sm',
  secondary: 'bg-white text-slate-800 border border-slate-200 hover:bg-slate-50 shadow-sm',
  ghost: 'text-slate-600 hover:bg-slate-100',
  danger: 'bg-white text-red-600 border border-red-200 hover:bg-red-50',
  wa: 'bg-wa text-white hover:brightness-95 shadow-sm',
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
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  )
}

export function Card({ className = '', children }: { className?: string; children: ReactNode }) {
  return <div className={`rounded-2xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}>{children}</div>
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm outline-none transition focus:border-brand-500 focus:ring-4 focus:ring-brand-100 ${props.className || ''}`}
    />
  )
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm outline-none transition focus:border-brand-500 focus:ring-4 focus:ring-brand-100 ${props.className || ''}`}
    />
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="block text-xs text-slate-500">{hint}</span>}
    </label>
  )
}

export function Spinner({ className = '' }: { className?: string }) {
  return <Loader2 className={`h-5 w-5 animate-spin text-brand-600 ${className}`} />
}

const statusColors: Record<string, string> = {
  processing: 'bg-amber-100 text-amber-800',
  revising: 'bg-amber-100 text-amber-800',
  captioning: 'bg-amber-100 text-amber-800',
  publishing: 'bg-amber-100 text-amber-800',
  awaiting_video_approval: 'bg-brand-100 text-brand-700',
  awaiting_change_notes: 'bg-brand-100 text-brand-700',
  awaiting_context: 'bg-brand-100 text-brand-700',
  awaiting_caption_choice: 'bg-brand-100 text-brand-700',
  awaiting_publish_choice: 'bg-brand-100 text-brand-700',
  awaiting_schedule_time: 'bg-brand-100 text-brand-700',
  scheduled: 'bg-sky-100 text-sky-800',
  published: 'bg-emerald-100 text-emerald-800',
  saved: 'bg-slate-100 text-slate-700',
  discarded: 'bg-slate-100 text-slate-500',
  failed: 'bg-red-100 text-red-700',
}

export function StatusBadge({ status, label }: { status: string; label: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${statusColors[status] || 'bg-slate-100 text-slate-700'}`}>
      {label}
    </span>
  )
}

export function Logo({ name = 'SocialAgent' }: { name?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-lg font-extrabold tracking-tight">
      <span className="grid h-8 w-8 place-items-center rounded-xl bg-brand-600 text-white">🎬</span>
      {name}
    </span>
  )
}

export function fmtDate(iso: string | null | undefined) {
  if (!iso) return ''
  return new Date(iso).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}
