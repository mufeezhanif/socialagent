import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Bot, User as UserIcon, X } from 'lucide-react'

/*
 * A short, quiet "baton pass" card that appears when the human clears a gate (edit approved, caption chosen,
 * post scheduled) and when the Reel goes live. It watches the draft for transitions, so it never fires on page
 * load, only on changes seen while the page is open. Respects prefers-reduced-motion.
 */

export interface HandoffDraft {
  id?: string
  status: string
  revision?: number
  publish_at?: string | null
  gates: { video_approved: boolean; caption_approved: boolean; publish_confirmed: boolean }
  events?: { actor: 'ai' | 'human' | 'system' }[]
}

interface Moment {
  id: number
  title: string
  body: string
  next: { actor: 'ai' | 'human'; text: string } | null
}

interface Snapshot {
  id?: string
  status: string
  video: boolean
  caption: boolean
}

function fmtWhen(iso: string | null | undefined) {
  if (!iso) return 'at the time you picked'
  return new Date(iso).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

function reducedMotion() {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return true
  }
}

function detect(prev: Snapshot, d: HandoffDraft): Omit<Moment, 'id'> | null {
  if (prev.status !== 'published' && d.status === 'published') {
    const you = d.events?.filter((e) => e.actor === 'human').length ?? 0
    const ai = d.events?.filter((e) => e.actor === 'ai').length ?? 0
    return {
      title: 'Live on Instagram',
      body: you && ai ? `Raw clip to Reel: the AI took ${ai} steps, you made ${you} calls.` : 'Raw clip to Reel, posted with your sign-off.',
      next: null,
    }
  }
  if (prev.status !== 'scheduled' && d.status === 'scheduled') {
    return { title: 'Scheduled', body: 'Your Reel is approved and queued.', next: { actor: 'ai', text: `AI posts it ${fmtWhen(d.publish_at)}` } }
  }
  if (!prev.caption && d.gates.caption_approved) {
    return { title: 'Caption locked in', body: 'Two of three approvals done. The last call is yours: post now or schedule it.', next: null }
  }
  if (!prev.video && d.gates.video_approved) {
    return {
      title: d.revision && d.revision > 1 ? `Revision ${d.revision} approved` : 'Edit approved',
      body: 'Nice. Handing it back to the agent.',
      next: { actor: 'ai', text: 'AI writes caption options in your brand voice' },
    }
  }
  return null
}

export default function HandoffMoment({ draft, duration = 5000 }: { draft: HandoffDraft; duration?: number }) {
  const prev = useRef<Snapshot | null>(null)
  const [moment, setMoment] = useState<Moment | null>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  const checkRef = useRef<SVGPathElement>(null)
  const ringRef = useRef<SVGCircleElement>(null)

  const { id, status, gates } = draft
  useEffect(() => {
    const now: Snapshot = { id, status, video: gates.video_approved, caption: gates.caption_approved }
    const before = prev.current
    prev.current = now
    if (!before || before.id !== id) return
    const found = detect(before, draft)
    if (found) setMoment({ ...found, id: Date.now() })
    // Deliberately keyed on the gate fields only: polling hands us a new draft object every few seconds.
  }, [id, status, gates.video_approved, gates.caption_approved])

  useEffect(() => {
    if (!moment) return
    const t = window.setTimeout(() => setMoment(null), duration)
    if (!reducedMotion()) {
      cardRef.current?.animate(
        [
          { opacity: 0, transform: 'translateY(-12px) scale(0.98)' },
          { opacity: 1, transform: 'translateY(0) scale(1)' },
        ],
        { duration: 320, easing: 'cubic-bezier(.2,.8,.2,1)' },
      )
      ringRef.current?.animate([{ strokeDashoffset: 76 }, { strokeDashoffset: 0 }], { duration: 520, easing: 'ease-out', fill: 'both' })
      checkRef.current?.animate([{ strokeDashoffset: 24 }, { strokeDashoffset: 24, offset: 0.45 }, { strokeDashoffset: 0 }], {
        duration: 760,
        easing: 'ease-out',
        fill: 'both',
      })
    }
    return () => window.clearTimeout(t)
  }, [moment, duration])

  return (
    <div aria-live="polite" role="status" className="pointer-events-none fixed inset-x-0 top-20 z-40 flex justify-center px-4">
      {moment && (
        <div
          key={moment.id}
          ref={cardRef}
          className="pointer-events-auto w-full max-w-sm overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl"
        >
          <div aria-hidden className="h-1 bg-gradient-to-r from-brand-500 via-gold to-brand-500" />
          <div className="flex gap-3 p-4">
            <svg viewBox="0 0 28 28" className="h-11 w-11 shrink-0 text-brand-600" aria-hidden>
              <circle cx="14" cy="14" r="12" fill="none" className="stroke-line" strokeWidth="2" />
              <circle
                ref={ringRef}
                cx="14"
                cy="14"
                r="12"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeDasharray="76"
                strokeDashoffset="0"
                transform="rotate(-90 14 14)"
              />
              <path
                ref={checkRef}
                d="M8.5 14.5l3.6 3.6 7.4-7.6"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeDasharray="24"
                strokeDashoffset="0"
              />
            </svg>
            <div className="min-w-0 flex-1">
              <div className="flex items-start justify-between gap-2">
                <p className="font-display text-xl leading-tight font-semibold text-ink">{moment.title}</p>
                <button
                  type="button"
                  onClick={() => setMoment(null)}
                  aria-label="Dismiss"
                  className="-mt-1 -mr-1 rounded-lg p-1 text-ink-faint hover:bg-surface-2 hover:text-ink focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:outline-none"
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
              </div>
              <p className="mt-0.5 text-sm text-ink-soft">{moment.body}</p>
              {moment.next && (
                <div className="mt-2.5 flex items-center gap-2 text-xs font-semibold">
                  <span className="inline-flex items-center gap-1 rounded-full bg-gold px-2 py-0.5 text-brand-900 dark:text-on-brand">
                    <UserIcon className="h-3 w-3" aria-hidden /> You
                  </span>
                  <ArrowRight className="h-3.5 w-3.5 shrink-0 text-ink-faint" aria-hidden />
                  <span
                    className={`inline-flex min-w-0 items-center gap-1 rounded-full px-2 py-0.5 ${
                      moment.next.actor === 'ai' ? 'bg-brand-600 text-on-brand' : 'bg-gold text-brand-900 dark:text-on-brand'
                    }`}
                  >
                    {moment.next.actor === 'ai' ? <Bot className="h-3 w-3 shrink-0" aria-hidden /> : <UserIcon className="h-3 w-3 shrink-0" aria-hidden />}
                    <span className="truncate">{moment.next.text}</span>
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
