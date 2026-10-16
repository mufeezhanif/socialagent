import { Link } from 'react-router-dom'
import { CheckCircle2, MessageCircle, Scissors, Send, ShieldCheck, Sparkles, UserCheck } from 'lucide-react'
import { Logo } from '../ui'

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

export default function Landing() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-brand-50 via-white to-white">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5">
        <Logo />
        <div className="flex items-center gap-2">
          <Link to="/login" className="rounded-xl px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-white">
            Log in
          </Link>
          <Link to="/signup" className="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
            Get started
          </Link>
        </div>
      </header>

      <section className="mx-auto grid max-w-6xl items-center gap-10 px-4 pt-10 pb-16 md:grid-cols-2">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1 text-xs font-semibold text-brand-700 shadow-sm ring-1 ring-brand-100">
            <Sparkles className="h-3.5 w-3.5" /> Human + AI: better together
          </span>
          <h1 className="mt-5 text-4xl font-black leading-tight tracking-tight md:text-5xl">
            Send a raw clip on WhatsApp.
            <br />
            <span className="text-brand-600">Get a Reel worth posting.</span>
          </h1>
          <p className="mt-5 max-w-lg text-lg text-slate-600">
            Your AI editor cuts, captions and frames your video, writes the caption and posts it to Instagram. You stay in
            control of every decision that matters.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/signup" className="rounded-xl bg-brand-600 px-6 py-3 font-semibold text-white shadow-lg shadow-brand-600/20 hover:bg-brand-700">
              Create free account
            </Link>
            <Link to="/login" className="rounded-xl bg-white px-6 py-3 font-semibold text-slate-800 shadow-sm ring-1 ring-slate-200 hover:bg-slate-50">
              I have an account
            </Link>
          </div>
        </div>
        <div className="mx-auto w-full max-w-sm">
          <div className="chat-bg rounded-[2rem] border-8 border-slate-900 p-4 shadow-2xl">
            <div className="space-y-2 text-sm">
              <div className="ml-auto w-fit max-w-[80%] rounded-xl rounded-tr-sm bg-[#d9fdd3] px-3 py-2 shadow-sm">🎥 raw_clip.mp4 · "weekend sale"</div>
              <div className="w-fit max-w-[85%] rounded-xl rounded-tl-sm bg-white px-3 py-2 shadow-sm">🎬 Got it! Editing now...</div>
              <div className="w-fit max-w-[85%] rounded-xl rounded-tl-sm bg-white px-3 py-2 shadow-sm">
                ✨ <b>Edit ready</b> (48s → 34s)
                <br />• Cut 14s of pauses
                <br />• Captions + hook
                <br />
                <br />1 ✅ approve · 2 ✏️ change
              </div>
              <div className="ml-auto w-fit rounded-xl rounded-tr-sm bg-[#d9fdd3] px-3 py-2 shadow-sm">👍</div>
              <div className="w-fit max-w-[85%] rounded-xl rounded-tl-sm bg-white px-3 py-2 shadow-sm">🎉 Live on Instagram</div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-16">
        <div className="grid gap-4 md:grid-cols-4">
          {steps.map((s, i) => (
            <div key={s.title} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-2 text-brand-600">
                <s.icon className="h-5 w-5" />
                <span className="text-xs font-bold text-slate-400">STEP {i + 1}</span>
              </div>
              <h3 className="mt-3 font-bold">{s.title}</h3>
              <p className="mt-1 text-sm text-slate-600">{s.text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-20">
        <div className="rounded-3xl bg-slate-900 p-8 text-white md:p-10">
          <div className="flex items-center gap-2 text-brand-100">
            <ShieldCheck className="h-5 w-5" /> <span className="text-sm font-semibold">Built-in human approval</span>
          </div>
          <h2 className="mt-3 text-2xl font-bold md:text-3xl">The AI does 90% of the work. You make the calls that need taste.</h2>
          <ul className="mt-6 grid gap-3 md:grid-cols-2">
            {gates.map((g) => (
              <li key={g} className="flex items-start gap-2 text-slate-200">
                <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-wa" /> {g}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <footer className="border-t border-slate-200 py-6 text-center text-sm text-slate-500">
        <Link to="/privacy" className="hover:underline">Privacy</Link> · <Link to="/terms" className="hover:underline">Terms</Link> ·{' '}
        <Link to="/data-deletion" className="hover:underline">Data deletion</Link>
      </footer>
    </div>
  )
}
