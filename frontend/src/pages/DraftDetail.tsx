import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CheckCircle2, Circle, ExternalLink, RefreshCw, Sparkles, Wrench } from 'lucide-react'
import { toast } from 'sonner'
import { api, WORKING, type DraftDetail } from '../api'
import { Button, Card, fmtDate, Input, Spinner, StatusBadge, Textarea } from '../ui'
import { useMe } from '../App'
import PipelineStepper from '../components/PipelineStepper'
import CollabTimeline from '../components/CollabTimeline'
import ReelPreview from '../components/ReelPreview'
import HandoffMoment from '../components/HandoffMoment'
import KeyboardShortcuts, { type Hotkey } from '../components/KeyboardShortcuts'
import { DraftDetailSkeleton } from '../components/Skeletons'

const STYLES = ['clean', 'hype', 'cinematic', 'funny', 'deadpan', 'luxury']
function toLocalInput(date: Date) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export default function DraftDetailPage() {
  const { id } = useParams()
  const qc = useQueryClient()
  const me = useMe()
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
      return true
    } catch (err) {
      toast.error((err as Error).message)
      return false
    } finally {
      setBusy(null)
    }
  }

  if (q.isLoading) return <DraftDetailSkeleton />
  if (q.isError || !q.data) return <p>Draft not found.</p>
  const d = q.data
  const st = d.status
  const working = WORKING.has(st)
  const reviewing = st === 'awaiting_video_approval' || st === 'awaiting_change_notes'
  const captionStage = ['awaiting_caption_choice', 'awaiting_publish_choice', 'awaiting_schedule_time', 'saved'].includes(st)
  const canPublish = d.gates.video_approved && d.gates.caption_approved && ['awaiting_publish_choice', 'awaiting_schedule_time', 'saved'].includes(st)
  const pack = d.caption_pack
  const question = d.storyboard?.question_for_user as string | undefined
  const trace = (d.storyboard?.trace as string[] | undefined) || []
  const editorName = (d.storyboard?.editor as string | undefined) || 'rules'

  const pickable = captionStage && !d.gates.caption_approved && !!pack
  const hotkeys: Hotkey[] = [
    { key: 'a', label: 'Approve edit', enabled: reviewing && !busy, run: () => void act('approve', 'approve') },
    { key: 'r', label: 'Request changes', enabled: reviewing, run: () => document.getElementById('change-notes')?.focus() },
    ...[0, 1, 2].map((i) => ({
      key: String(i + 1),
      label: `Use caption ${i + 1}`,
      enabled: pickable && !busy && !!pack?.options[i],
      chip: i === 0,
      run: () => void act(`cap-${i}`, 'caption', { option: i + 1 }),
    })),
  ]

  return (
    <div className="space-y-5">
      <HandoffMoment draft={d} />
      <KeyboardShortcuts hotkeys={hotkeys} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Link to="/app" className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-line bg-surface text-ink-soft shadow-xs transition hover:bg-surface-2 hover:text-ink" aria-label="Back to drafts">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="font-display text-3xl leading-none font-semibold tracking-tight">Draft</h1>
              <StatusBadge status={st} label={d.status_label} />
            </div>
            <p className="mt-1 text-xs text-ink-faint">
              {fmtDate(d.created_at)} · via {d.channel} · style {d.style} · revision {d.revision}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
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

      <PipelineStepper draft={d} />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,380px)_1fr]">
        <div className="space-y-3">
          <ReelPreview
            videoUrl={(showOriginal ? d.source_url : d.master_url) || null}
            posterUrl={d.cover_url}
            username={me.data?.instagram?.username}
            avatarUrl={me.data?.instagram?.profile_picture_url}
            caption={showOriginal ? null : d.caption_final}
            hashtags={showOriginal ? [] : d.hashtags_final}
            busyLabel={working ? d.status_label : null}
            badge={showOriginal ? 'Original clip · as you sent it' : st === 'published' ? 'Live on Instagram' : 'Preview · not posted yet'}
          />
          {d.source_url && d.master_url && (
            <div className="flex rounded-full border border-line bg-surface-2 p-1 text-sm font-semibold">
              <button type="button" aria-pressed={!showOriginal} onClick={() => setShowOriginal(false)} className={`flex-1 rounded-full py-1.5 transition focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:outline-none ${!showOriginal ? 'bg-surface text-ink shadow-sm' : 'text-ink-faint hover:text-ink'}`}>
                AI edit {d.duration_out ? `· ${Math.round(d.duration_out)}s` : ''}
              </button>
              <button type="button" aria-pressed={showOriginal} onClick={() => setShowOriginal(true)} className={`flex-1 rounded-full py-1.5 transition focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:outline-none ${showOriginal ? 'bg-surface text-ink shadow-sm' : 'text-ink-faint hover:text-ink'}`}>
                Original {d.duration_in ? `· ${Math.round(d.duration_in)}s` : ''}
              </button>
            </div>
          )}
        </div>

        <div className="space-y-4">
          {working && (
            <Card className="flex items-center gap-3">
              <Spinner /> <span className="font-medium text-ink-soft">{d.status_label}…</span>
            </Card>
          )}

          {st === 'failed' && (
            <Card className="border-danger/40! bg-danger-soft/40">
              <p className="font-semibold text-danger">Something went wrong ({d.failed_stage}).</p>
              <p className="mt-1 text-sm break-words text-ink-soft">{d.error}</p>
              <Button className="mt-3" onClick={() => act('retry', 'retry')} loading={busy === 'retry'}>
                <RefreshCw className="h-4 w-4" /> Retry
              </Button>
            </Card>
          )}

          {d.edit_summary.length > 0 && (
            <Card>
              <h2 className="flex items-center gap-2 font-display text-2xl font-semibold">
                <Sparkles className="h-4 w-4 text-gold" /> What the AI editor did
              </h2>
              <ul className="mt-2 space-y-1 text-sm text-ink-soft">
                {d.edit_summary.map((b) => (
                  <li key={b}>• {b}</li>
                ))}
              </ul>
              {question && <p className="mt-3 rounded-xl bg-warn-soft p-3 text-sm text-warn">❓ {question}</p>}
              {trace.length > 0 && (
                <details className="mt-3 text-sm">
                  <summary className="cursor-pointer font-semibold text-ink-soft hover:text-ink">
                    Editor tool calls ({editorName === 'rules' ? 'built-in rules' : editorName}, {trace.length})
                  </summary>
                  <ol className="mt-2 space-y-1 rounded-xl bg-surface-2/60 p-3 font-mono text-xs break-words text-ink-soft">
                    {trace.map((t, i) => (
                      <li key={i} className={t.startsWith('✗') ? 'text-danger' : ''}>
                        {i + 1}. {t}
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </Card>
          )}

          {reviewing && (
            <Card className="space-y-3 border-brand-300! ring-4 ring-brand-500/10">
              <h2 className="font-display text-2xl font-semibold">Your call: is this edit good?</h2>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => act('approve', 'approve')} loading={busy === 'approve'}>
                  ✅ Approve edit
                </Button>
                {me.data?.features?.motion && (
                  <Button variant="secondary" onClick={() => act('motion', 'motion')} loading={busy === 'motion'} title="Kinetic captions, zoom punches, emoji pops, end card (2-4 min)">
                    ✨ Motion graphics
                  </Button>
                )}
                {STYLES.filter((s) => s !== d.style).map((s) => (
                  <Button key={s} variant="secondary" onClick={() => act(`style-${s}`, 'style', { style: s })} loading={busy === `style-${s}`}>
                    🎨 {s}
                  </Button>
                ))}
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input id="change-notes" aria-label="Ask for changes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder='Ask for changes, e.g. "cut the first 3 seconds", "no hook"' />
                <Button variant="secondary" disabled={!notes.trim()} loading={busy === 'changes'} onClick={() => act('changes', 'changes', { notes }).then((ok) => ok && setNotes(''))}>
                  <Wrench className="h-4 w-4" /> Apply
                </Button>
              </div>
            </Card>
          )}

          {st === 'awaiting_context' && (
            <Card className="space-y-3 border-brand-300! ring-4 ring-brand-500/10">
              <h2 className="font-display text-2xl font-semibold">Anything the caption should mention?</h2>
              <Textarea rows={2} value={tweak} onChange={(e) => setTweak(e.target.value)} placeholder="Offer, link, location... or leave empty" />
              <Button onClick={() => act('captions', 'captions/regenerate', { tweak: tweak ? `Include these details: ${tweak}` : null }).then((ok) => ok && setTweak(''))} loading={busy === 'captions'}>
                Write captions
              </Button>
            </Card>
          )}

          {captionStage && pack && (
            <Card className="space-y-3">
              <h2 className="font-display text-2xl font-semibold">{d.gates.caption_approved ? 'Caption' : 'Pick a caption'}</h2>
              {d.gates.caption_approved && d.caption_final && (
                <div className="rounded-xl border border-success/25 bg-success-soft p-3 text-sm whitespace-pre-wrap text-ink">
                  {d.caption_final}
                  <div className="mt-2 font-medium text-success">{d.hashtags_final.map((t) => `#${t}`).join(' ')}</div>
                </div>
              )}
              <div className="grid gap-3 md:grid-cols-3">
                {pack.options.map((o, i) => (
                  <div key={i} className="flex flex-col rounded-xl border border-line bg-surface-2/40 p-3 transition hover:border-brand-200">
                    <div className="text-xs font-bold tracking-[0.14em] text-ink-faint uppercase">{o.style}</div>
                    <p className="mt-1 flex-1 text-sm whitespace-pre-wrap">{o.text}</p>
                    <Button variant="secondary" className="mt-3" onClick={() => act(`cap-${i}`, 'caption', { option: i + 1 })} loading={busy === `cap-${i}`}>
                      Use this
                    </Button>
                  </div>
                ))}
              </div>
              <p className="text-sm break-words text-ink-faint">{pack.hashtags.map((t) => `#${t}`).join(' ')}</p>
              {pack.facts_to_confirm.length > 0 && (
                <p className="rounded-xl bg-warn-soft p-3 text-sm text-warn">⚠️ Double-check: {pack.facts_to_confirm.join('; ')}</p>
              )}
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input value={tweak} onChange={(e) => setTweak(e.target.value)} placeholder='Tweak, e.g. "shorter", "more playful"' />
                <Button variant="secondary" disabled={!tweak.trim()} loading={busy === 'regen'} onClick={() => act('regen', 'captions/regenerate', { tweak }).then((ok) => ok && setTweak(''))}>
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
            <Card className="space-y-3 border-brand-300! ring-4 ring-brand-500/10">
              <h2 className="font-display text-2xl font-semibold">Post it</h2>
              <div className="flex flex-wrap items-center gap-2">
                <Button onClick={() => act('now', 'publish', { mode: 'now' })} loading={busy === 'now'}>
                  🚀 Post now
                </Button>
                <span className="text-sm text-ink-faint">or</span>
                <Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} className="min-w-0 sm:w-auto" />
                <Button variant="secondary" onClick={() => act('schedule', 'publish', { mode: 'schedule', publish_at: new Date(when).toISOString() })} loading={busy === 'schedule'} disabled={!when}>
                  🗓 Schedule
                </Button>
              </div>
            </Card>
          )}

          {st === 'scheduled' && (
            <Card className="flex flex-wrap items-center justify-between gap-3 border-info/40!">
              <div>
                <div className="font-display text-2xl font-semibold text-info">Scheduled</div>
                <div className="text-sm text-ink-soft">Posts {fmtDate(d.publish_at)}</div>
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => act('unschedule', 'unschedule')} loading={busy === 'unschedule'}>
                  Unschedule
                </Button>
              </div>
            </Card>
          )}

          {st === 'published' && d.ig_permalink && (
            <Card className="border-success/40!">
              <div className="font-display text-2xl font-semibold text-success">🎉 Live on Instagram</div>
              <a href={d.ig_permalink} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-sm font-semibold text-brand-600">
                Open post <ExternalLink className="h-4 w-4" />
              </a>
            </Card>
          )}

          <Card>
            <h2 className="font-display text-2xl font-semibold">Approval gates</h2>
            <ul className="mt-2 space-y-1.5 text-sm">
              {[
                ['Edit approved by you', d.gates.video_approved],
                ['Caption approved by you', d.gates.caption_approved],
                ['Posting confirmed by you', d.gates.publish_confirmed],
              ].map(([label, ok]) => (
                <li key={label as string} className="flex items-center gap-2">
                  {ok ? <CheckCircle2 className="h-4 w-4 shrink-0 text-success" /> : <Circle className="h-4 w-4 shrink-0 text-ink-faint/50" />} {label}
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-ink-faint">Nothing reaches Instagram until all three are ticked for the current revision.</p>
          </Card>

          <CollabTimeline events={d.events} />

          {d.transcript && (
            <details className="rounded-2xl border border-line bg-surface p-5 text-sm shadow-sm">
              <summary className="cursor-pointer font-display text-2xl font-semibold">Transcript</summary>
              <p className="mt-2 leading-relaxed text-ink-soft">{d.transcript}</p>
            </details>
          )}
        </div>
      </div>
    </div>
  )
}
