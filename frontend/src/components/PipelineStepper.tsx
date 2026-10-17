import { AlertTriangle, Bot, Check, Clock, Film, Hand, MessageCircle, PenLine, Rocket, Scissors, ThumbsUp, User as UserIcon, type LucideIcon } from 'lucide-react'

/*
 * The draft journey as a relay between the creator and the agent:
 * You send → AI edits → You approve → AI writes captions → You pick + confirm → AI publishes.
 * Works from DraftSummary data (status only) or DraftDetail data (status + gates + failed_stage).
 */

type Actor = 'ai' | 'human'
export type StepState = 'done' | 'active' | 'waiting' | 'scheduled' | 'failed' | 'paused' | 'todo'

interface StepDef {
  id: string
  actor: Actor
  title: string
  icon: LucideIcon
}

const STEPS: StepDef[] = [
  { id: 'sent', actor: 'human', title: 'You send a clip', icon: MessageCircle },
  { id: 'edit', actor: 'ai', title: 'AI edits the Reel', icon: Scissors },
  { id: 'review', actor: 'human', title: 'You approve the edit', icon: ThumbsUp },
  { id: 'captions', actor: 'ai', title: 'AI writes captions', icon: PenLine },
  { id: 'confirm', actor: 'human', title: 'You pick and confirm', icon: Hand },
  { id: 'publish', actor: 'ai', title: 'AI posts to Instagram', icon: Rocket },
]

export interface PipelineInput {
  status: string
  gates?: { video_approved: boolean; caption_approved: boolean; publish_confirmed: boolean }
  failed_stage?: string | null
  caption_final?: string | null
  publish_at?: string | null
}

interface Position {
  index: number
  state: StepState
  note: string
}

function locate(d: PipelineInput): Position {
  switch (d.status) {
    case 'processing':
      return { index: 1, state: 'active', note: 'Cutting pauses, framing 9:16, adding captions. Usually about a minute.' }
    case 'revising':
      return { index: 1, state: 'active', note: 'Applying your notes to a new revision.' }
    case 'awaiting_video_approval':
      return { index: 2, state: 'waiting', note: 'Watch the edit. Approve it, ask for changes, or try another style.' }
    case 'awaiting_change_notes':
      return { index: 2, state: 'waiting', note: 'Tell the AI what to change, in plain words.' }
    case 'awaiting_context':
      return { index: 3, state: 'waiting', note: 'The AI wants a detail for the caption (offer, link, location). Optional.' }
    case 'captioning':
      return { index: 3, state: 'active', note: 'Writing caption options in your brand voice.' }
    case 'awaiting_caption_choice':
      return { index: 4, state: 'waiting', note: 'Pick a caption, tweak it, or write your own.' }
    case 'awaiting_publish_choice':
    case 'awaiting_schedule_time':
      return { index: 4, state: 'waiting', note: 'Post now or schedule it. Nothing goes live without this.' }
    case 'scheduled':
      return { index: 5, state: 'scheduled', note: d.publish_at ? `The agent will post it ${fmtWhen(d.publish_at)}.` : 'The agent will post it at the scheduled time.' }
    case 'publishing':
      return { index: 5, state: 'active', note: 'Uploading to Instagram.' }
    case 'published':
      return { index: 6, state: 'done', note: 'Live on Instagram.' }
    case 'failed': {
      const index = d.failed_stage === 'captions' ? 3 : 1
      return { index, state: 'failed', note: 'Something broke on the AI side. You can retry.' }
    }
    case 'saved': {
      const index = d.gates ? (d.gates.caption_approved ? 4 : d.gates.video_approved ? 4 : 2) : d.caption_final ? 4 : 2
      return { index, state: 'paused', note: 'Saved for later. Pick it up any time.' }
    }
    case 'discarded':
      return { index: 0, state: 'paused', note: 'Discarded.' }
    default:
      return { index: 1, state: 'active', note: '' }
  }
}

