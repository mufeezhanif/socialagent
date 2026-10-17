import { Bot, CalendarClock, Scissors, User as UserIcon, type LucideIcon } from 'lucide-react'
import type { DraftSummary } from '../api'
import { whoseTurn } from './PipelineStepper'

/*
 * Four numbers above the dashboard grid that tell the human + AI story at a glance:
 * what is waiting on you, what the agent is busy with, how much filler it cut, and what is live or queued.
 * Uses the same GET /api/drafts list the dashboard already polls.
 */

function fmtSeconds(total: number) {
  const s = Math.round(total)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rest = s % 60
  return m < 60 ? `${m}m ${String(rest).padStart(2, '0')}s` : `${Math.floor(m / 60)}h ${m % 60}m`
}

function Stat({ icon: Icon, value, label, note, accent = false }: { icon: LucideIcon; value: string; label: string; note?: string; accent?: boolean }) {
  return (
    <div className={`rounded-2xl border p-3.5 sm:p-4 ${accent ? 'border-gold bg-gold/15' : 'border-line bg-surface'}`}>
      <div className={`flex items-center gap-1.5 text-[11px] font-bold tracking-wider uppercase ${accent ? 'text-brand-800' : 'text-ink-faint'}`}>
        <Icon className="h-3.5 w-3.5" aria-hidden /> {label}
      </div>
      <div className="mt-1 font-display text-3xl leading-none font-semibold text-ink tabular-nums">{value}</div>
      {note && <div className="mt-1 truncate text-xs text-ink-soft">{note}</div>}
    </div>
  )
}

export default function ImpactStrip({ drafts, className = '' }: { drafts: DraftSummary[]; className?: string }) {
  const yours = drafts.filter((d) => whoseTurn(d.status) === 'you').length
  const working = drafts.filter((d) => whoseTurn(d.status) === 'ai' && d.status !== 'scheduled').length
  const trimmed = drafts.reduce((sum, d) => (d.duration_in && d.duration_out && d.duration_in > d.duration_out ? sum + (d.duration_in - d.duration_out) : sum), 0)
  const edited = drafts.filter((d) => d.duration_out).length
  const published = drafts.filter((d) => d.status === 'published').length
  const next = drafts
    .filter((d) => d.status === 'scheduled' && d.publish_at)
    .map((d) => new Date(d.publish_at as string))
    .sort((a, b) => a.getTime() - b.getTime())[0]

  return (
    <section aria-label="Your Reels at a glance" className={`grid grid-cols-2 gap-3 lg:grid-cols-4 ${className}`}>
      <Stat icon={UserIcon} value={String(yours)} label="Waiting on you" note={yours ? 'Your call on these' : 'All caught up'} accent={yours > 0} />
      <Stat icon={Bot} value={String(working)} label="AI working" note={working ? 'Editing or writing now' : 'Idle, send a clip'} />
      <Stat icon={Scissors} value={fmtSeconds(trimmed)} label="Filler cut by AI" note={edited ? `across ${edited} ${edited === 1 ? 'edit' : 'edits'}` : 'Nothing edited yet'} />
      <Stat
        icon={CalendarClock}
        value={String(published)}
        label="Posted"
        note={next ? `Next ${next.toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })}` : 'Nothing queued'}
      />
    </section>
  )
}
