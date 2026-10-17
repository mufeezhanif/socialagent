import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Camera as Instagram, Film, MessageCircle } from 'lucide-react'
import { api, WORKING, type DraftSummary } from '../api'
import { fmtDate, Spinner, StatusBadge } from '../ui'
import { useMe } from '../App'
import ImpactStrip from '../components/ImpactStrip'
import EmptyDrafts from '../components/EmptyDrafts'
import { DraftGridSkeleton } from '../components/Skeletons'
import { PipelineMini } from '../components/PipelineStepper'

const GROUPS: { title: string; match: (s: string) => boolean }[] = [
  { title: 'Needs you', match: (s) => s.startsWith('awaiting') || s === 'failed' },
  { title: 'In progress', match: (s) => WORKING.has(s) },
  { title: 'Scheduled', match: (s) => s === 'scheduled' },
  { title: 'Published', match: (s) => s === 'published' },
  { title: 'Saved drafts', match: (s) => s === 'saved' },
]

function DraftCard({ d }: { d: DraftSummary }) {
  return (
    <Link to={`/app/drafts/${d.id}`} className="group block overflow-hidden rounded-2xl border border-line bg-surface shadow-sm transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-lg focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:outline-none motion-reduce:transition-none motion-reduce:hover:translate-y-0">
      <div className="relative aspect-[9/16] max-h-64 w-full bg-surface-2">
        {d.cover_url ? (
          <img src={d.cover_url} alt="" className="h-full w-full object-cover transition duration-500 group-hover:scale-[1.03] motion-reduce:transition-none motion-reduce:group-hover:scale-100" />
        ) : (
          <div className="grid h-full place-items-center text-ink-faint">
            {WORKING.has(d.status) ? <Spinner /> : <Film className="h-8 w-8" />}
          </div>
        )}
        <div className="absolute top-2 left-2">
          <StatusBadge status={d.status} label={d.status_label} />
        </div>
      </div>
      <div className="space-y-1 p-3">
        <div className="line-clamp-2 min-h-10 text-sm font-medium">{d.caption_final || <span className="text-ink-faint">No caption yet</span>}</div>
        <PipelineMini draft={d} className="pt-1" />
        <div className="truncate text-xs text-ink-faint">
          {d.status === 'scheduled' && d.publish_at ? `Posts ${fmtDate(d.publish_at)}` : fmtDate(d.created_at)}
          {d.duration_out ? ` · ${Math.round(d.duration_out)}s · ${d.style}` : ''}
        </div>
      </div>
    </Link>
  )
}

export default function Dashboard() {
  const me = useMe()
  const drafts = useQuery({
    queryKey: ['drafts'],
    queryFn: () => api<DraftSummary[]>('/api/drafts'),
    refetchInterval: 4000,
  })
  const list = drafts.data || []

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-4xl font-semibold tracking-tight">Your drafts</h1>
          <p className="text-sm text-ink-soft">Send a video to the bot on WhatsApp, or upload one in Chat.</p>
        </div>
        <div className="flex flex-wrap gap-2 text-sm">
          <Link to="/onboarding" className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 font-semibold ring-1 ring-black/5 ring-inset transition hover:brightness-95 dark:ring-white/5 dark:hover:brightness-110 ${me.data?.instagram ? 'bg-success-soft text-success' : 'bg-warn-soft text-warn'}`}>
            <Instagram className="h-4 w-4" /> {me.data?.instagram ? `@${me.data.instagram.username}` : 'Connect Instagram'}
          </Link>
          <Link to="/onboarding" className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 font-semibold ring-1 ring-black/5 ring-inset transition hover:brightness-95 dark:ring-white/5 dark:hover:brightness-110 ${me.data?.whatsapp?.linked ? 'bg-success-soft text-success' : 'bg-warn-soft text-warn'}`}>
            <MessageCircle className="h-4 w-4" /> {me.data?.whatsapp?.linked ? 'WhatsApp linked' : 'Link WhatsApp'}
          </Link>
        </div>
      </div>

      {!drafts.isLoading && list.length > 0 && <ImpactStrip drafts={list} />}

      {drafts.isLoading ? (
        <DraftGridSkeleton />
      ) : list.length === 0 ? (
        <EmptyDrafts whatsappLinked={Boolean(me.data?.whatsapp?.linked)} />
      ) : (
        GROUPS.map((g) => {
          const items = list.filter((d) => g.match(d.status))
          if (!items.length) return null
          return (
            <section key={g.title}>
              <h2 className="mb-3 text-xs font-bold tracking-[0.14em] text-ink-faint uppercase">
                {g.title} · {items.length}
              </h2>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
                {items.map((d) => (
                  <DraftCard key={d.id} d={d} />
                ))}
              </div>
            </section>
          )
        })
      )}
    </div>
  )
}