function fmtWhen(iso: string) {
  return new Date(iso).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

function stateOf(i: number, pos: Position): StepState {
  if (i < pos.index) return 'done'
  if (i === pos.index) return pos.state
  return 'todo'
}

const STATE_TEXT: Record<StepState, string> = {
  done: 'done',
  active: 'in progress',
  waiting: 'waiting for you',
  scheduled: 'scheduled',
  failed: 'failed',
  paused: 'paused',
  todo: 'not started',
}

function nodeClass(state: StepState) {
  switch (state) {
    case 'done':
      return 'bg-brand-600 text-on-brand border-brand-600'
    case 'active':
      return 'bg-surface text-brand-700 border-brand-500'
    case 'waiting':
      return 'bg-gold text-brand-900 dark:text-on-brand border-gold'
    case 'scheduled':
      return 'bg-surface text-brand-700 border-brand-400 border-dashed'
    case 'failed':
      return 'bg-surface text-danger border-danger'
    case 'paused':
      return 'bg-surface-2 text-ink-soft border-line'
    default:
      return 'bg-surface text-ink-faint border-line'
  }
}

function NodeIcon({ state, step }: { state: StepState; step: StepDef }) {
  if (state === 'done') return <Check className="h-4 w-4" strokeWidth={3} aria-hidden />
  if (state === 'failed') return <AlertTriangle className="h-4 w-4" aria-hidden />
  if (state === 'scheduled') return <Clock className="h-4 w-4" aria-hidden />
  const Icon = step.icon
  return <Icon className="h-4 w-4" aria-hidden />
}

/** Full stepper for the draft page: six nodes plus a "whose turn" headline. */
export default function PipelineStepper({ draft, className = '' }: { draft: PipelineInput; className?: string }) {
  const pos = locate(draft)
  const current = STEPS[Math.min(pos.index, STEPS.length - 1)]
  const yourTurn = pos.state === 'waiting'
  const aiTurn = pos.state === 'active' || pos.state === 'scheduled'
  const finished = draft.status === 'published'

  return (
    <section aria-label="Draft progress" className={`rounded-2xl border border-line bg-surface p-4 sm:p-5 ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold tracking-wide uppercase ${
              finished
                ? 'bg-brand-600 text-on-brand'
                : yourTurn
                  ? 'bg-gold text-brand-900 dark:text-on-brand'
                  : aiTurn
                    ? 'bg-brand-100 text-brand-800'
                    : pos.state === 'failed'
                      ? 'bg-danger-soft text-danger'
                      : 'bg-surface-2 text-ink-soft'
            }`}
          >
            {finished ? (
              <Film className="h-3.5 w-3.5" aria-hidden />
            ) : pos.state === 'failed' ? (
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
            ) : yourTurn ? (
              <UserIcon className="h-3.5 w-3.5" aria-hidden />
            ) : (
              <Bot className="h-3.5 w-3.5" aria-hidden />
            )}
            {finished ? 'Done together' : yourTurn ? 'Your move' : aiTurn ? 'AI is on it' : pos.state === 'failed' ? 'Needs a retry' : 'Paused'}
          </span>
          {pos.state === 'active' && (
            <span className="relative flex h-2 w-2" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-60 motion-reduce:animate-none" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-brand-500" />
            </span>
          )}
        </div>
        <span className="text-xs text-ink-faint">
          Step {Math.min(pos.index + 1, STEPS.length)} of {STEPS.length}
        </span>
      </div>

      <h2 className="mt-2 font-display text-2xl leading-tight font-semibold text-ink">{finished ? 'Posted. Nice work, team.' : current.title}</h2>
      {pos.note && <p className="mt-0.5 text-sm text-ink-soft">{pos.note}</p>}

      <ol className="mt-4 flex items-start" aria-label="Pipeline steps">
        {STEPS.map((step, i) => {
          const state = stateOf(i, pos)
          const last = i === STEPS.length - 1
          return (
            <li key={step.id} className="relative flex min-w-0 flex-1 flex-col items-center text-center" aria-current={i === pos.index ? 'step' : undefined}>
              {!last && (
                <span aria-hidden className="absolute top-[15px] right-[calc(-50%+1.25rem)] left-[calc(50%+1.25rem)] h-0.5 overflow-hidden rounded-full bg-line">
                  <span className={`block h-full rounded-full bg-brand-500 transition-[width] duration-700 motion-reduce:transition-none ${i < pos.index ? 'w-full' : 'w-0'}`} />
                </span>
              )}
              <span
                className={`relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full border-2 transition-colors ${nodeClass(state)} ${
                  state === 'waiting' ? 'ring-4 ring-gold/30' : state === 'active' ? 'ring-4 ring-brand-500/20' : ''
                }`}
                title={`${step.title}: ${STATE_TEXT[state]}`}
              >
                <NodeIcon state={state} step={step} />
                <span className="sr-only">
                  {step.title}: {STATE_TEXT[state]}
                </span>
              </span>
              <span
                className={`mt-1.5 text-[10px] font-bold tracking-wider uppercase ${
                  i === pos.index ? (step.actor === 'ai' ? 'text-brand-700' : 'text-ink') : 'text-ink-faint'
                }`}
                aria-hidden
              >
                {step.actor === 'ai' ? 'AI' : 'You'}
              </span>
              <span
                aria-hidden
                className={`hidden px-1 text-[11px] leading-tight font-semibold sm:block ${
                  i === pos.index ? 'text-ink' : state === 'done' ? 'text-ink-soft' : 'text-ink-faint'
                }`}
              >
                {step.title.replace(/^(You|AI) /, '')}
              </span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

/** Thin six-segment bar for draft cards on the dashboard. Uses DraftSummary fields only. */
export function PipelineMini({ draft, className = '' }: { draft: PipelineInput; className?: string }) {
  const pos = locate(draft)
  const label = `${STEPS[Math.min(pos.index, STEPS.length - 1)].title}: ${STATE_TEXT[pos.state]}`
  return (
    <div className={`flex items-center gap-1 ${className}`} role="img" aria-label={`Progress: ${label}`} title={label}>
      {STEPS.map((step, i) => {
        const state = stateOf(i, pos)
        const color =
          state === 'done'
            ? 'bg-brand-500'
            : state === 'waiting'
              ? 'bg-gold'
              : state === 'active' || state === 'scheduled'
                ? 'bg-brand-300 animate-pulse motion-reduce:animate-none'
                : state === 'failed'
                  ? 'bg-danger'
                  : 'bg-line'
        return <span key={step.id} className={`h-1 flex-1 rounded-full ${color}`} />
      })}
    </div>
  )
}

/** Who holds the ball right now, for badges and filters. */
export function whoseTurn(status: string): 'you' | 'ai' | 'none' {
  const { state } = locate({ status })
  if (state === 'waiting' || state === 'failed') return 'you'
  if (state === 'active' || state === 'scheduled') return 'ai'
  return 'none'
}
