import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Bot, CheckCircle2, Circle, ExternalLink, RefreshCw, Sparkles, User as UserIcon, Wrench } from 'lucide-react'
import { toast } from 'sonner'
import { api, WORKING, type DraftDetail } from '../api'
import { Button, Card, fmtDate, Input, Spinner, StatusBadge, Textarea } from '../ui'

const STYLES = ['clean', 'hype', 'cinematic', 'funny', 'deadpan', 'luxury']
const ACTION_LABELS: Record<string, string> = {
  sent_video: 'Sent a video',
  edited_video: 'Edited the video',
  requested_changes: 'Asked for changes',
  requested_style: 'Asked for another style',
  approved_edit: 'Approved the edit',
  wrote_captions: 'Wrote caption options',
  chose_caption: 'Picked a caption',
  wrote_caption: 'Wrote their own caption',
  confirmed_post_now: 'Confirmed: post now',
  scheduled: 'Scheduled the post',
  unscheduled: 'Unscheduled',
  published: 'Published to Instagram',
  publish_blocked: 'Publish blocked by approval gate',
  publish_failed: 'Instagram rejected the post',
  failed: 'Something failed',
  saved_draft: 'Saved as draft',
  discarded: 'Discarded',
}

function toLocalInput(date: Date) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export default function DraftDetailPage() {
  const { id } = useParams()
  const qc = useQueryClient()
  const key = ['draft', id]
  const q = useQuery({
    queryKey: key,
    queryFn: () => api<DraftDetail>(`/api/drafts/${id}`),
    refetchInterval: (query) => (query.state.data && WORKING.has(query.state.data.status) ? 2500 : 6000),
  })
  const [notes, setNotes] = useState('')
  const [own, setOwn] = useState('')
  const [tweak, setTweak] = useState('')
  const [when, setWhen] = useState(() => toLocalInput(new Date(Date.now() + 60 * 60 * 1000)))
  const [busy, setBusy] = useState<string | null>(null)
  const [showOriginal, setShowOriginal] = useState(false)

  const act = async (name: string, path: string, json: unknown = {}) => {
    setBusy(name)
    try {
      const data = await api<DraftDetail>(`/api/drafts/${id}/${path}`, { method: 'POST', json })
      qc.setQueryData(key, data)
      qc.invalidateQueries({ queryKey: ['drafts'] })
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (q.isLoading) return <Spinner />
  if (q.isError || !q.data) return <p>Draft not found.</p>
  const d = q.data
  const st = d.status
  const working = WORKING.has(st)
  const reviewing = st === 'awaiting_video_approval' || st === 'awaiting_change_notes'
  const captionStage = ['awaiting_caption_choice', 'awaiting_publish_choice', 'awaiting_schedule_time', 'saved'].includes(st)
  const canPublish = d.gates.video_approved && d.gates.caption_approved && ['awaiting_publish_choice', 'awaiting_schedule_time', 'saved'].includes(st)
  const pack = d.caption_pack
  const question = d.storyboard?.question_for_user as string | undefined

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link to="/app" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold">Draft</h1>
              <StatusBadge status={st} label={d.status_label} />
            </div>
            <p className="text-xs text-slate-500">
              {fmtDate(d.created_at)} · via {d.channel} · style {d.style} · revision {d.revision}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          {!['published', 'discarded', 'saved'].includes(st) && !working && (
            <Button variant="secondary" onClick={() => act('save', 'save')} loading={busy === 'save'}>
              Save for later
            </Button>
          )}
          {st !== 'published' && st !== 'discarded' && (
            <Button variant="danger" onClick={() => act('discard', 'discard')} loading={busy === 'discard'}>
              Discard
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,380px)_1fr]">
        <div className="space-y-3">
          <div className="overflow-hidden rounded-2xl bg-black shadow-lg">
            {working && !d.master_url ? (
              <div className="grid aspect-[9/16] place-items-center text-white">
                <div className="text-center">
                  <Spinner className="mx-auto text-white" />
                  <p className="mt-3 text-sm">{d.status_label}</p>
                </div>
              </div>
            ) : (
              <video
                key={(showOriginal ? d.source_url : d.master_url) || 'none'}
                src={(showOriginal ? d.source_url : d.master_url) || undefined}
                controls
                playsInline
                className="aspect-[9/16] w-full bg-black object-contain"
              />
            )}
          </div>
          {d.source_url && d.master_url && (
            <div className="flex rounded-xl bg-slate-100 p-1 text-sm font-semibold">
              <button onClick={() => setShowOriginal(false)} className={`flex-1 rounded-lg py-1.5 ${!showOriginal ? 'bg-white shadow-sm' : 'text-slate-500'}`}>
                AI edit {d.duration_out ? `· ${Math.round(d.duration_out)}s` : ''}
              </button>
              <button onClick={() => setShowOriginal(true)} className={`flex-1 rounded-lg py-1.5 ${showOriginal ? 'bg-white shadow-sm' : 'text-slate-500'}`}>
                Original {d.duration_in ? `· ${Math.round(d.duration_in)}s` : ''}
              </button>
            </div>
          )}
        </div>

        <div className="space-y-4">
          {working && (
            <Card className="flex items-center gap-3">
              <Spinner /> <span className="font-medium">{d.status_label}…</span>
            </Card>
          )}

          {st === 'failed' && (
            <Card className="border-red-200">
              <p className="font-semibold text-red-700">Something went wrong ({d.failed_stage}).</p>
              <p className="mt-1 text-sm text-slate-600">{d.error}</p>
              <Button className="mt-3" onClick={() => act('retry', 'retry')} loading={busy === 'retry'}>
                <RefreshCw className="h-4 w-4" /> Retry
              </Button>
            </Card>
          )}

          {d.edit_summary.length > 0 && (
            <Card>
              <h2 className="flex items-center gap-2 font-bold">
                <Sparkles className="h-4 w-4 text-brand-600" /> What the AI editor did
              </h2>
              <ul className="mt-2 space-y-1 text-sm text-slate-700">
                {d.edit_summary.map((b) => (
                  <li key={b}>• {b}</li>
                ))}
              </ul>
              {question && <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">❓ {question}</p>}
            </Card>
          )}

          {reviewing && (
            <Card className="space-y-3 border-brand-200">
              <h2 className="font-bold">Your call: is this edit good?</h2>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => act('approve', 'approve')} loading={busy === 'approve'}>
                  ✅ Approve edit
                </Button>
                {STYLES.filter((s) => s !== d.style).map((s) => (
                  <Button key={s} variant="secondary" onClick={() => act(`style-${s}`, 'style', { style: s })} loading={busy === `style-${s}`}>
                    🎨 {s}
                  </Button>
                ))}
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder='Ask for changes, e.g. "cut the first 3 seconds", "no hook"' />
                <Button variant="secondary" disabled={!notes.trim()} loading={busy === 'changes'} onClick={() => act('changes', 'changes', { notes }).then(() => setNotes(''))}>
                  <Wrench className="h-4 w-4" /> Apply
                </Button>
              </div>
            </Card>
          )}

          {st === 'awaiting_context' && (
            <Card className="space-y-3 border-brand-200">
              <h2 className="font-bold">Anything the caption should mention?</h2>
              <Textarea rows={2} value={tweak} onChange={(e) => setTweak(e.target.value)} placeholder="Offer, link, location... or leave empty" />
              <Button onClick={() => act('captions', 'captions/regenerate', { tweak: tweak ? `Include these details: ${tweak}` : null })} loading={busy === 'captions'}>
                Write captions
              </Button>
            </Card>
          )}

          {captionStage && pack && (
            <Card className="space-y-3">
              <h2 className="font-bold">{d.gates.caption_approved ? 'Caption' : 'Pick a caption'}</h2>
              {d.gates.caption_approved && d.caption_final && (
                <div className="rounded-xl bg-emerald-50 p-3 text-sm whitespace-pre-wrap text-emerald-900">
                  {d.caption_final}
                  <div className="mt-2 text-emerald-700">{d.hashtags_final.map((t) => `#${t}`).join(' ')}</div>
                </div>
              )}
              <div className="grid gap-3 md:grid-cols-3">
                {pack.options.map((o, i) => (
                  <div key={i} className="flex flex-col rounded-xl border border-slate-200 p-3">
                    <div className="text-xs font-bold text-slate-400 uppercase">{o.style}</div>
                    <p className="mt-1 flex-1 text-sm whitespace-pre-wrap">{o.text}</p>
                    <Button variant="secondary" className="mt-3" onClick={() => act(`cap-${i}`, 'caption', { option: i + 1 })} loading={busy === `cap-${i}`}>
                      Use this
                    </Button>
                  </div>
                ))}
              </div>
              <p className="text-sm text-slate-500">{pack.hashtags.map((t) => `#${t}`).join(' ')}</p>
              {pack.facts_to_confirm.length > 0 && (
                <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">⚠️ Double-check: {pack.facts_to_confirm.join('; ')}</p>
              )}
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input value={tweak} onChange={(e) => setTweak(e.target.value)} placeholder='Tweak, e.g. "shorter", "more playful"' />
                <Button variant="secondary" disabled={!tweak.trim()} loading={busy === 'regen'} onClick={() => act('regen', 'captions/regenerate', { tweak }).then(() => setTweak(''))}>
                  Rewrite
                </Button>
              </div>
              <Textarea rows={3} value={own} onChange={(e) => setOwn(e.target.value)} placeholder="Or write your own caption" />
              <Button variant="secondary" disabled={!own.trim()} loading={busy === 'own'} onClick={() => act('own', 'caption', { text: own })}>
                Use my caption
              </Button>
            </Card>
          )}

          {canPublish && (
            <Card className="space-y-3 border-brand-200">
              <h2 className="font-bold">Post it</h2>
              <div className="flex flex-wrap items-center gap-2">
                <Button onClick={() => act('now', 'publish', { mode: 'now' })} loading={busy === 'now'}>
                  🚀 Post now
                </Button>
                <span className="text-sm text-slate-400">or</span>
                <Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} className="w-auto" />
                <Button variant="secondary" onClick={() => act('schedule', 'publish', { mode: 'schedule', publish_at: new Date(when).toISOString() })} loading={busy === 'schedule'}>
                  🗓 Schedule
                </Button>
              </div>
            </Card>
          )}

          {st === 'scheduled' && (
            <Card className="flex flex-wrap items-center justify-between gap-3 border-sky-200">
              <div>
                <div className="font-bold">Scheduled</div>
                <div className="text-sm text-slate-600">Posts {fmtDate(d.publish_at)}</div>
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => act('unschedule', 'unschedule')} loading={busy === 'unschedule'}>
                  Unschedule
                </Button>
              </div>
            </Card>
          )}

          {st === 'published' && d.ig_permalink && (
            <Card className="border-emerald-200">
              <div className="font-bold text-emerald-700">🎉 Live on Instagram</div>
              <a href={d.ig_permalink} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-sm font-semibold text-brand-600">
                Open post <ExternalLink className="h-4 w-4" />
              </a>
            </Card>
          )}

          <Card>
            <h2 className="font-bold">Approval gates</h2>
            <ul className="mt-2 space-y-1.5 text-sm">
              {[
                ['Edit approved by you', d.gates.video_approved],
                ['Caption approved by you', d.gates.caption_approved],
                ['Posting confirmed by you', d.gates.publish_confirmed],
              ].map(([label, ok]) => (
                <li key={label as string} className="flex items-center gap-2">
                  {ok ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <Circle className="h-4 w-4 text-slate-300" />} {label}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-slate-500">Nothing reaches Instagram until all three are ticked for the current revision.</p>
          </Card>

          <Card>
            <h2 className="font-bold">Timeline: who did what</h2>
            <ol className="mt-3 space-y-2.5">
              {d.events.map((e, i) => (
                <li key={i} className="flex gap-3 text-sm">
                  <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full ${e.actor === 'ai' ? 'bg-brand-100 text-brand-700' : e.actor === 'human' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
                    {e.actor === 'ai' ? <Bot className="h-4 w-4" /> : e.actor === 'human' ? <UserIcon className="h-4 w-4" /> : <Wrench className="h-4 w-4" />}
                  </span>
                  <div>
                    <div className="font-medium">
                      {e.actor === 'ai' ? 'AI' : e.actor === 'human' ? 'You' : 'System'}: {ACTION_LABELS[e.action] || e.action}
                    </div>
                    <div className="text-xs text-slate-500">
                      {fmtDate(e.at)}
                      {typeof e.detail?.notes === 'string' && ` · "${e.detail.notes}"`}
                      {typeof e.detail?.style === 'string' && ` · ${e.detail.style}`}
                      {typeof e.detail?.seconds === 'number' && ` · ${e.detail.seconds}s`}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </Card>

          {d.transcript && (
            <details className="rounded-2xl border border-slate-200 bg-white p-5 text-sm shadow-sm">
              <summary className="cursor-pointer font-bold">Transcript</summary>
              <p className="mt-2 text-slate-600">{d.transcript}</p>
            </details>
          )}
        </div>
      </div>
    </div>
  )
}
