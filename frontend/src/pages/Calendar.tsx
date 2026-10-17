import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, type DraftSummary } from '../api'
import { Card, Spinner, StatusBadge } from '../ui'

export default function Calendar() {
  const drafts = useQuery({ queryKey: ['drafts'], queryFn: () => api<DraftSummary[]>('/api/drafts'), refetchInterval: 5000 })
  if (drafts.isLoading) return <Spinner />
  const items = (drafts.data || [])
    .filter((d) => (d.status === 'scheduled' || d.status === 'published') && (d.publish_at || d.updated_at))
    .map((d) => ({ d, when: new Date(d.publish_at || d.updated_at || d.created_at) }))
    .sort((a, b) => a.when.getTime() - b.when.getTime())
  const days = new Map<string, typeof items>()
  for (const item of items) {
    const key = item.when.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
    days.set(key, [...(days.get(key) || []), item])
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="font-display text-4xl font-semibold tracking-tight">Calendar</h1>
        <p className="text-sm text-ink-soft">Scheduled and published Reels.</p>
      </div>
      {items.length === 0 && <Card className="py-10 text-center text-sm text-ink-soft">Nothing scheduled yet.</Card>}
      {[...days.entries()].map(([day, list]) => (
        <section key={day}>
          <h2 className="mb-2 text-xs font-bold tracking-[0.14em] text-ink-faint uppercase">{day}</h2>
          <div className="space-y-2">
            {list.map(({ d, when }) => (
              <Link key={d.id} to={`/app/drafts/${d.id}`} className="flex items-center gap-3 rounded-2xl border border-line bg-surface p-3 shadow-xs transition hover:border-brand-200 hover:bg-surface-2 sm:gap-4">
                <div className="w-16 shrink-0 font-display text-lg leading-tight font-semibold">{when.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</div>
                {d.cover_url ? <img src={d.cover_url} className="h-16 w-9 shrink-0 rounded-md object-cover" alt="" /> : <div className="h-16 w-9 rounded-md bg-surface-2" />}
                <div className="min-w-0 flex-1">
                  <div className="mb-1 truncate text-sm font-medium">{d.caption_final || 'Untitled'}</div>
                  <StatusBadge status={d.status} label={d.status_label} />
                </div>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
