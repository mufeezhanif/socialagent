import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Camera as Instagram, Film, MessageCircle } from 'lucide-react'
import { api, WORKING, type DraftSummary } from '../api'
import { Card, fmtDate, Spinner, StatusBadge } from '../ui'
import { useMe } from '../App'

const GROUPS: { title: string; match: (s: string) => boolean }[] = [
  { title: 'Needs you', match: (s) => s.startsWith('awaiting') || s === 'failed' },
  { title: 'In progress', match: (s) => WORKING.has(s) },
  { title: 'Scheduled', match: (s) => s === 'scheduled' },
  { title: 'Published', match: (s) => s === 'published' },
  { title: 'Saved drafts', match: (s) => s === 'saved' },
]

function DraftCard({ d }: { d: DraftSummary }) {
  return (
    <Link to={`/app/drafts/${d.id}`} className="group block overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <div className="relative aspect-[9/16] max-h-64 w-full bg-slate-100">
        {d.cover_url ? (
          <img src={d.cover_url} alt="" className="h-full w-full object-cover" />
        ) : (
          <div className="grid h-full place-items-center text-slate-400">
            {WORKING.has(d.status) ? <Spinner /> : <Film className="h-8 w-8" />}
          </div>
        )}
        <div className="absolute top-2 left-2">
          <StatusBadge status={d.status} label={d.status_label} />
        </div>
      </div>
      <div className="space-y-1 p-3">
        <div className="line-clamp-2 min-h-10 text-sm font-medium">{d.caption_final || <span className="text-slate-400">No caption yet</span>}</div>
        <div className="text-xs text-slate-500">
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
          <h1 className="text-2xl font-bold">Your drafts</h1>
          <p className="text-sm text-slate-500">Send a video to the bot on WhatsApp, or upload one in Chat.</p>
        </div>
        <div className="flex flex-wrap gap-2 text-sm">
          <Link to="/onboarding" className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 font-medium ${me.data?.instagram ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
            <Instagram className="h-4 w-4" /> {me.data?.instagram ? `@${me.data.instagram.username}` : 'Connect Instagram'}
          </Link>
          <Link to="/onboarding" className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 font-medium ${me.data?.whatsapp?.linked ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
            <MessageCircle className="h-4 w-4" /> {me.data?.whatsapp?.linked ? 'WhatsApp linked' : 'Link WhatsApp'}
          </Link>
        </div>
      </div>

      {drafts.isLoading ? (
        <Spinner />
      ) : list.length === 0 ? (
        <Card className="py-12 text-center">
          <div className="text-4xl">🎬</div>
          <h2 className="mt-3 text-lg font-bold">No videos yet</h2>
          <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
            Send a raw clip to the bot on WhatsApp. It comes back edited for your approval, then you pick a caption and post or schedule it.
          </p>
          <Link to="/app/chat" className="mt-4 inline-block text-sm font-semibold text-brand-600">
            Or try it here in the web chat →
          </Link>
        </Card>
      ) : (
        GROUPS.map((g) => {
          const items = list.filter((d) => g.match(d.status))
          if (!items.length) return null
          return (
            <section key={g.title}>
              <h2 className="mb-3 text-sm font-bold tracking-wide text-slate-500 uppercase">
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
