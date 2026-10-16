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
        <h1 className="text-2xl font-bold">Calendar</h1>
        <p className="text-sm text-slate-500">Scheduled and published Reels.</p>
      </div>
      {items.length === 0 && <Card className="text-center text-sm text-slate-500">Nothing scheduled yet.</Card>}
      {[...days.entries()].map(([day, list]) => (
        <section key={day}>
          <h2 className="mb-2 text-sm font-bold text-slate-500">{day}</h2>
          <div className="space-y-2">
            {list.map(({ d, when }) => (
              <Link key={d.id} to={`/app/drafts/${d.id}`} className="flex items-center gap-4 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm hover:bg-slate-50">
                <div className="w-16 text-sm font-bold">{when.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</div>
                {d.cover_url ? <img src={d.cover_url} className="h-16 w-9 rounded-md object-cover" alt="" /> : <div className="h-16 w-9 rounded-md bg-slate-100" />}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{d.caption_final || 'Untitled'}</div>
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
