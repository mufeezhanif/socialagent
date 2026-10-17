import { Link } from 'react-router-dom'
import { ArrowRight, Bot, Camera, MessageCircle, Send, ThumbsUp } from 'lucide-react'

/*
 * First-run empty state for the dashboard: the four-beat loop (send, AI edits, you approve, it posts)
 * with the next sensible action. Pass whether WhatsApp is linked so the primary button points the right way.
 */

const BEATS = [
  { icon: MessageCircle, who: 'You', title: 'Send a raw clip', text: 'On WhatsApp, like texting a friend.', tone: 'bg-wa text-white' },
  { icon: Bot, who: 'AI', title: 'It edits', text: 'Trims filler, frames 9:16, adds captions.', tone: 'bg-brand-600 text-on-brand' },
  { icon: ThumbsUp, who: 'You', title: 'You approve', text: 'Change anything in plain words.', tone: 'bg-gold text-brand-900 dark:text-on-brand' },
  { icon: Camera, who: 'AI', title: 'It posts', text: 'Now or on your schedule.', tone: 'ig-gradient text-white' },
]

export default function EmptyDrafts({ whatsappLinked, className = '' }: { whatsappLinked: boolean; className?: string }) {
  return (
    <section aria-labelledby="empty-title" className={`rounded-2xl border border-line bg-surface px-5 py-10 text-center sm:px-10 ${className}`}>
      <p className="font-script text-2xl text-brand-600">Your first Reel</p>
      <h2 id="empty-title" className="mt-1 font-display text-3xl font-semibold text-ink sm:text-4xl">
        is one clip away
      </h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-ink-soft">The agent does the editing. Nothing goes live until you say so.</p>

      <ol className="mx-auto mt-8 grid max-w-3xl grid-cols-2 gap-x-4 gap-y-6 text-left sm:grid-cols-4">
        {BEATS.map((b, i) => (
          <li key={b.title} className="relative">
            <div className="flex items-center gap-2">
              <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-2xl shadow-sm ${b.tone}`}>
                <b.icon className="h-5 w-5" aria-hidden />
              </span>
              {i < BEATS.length - 1 && <span aria-hidden className="hidden h-px flex-1 bg-line sm:block" />}
            </div>
            <div className="mt-2 text-[10px] font-bold tracking-wider text-ink-faint uppercase">
              {i + 1} · {b.who}
            </div>
            <div className="text-sm font-semibold text-ink">{b.title}</div>
            <div className="text-xs text-ink-soft">{b.text}</div>
          </li>
        ))}
      </ol>

      <div className="mt-8 flex flex-col items-center justify-center gap-2 sm:flex-row">
        {whatsappLinked ? (
          <span className="inline-flex items-center gap-2 rounded-xl bg-wa/10 px-4 py-2.5 text-sm font-semibold text-wa-dark dark:text-wa">
            <Send className="h-4 w-4" aria-hidden /> WhatsApp is linked. Send the bot a clip.
          </span>
        ) : (
          <Link
            to="/onboarding"
            className="inline-flex items-center gap-2 rounded-xl bg-wa px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:brightness-95 focus-visible:ring-2 focus-visible:ring-wa focus-visible:ring-offset-2 focus-visible:ring-offset-surface focus-visible:outline-none"
          >
            <MessageCircle className="h-4 w-4" aria-hidden /> Link WhatsApp
          </Link>
        )}
        <Link
          to="/app/chat"
          className="inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-semibold text-brand-700 transition hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:outline-none"
        >
          Or upload in the web chat <ArrowRight className="h-4 w-4" aria-hidden />
        </Link>
      </div>
    </section>
  )
}
