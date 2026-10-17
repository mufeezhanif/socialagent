import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Share2 } from 'lucide-react'
import { api } from '../api'
import { Button } from '../ui'

type FacebookStatus = {
  connected: boolean
  configured: boolean
  name?: string
  picture_url?: string
  ok?: boolean
  error?: string
  followers?: number | null
}

/** Optional: cross-post every approved Reel to a Facebook Page as well. */
export function FacebookConnect() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [busy, setBusy] = useState(false)
  const status = useQuery({ queryKey: ['facebook'], queryFn: () => api<FacebookStatus>('/api/facebook/status') })

  useEffect(() => {
    const fb = params.get('fb')
    if (fb === 'connected') toast.success('Facebook Page connected')
    if (fb === 'error') toast.error(`Facebook: ${params.get('reason') || 'could not connect'}`)
    if (fb) {
      params.delete('fb')
      params.delete('reason')
      setParams(params, { replace: true })
      qc.invalidateQueries({ queryKey: ['facebook'] })
    }
  }, [params, setParams, qc])

  const connect = async () => {
    setBusy(true)
    try {
      const { url } = await api<{ url: string }>('/api/facebook/connect')
      window.location.href = url
    } catch (err) {
      toast.error((err as Error).message)
      setBusy(false)
    }
  }

  const disconnect = async () => {
    await api('/api/facebook', { method: 'DELETE' })
    qc.invalidateQueries({ queryKey: ['facebook'] })
  }

  const data = status.data
  return (
    <div className="mt-3 space-y-2 border-t border-line pt-3">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <Share2 className="h-4 w-4" /> Also post to Facebook <span className="font-normal text-ink-faint">(optional)</span>
      </div>
      {data?.connected ? (
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            {data.picture_url && <img src={data.picture_url} className="h-8 w-8 rounded-full ring-2 ring-line" alt="" />}
            <div className="text-sm">
              <div className="font-semibold">{data.name}</div>
              <div className="text-xs text-ink-faint">
                {data.ok === false ? `Problem: ${data.error}` : 'Every approved Reel is cross-posted to this Page.'}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" onClick={connect} loading={busy}>
              Reconnect
            </Button>
            <Button variant="ghost" onClick={disconnect}>
              Disconnect
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-sm text-ink-soft">Connect a Facebook Page and the same approved Reel goes live there too.</p>
          <Button variant="secondary" onClick={connect} loading={busy} disabled={!data?.configured}>
            <Share2 className="h-4 w-4" /> Connect Facebook Page
          </Button>
          {data && !data.configured && (
            <p className="rounded-xl bg-warn-soft p-3 text-xs text-warn">
              Facebook isn't set up on this server yet. An admin needs to add the Meta app ID and secret (FB_APP_ID /
              FB_APP_SECRET).
            </p>
          )}
        </div>
      )}
    </div>
  )
}
