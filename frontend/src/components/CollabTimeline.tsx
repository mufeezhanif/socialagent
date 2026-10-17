import { AlertTriangle, Bot, ExternalLink, User as UserIcon, Wrench } from 'lucide-react'

/*
 * "Who did what": the draft's audit log drawn as two lanes, AI on the left and you on the right
 * (one column on phones). Takes DraftDetail.events as-is from GET /api/drafts/:id.
 */

export interface TimelineEvent {
  actor: 'ai' | 'human' | 'system'
  action: string
  detail: Record<string, unknown>
  at: string
}

const str = (v: unknown) => (typeof v === 'string' && v.trim() ? v : null)
const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

function fmtTime(iso: string) {
  const d = new Date(iso)
  const today = new Date().toDateString() === d.toDateString()
  return today
    ? d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
    : d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

function fmtGap(ms: number) {
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min`
  const h = Math.round(m / 60)
  return h < 48 ? `${h} h` : `${Math.round(h / 24)} days`
}

interface Described {
  title: string
  lines: string[]
  quote?: string
  bullets?: string[]
  link?: string
  warn?: boolean
}

function describe(e: TimelineEvent): Described {
  const d = e.detail || {}
  switch (e.action) {
    case 'sent_video':
      return { title: 'Sent a raw clip', lines: [str(d.channel) ? `via ${d.channel === 'web' ? 'web chat' : d.channel}` : ''], quote: str(d.context) ?? undefined }
    case 'edited_video': {
      const lines = [
        num(d.revision) ? `revision ${d.revision}` : '',
        str(d.style) ? `${d.style} style` : '',
        num(d.seconds) ? `took ${d.seconds}s` : '',
        num(d.tools) ? `${d.tools} editing tool calls` : '',
        str(d.director) && d.director !== 'rules' ? `directed by ${d.director}` : '',
      ]
      const bullets = Array.isArray(d.summary) ? d.summary.filter((b): b is string => typeof b === 'string') : []
      return { title: 'Edited the video', lines, bullets }
    }
    case 'requested_changes':
      return { title: 'Asked for changes', lines: [], quote: str(d.notes) ?? undefined }
    case 'requested_style':
      return { title: 'Asked for another style', lines: [str(d.style) ? `${d.style}` : ''] }
    case 'requested_motion':
      return { title: 'Asked for motion graphics', lines: [] }
    case 'approved_edit':
      return { title: 'Approved the edit', lines: [num(d.revision) ? `revision ${d.revision}` : ''] }
    case 'wrote_captions':
      return {
        title: d.writer === 'fallback' ? 'Drafted captions (offline template)' : 'Wrote caption options',
        lines: [],
        quote: str(d.tweak) ?? undefined,
      }
    case 'chose_caption':
      return { title: 'Picked a caption', lines: [num(d.option) ? `option ${d.option}` : ''] }
    case 'wrote_caption':
      return { title: 'Wrote their own caption', lines: [] }
    case 'confirmed_post_now':
      return { title: 'Confirmed: post now', lines: [] }
    case 'scheduled':
      return { title: 'Scheduled the post', lines: [str(d.at) ? `for ${fmtTime(d.at as string)}` : ''] }
    case 'unscheduled':
      return { title: 'Unscheduled', lines: [] }
    case 'published':
      return { title: 'Published to Instagram', lines: [], link: str(d.permalink) ?? undefined }
    case 'publish_blocked':
      return { title: 'Publish blocked by the approval gate', lines: [str(d.reason) ?? ''], warn: true }
    case 'publish_failed':
      return { title: 'Instagram rejected the post', lines: [str(d.error) ?? ''], warn: true }
    case 'failed':
      return { title: `Something failed${str(d.stage) ? ` while ${d.stage === 'captions' ? 'writing captions' : 'editing'}` : ''}`, lines: [str(d.error) ?? ''], warn: true }
    case 'saved_draft':
      return { title: 'Saved as draft', lines: [] }
    case 'discarded':
      return { title: 'Discarded', lines: [] }
    default:
      return { title: e.action.replace(/_/g, ' '), lines: [] }
  }
}

const ACTOR = {
  ai: { name: 'AI', icon: Bot, node: 'bg-brand-600 text-on-brand', label: 'text-brand-700' },
  human: { name: 'You', icon: UserIcon, node: 'bg-gold text-brand-900 dark:text-on-brand', label: 'text-ink' },
  system: { name: 'System', icon: Wrench, node: 'bg-surface-2 text-ink-soft border border-line', label: 'text-ink-soft' },
} as const

export default function CollabTimeline({ events, className = '' }: { events: TimelineEvent[]; className?: string }) {
  const ai = events.filter((e) => e.actor === 'ai').length
  const you = events.filter((e) => e.actor === 'human').length
  const total = Math.max(ai + you, 1)
  const span = events.length > 1 ? new Date(events[events.length - 1].at).getTime() - new Date(events[0].at).getTime() : 0

  return (
    <section aria-labelledby="collab-title" className={`rounded-2xl border border-line bg-surface p-4 sm:p-5 ${className}`}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id="collab-title" className="font-display text-xl font-semibold text-ink">
            Who did what
          </h2>
          <p className="text-xs text-ink-faint">Every step is logged. The AI does the work, you make the calls.</p>
        </div>
        {span > 0 && <span className="text-xs text-ink-faint">{fmtGap(span)} start to finish</span>}
      </div>

      {events.length > 0 && (
        <div className="mt-3">
          <div className="flex h-2 overflow-hidden rounded-full bg-surface-2" role="img" aria-label={`AI took ${ai} steps, you made ${you} decisions`}>
            <span className="h-full bg-brand-500" style={{ width: `${(ai / total) * 100}%` }} />
            <span className="h-full bg-gold" style={{ width: `${(you / total) * 100}%` }} />
          </div>
          <div className="mt-1.5 flex justify-between text-xs font-semibold">
            <span className="inline-flex items-center gap-1 text-brand-700">
              <Bot className="h-3.5 w-3.5" aria-hidden /> AI · {ai} {ai === 1 ? 'step' : 'steps'}
            </span>
            <span className="inline-flex items-center gap-1 text-ink-soft">
              You · {you} {you === 1 ? 'decision' : 'decisions'} <UserIcon className="h-3.5 w-3.5" aria-hidden />
            </span>
          </div>
        </div>
      )}

      {events.length === 0 ? (
        <p className="mt-4 text-sm text-ink-faint">Nothing yet. Steps appear here as they happen.</p>
      ) : (
        <ol className="relative mt-5 space-y-4">
          <span aria-hidden className="absolute top-2 bottom-2 left-4 w-px bg-line sm:left-1/2 sm:-translate-x-1/2" />
          {events.map((e, i) => {
            const a = ACTOR[e.actor] || ACTOR.system
            const info = describe(e)
            const Icon = info.warn ? AlertTriangle : a.icon
            const gap = i > 0 ? new Date(e.at).getTime() - new Date(events[i - 1].at).getTime() : 0
            const right = e.actor === 'human'
            const lines = info.lines.filter(Boolean)
            return (
              <li key={`${e.at}-${i}`} className="relative grid grid-cols-[2rem_1fr] gap-3 sm:grid-cols-[1fr_2rem_1fr]">
                <span
                  className={`relative z-10 col-start-1 row-start-1 grid h-8 w-8 place-items-center rounded-full shadow-sm ring-4 ring-surface sm:col-start-2 ${
                    info.warn ? 'border border-danger bg-danger-soft text-danger' : a.node
                  }`}
                >
                  <Icon className="h-4 w-4" aria-hidden />
                </span>
                <div className={`col-start-2 row-start-1 min-w-0 ${right ? 'sm:col-start-3' : 'sm:col-start-1 sm:text-right'}`}>
                  <div className="text-sm leading-snug">
                    <span className={`font-bold ${a.label}`}>{a.name}</span>
                    <span className="text-ink"> {info.title.charAt(0).toLowerCase() + info.title.slice(1)}</span>
                  </div>
                  <div className="mt-0.5 text-xs text-ink-faint">
                    <time dateTime={e.at}>{fmtTime(e.at)}</time>
                    {gap >= 1000 && <span> · {fmtGap(gap)} later</span>}
                    {lines.length > 0 && <span> · {lines.join(' · ')}</span>}
                  </div>
                  {info.quote && (
                    <blockquote className="mt-1.5 inline-block max-w-full rounded-xl bg-surface-2 px-3 py-1.5 text-left text-sm break-words text-ink-soft italic">
                      “{info.quote}”
                    </blockquote>
                  )}
                  {info.bullets && info.bullets.length > 0 && (
                    <details className="group mt-1.5">
                      <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-md text-xs font-semibold text-brand-700 hover:underline focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:outline-none [&::-webkit-details-marker]:hidden">
                        <span className="group-open:hidden">Show the {info.bullets.length} edits</span>
                        <span className="hidden group-open:inline">Hide edits</span>
                      </summary>
                      <ul className="mt-1.5 space-y-1 rounded-xl bg-surface-2 p-3 text-left text-xs text-ink-soft">
                        {info.bullets.map((b) => (
                          <li key={b} className="flex gap-2">
                            <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-brand-500" />
                            <span>{b}</span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {info.link && (
                    <a
                      href={info.link}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-1 inline-flex items-center gap-1 rounded-md text-xs font-semibold text-brand-700 hover:underline focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:outline-none"
                    >
                      Open on Instagram <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                    </a>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}
