import { Link } from 'react-router-dom'
import { CheckCircle2, MessageCircle, Scissors, Send, ShieldCheck, Sparkles, UserCheck } from 'lucide-react'
import { Logo } from '../ui'
import { ThemeToggle } from '../theme'

const steps = [
  { icon: MessageCircle, title: 'Send a raw clip', text: 'Drop any video into WhatsApp, the app you already use every day.' },
  { icon: Scissors, title: 'AI edits it', text: 'Pauses and filler cut, vertical 9:16, word-by-word captions, hook, clean audio.' },
  { icon: UserCheck, title: 'You approve', text: 'Reply 1 to approve, or ask for changes by text or voice note.' },
  { icon: Send, title: 'It goes live', text: 'Pick a caption, then post to Instagram now or schedule it.' },
]

const gates = [
  'You approve every edit before it moves on',
  'You choose or write the caption: the AI never invents prices, dates or claims',
  'Nothing posts until you say post now or pick a time',
  'Every AI step is explained and logged',
]

const bubbleIn = 'w-fit max-w-[85%] rounded-xl rounded-tl-sm bg-surface px-3 py-2 text-ink shadow-xs'
const bubbleOut = 'ml-auto w-fit max-w-[80%] rounded-xl rounded-tr-sm bg-bubble px-3 py-2 text-ink shadow-xs'

export default function Landing() {
  return (
    <div className="min-h-screen overflow-x-hidden">
      <header className="mx-auto flex max-w-6xl items-center justify-between gap-2 px-4 py-5">
        <Logo />
        <div className="flex items-center gap-1.5 sm:gap-2">
          <ThemeToggle />
          <Link to="/login" className="hidden rounded-full px-4 py-2 text-sm font-semibold text-ink-soft transition hover:bg-surface hover:text-ink sm:inline-flex">
            Log in
          </Link>
          <Link to="/signup" className="rounded-full bg-brand-600 px-4 py-2 text-sm font-semibold whitespace-nowrap text-on-brand shadow-sm transition hover:bg-brand-700">
            Get started
          </Link>
        </div>
      </header>

      <section className="mx-auto grid max-w-6xl items-center gap-12 px-4 pt-8 pb-16 md:grid-cols-2 md:pt-12">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-surface px-3 py-1 text-xs font-semibold text-brand-700 shadow-xs ring-1 ring-brand-200">
            <Sparkles className="h-3.5 w-3.5 text-gold" /> Human + AI: better together
          </span>
          <h1 className="mt-6 font-display text-[2.75rem] leading-[1.02] font-semibold tracking-tight text-ink sm:text-6xl">
            Send a raw clip on WhatsApp.
            <br />
            <span className="text-brand-600 italic">Get a Reel worth posting.</span>
          </h1>
          <p className="mt-6 max-w-lg text-lg leading-relaxed text-ink-soft">
            Your AI editor cuts, captions and frames your video, writes the caption and posts it to Instagram. You stay in
            control of every decision that matters.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/signup" className="rounded-full bg-brand-600 px-6 py-3 font-semibold text-on-brand shadow-lg transition hover:-translate-y-0.5 hover:bg-brand-700">
              Create free account
            </Link>
            <Link to="/login" className="rounded-full bg-surface px-6 py-3 font-semibold text-ink shadow-xs ring-1 ring-line transition hover:bg-surface-2">
              I have an account
            </Link>
          </div>
        </div>
        <div className="relative isolate mx-auto w-full max-w-sm">
          <div aria-hidden className="absolute -inset-6 -z-10 rounded-[3rem] bg-gradient-to-br from-brand-200/60 via-gold/20 to-transparent blur-2xl" />
          <div className="chat-bg rounded-[2.25rem] border-[10px] border-[#22170f] p-4 shadow-2xl ring-1 ring-gold/30 dark:border-[#0c0806]">
            <div className="space-y-2 text-sm">
              <div className={bubbleOut}>🎥 raw_clip.mp4 · "weekend sale"</div>
              <div className={bubbleIn}>🎬 Got it! Editing now...</div>
              <div className={bubbleIn}>
                ✨ <b>Edit ready</b> (48s → 34s)
                <br />• Cut 14s of pauses
                <br />• Captions + hook
                <br />
                <br />1 ✅ approve · 2 ✏️ change
              </div>
              <div className={bubbleOut}>👍</div>
              <div className={bubbleIn}>🎉 Live on Instagram</div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-16">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map((s, i) => (
            <div key={s.title} className="rounded-2xl border border-line bg-surface p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
              <div className="flex items-center justify-between">
                <span className="grid h-10 w-10 place-items-center rounded-full bg-brand-100 text-brand-700">
                  <s.icon className="h-5 w-5" />
                </span>
                <span className="font-display text-3xl font-semibold text-brand-300 italic">0{i + 1}</span>
              </div>
              <h3 className="mt-4 font-display text-2xl font-semibold">{s.title}</h3>
              <p className="mt-1 text-sm leading-relaxed text-ink-soft">{s.text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-20">
        <div className="relative overflow-hidden rounded-3xl bg-ink p-8 text-canvas shadow-xl md:p-12 dark:bg-surface dark:text-ink dark:ring-1 dark:ring-line">
          <div aria-hidden className="absolute -top-24 -right-24 h-72 w-72 rounded-full bg-gold/20 blur-3xl" />
          <div className="relative">
            <div className="flex items-center gap-2 text-gold">
              <ShieldCheck className="h-5 w-5" /> <span className="text-xs font-bold tracking-[0.16em] uppercase">Built-in human approval</span>
            </div>
            <h2 className="mt-4 max-w-3xl font-display text-3xl leading-tight font-semibold md:text-4xl">
              The AI does 90% of the work. You make the calls that need taste.
            </h2>
            <ul className="mt-8 grid gap-3 md:grid-cols-2">
              {gates.map((g) => (
                <li key={g} className="flex items-start gap-2 text-canvas/85 dark:text-ink-soft">
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-wa" /> {g}
                </li>
              ))}
            </ul>
            <p className="mt-8 text-right font-script text-4xl text-gold">Signed off by you.</p>
          </div>
        </div>
      </section>

      <footer className="border-t border-line py-6 text-center text-sm text-ink-faint">
        <Link to="/privacy" className="hover:text-ink hover:underline">Privacy</Link> · <Link to="/terms" className="hover:text-ink hover:underline">Terms</Link> ·{' '}
        <Link to="/data-deletion" className="hover:text-ink hover:underline">Data deletion</Link>
      </footer>
    </div>
  )
}
