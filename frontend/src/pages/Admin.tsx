import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { QRCodeSVG } from 'qrcode.react'
import { toast } from 'sonner'
import { api } from '../api'
import { Button, Card, Field, Input, Spinner } from '../ui'

interface WaStatus {
  status: string
  me?: { id: string; name?: string } | null
  qr?: string | null
  pairing_code?: string | null
  last_error?: string | null
  paused?: boolean
  allowlist_size?: number
  error?: string
}

interface ServerConfig {
  app_base_url: string
  instagram_configured: boolean
  instagram_redirect_uri: string
  instagram_graph_version: string
  publish_dry_run: boolean
  llm_providers: string[]
  transcription: string
  motion_graphics: boolean
}

function Row({ label, value, ok }: { label: string; value: React.ReactNode; ok?: boolean }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 py-2 text-sm last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className={`font-medium ${ok === false ? 'text-red-600' : ok ? 'text-emerald-700' : ''}`}>{value}</span>
    </div>
  )
}

interface Stats {
  users: number
  drafts: Record<string, number>
  jobs: Record<string, number>
}

export default function Admin() {
  const qc = useQueryClient()
  const status = useQuery({ queryKey: ['wa-status'], queryFn: () => api<WaStatus>('/api/admin/wa/status'), refetchInterval: 3000 })
  const stats = useQuery({ queryKey: ['stats'], queryFn: () => api<Stats>('/api/admin/stats'), refetchInterval: 10000 })
  const config = useQuery({ queryKey: ['admin-config'], queryFn: () => api<ServerConfig>('/api/admin/config') })
  const [phone, setPhone] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const call = async (name: string, path: string, json: unknown = {}) => {
    setBusy(name)
    try {
      const res = await api<Record<string, unknown>>(path, { method: 'POST', json })
      if (typeof res.code === 'string') toast.success(`Pairing code: ${res.code}`)
      qc.invalidateQueries({ queryKey: ['wa-status'] })
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const s = status.data
  const open = s?.status === 'open'
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-2xl font-bold">Admin</h1>
      {config.data && (
        <Card>
          <h2 className="font-bold">Server setup</h2>
          <div className="mt-2">
            <Row label="Public URL" value={config.data.app_base_url} />
            <Row label="Instagram app" value={config.data.instagram_configured ? 'configured' : 'missing IG_APP_ID / IG_APP_SECRET'} ok={config.data.instagram_configured} />
            <Row
              label="Instagram redirect URI (add in Meta)"
              value={
                <button
                  className="font-mono text-xs text-brand-700 underline"
                  onClick={() => navigator.clipboard.writeText(config.data!.instagram_redirect_uri).then(() => toast.success('Copied'))}
                >
                  {config.data.instagram_redirect_uri}
                </button>
              }
            />
            <Row label="Graph API version" value={config.data.instagram_graph_version} />
            <Row label="Publishing" value={config.data.publish_dry_run ? 'dry run (not posting)' : 'live'} ok={!config.data.publish_dry_run} />
            <Row label="AI providers" value={config.data.llm_providers.join(' → ') || 'none (built-in rules)'} ok={config.data.llm_providers.length > 0} />
            <Row label="Transcription" value={config.data.transcription} />
            <Row label="Motion graphics" value={config.data.motion_graphics ? 'available' : 'off'} />
          </div>
        </Card>
      )}
      <Card className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-bold">WhatsApp bot</h2>
          <span className={`rounded-full px-3 py-1 text-xs font-bold ${open ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-800'}`}>
            {s?.status || '...'}
            {s?.paused ? ' · paused' : ''}
          </span>
        </div>
        {status.isLoading && <Spinner />}
        {open && (
          <p className="text-sm text-slate-600">
            Connected as <b>{s?.me?.name || 'bot'}</b> ({s?.me?.id?.split(':')[0]}). Linked users: {s?.allowlist_size ?? 0}.
          </p>
        )}
        {!open && s?.qr && (
          <div className="grid items-center gap-5 sm:grid-cols-[auto_1fr]">
            <div className="rounded-2xl bg-white p-3 ring-1 ring-slate-200">
              <QRCodeSVG value={s.qr} size={220} />
            </div>
            <div className="space-y-2 text-sm text-slate-600">
              <p>On the bot phone: WhatsApp → Settings → Linked devices → Link a device, then scan.</p>
              <p className="text-xs text-amber-700">This QR gives full access to that WhatsApp account. Never share or screenshot it.</p>
            </div>
          </div>
        )}
        {!open && (
          <div className="space-y-2">
            <Field label="Or pair with a code" hint="Bot phone number with country code. Then on the phone: Linked devices → Link with phone number.">
              <div className="flex gap-2">
                <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="923001234567" />
                <Button variant="secondary" onClick={() => call('pair', '/api/admin/wa/pair-code', { phone })} loading={busy === 'pair'}>
                  Get code
                </Button>
              </div>
            </Field>
            {s?.pairing_code && <p className="font-mono text-2xl font-bold tracking-widest">{s.pairing_code}</p>}
          </div>
        )}
        {s?.last_error && <p className="text-xs text-slate-500">Last disconnect: {s.last_error}</p>}
        {s?.error && <p className="text-xs text-red-600">{s.error}</p>}
        <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
          <Button variant="secondary" onClick={() => call('pause', '/api/admin/wa/pause', { paused: !s?.paused })} loading={busy === 'pause'}>
            {s?.paused ? 'Resume bot' : 'Pause bot'}
          </Button>
          <Button variant="danger" onClick={() => call('logout', '/api/admin/wa/logout')} loading={busy === 'logout'}>
            Log out WhatsApp session
          </Button>
        </div>
      </Card>
      <Card>
        <h2 className="font-bold">Activity</h2>
        {stats.data && (
          <div className="mt-2 grid gap-2 text-sm sm:grid-cols-3">
            <div>Users: <b>{stats.data.users}</b></div>
            <div>Drafts: {Object.entries(stats.data.drafts).map(([k, v]) => `${k} ${v}`).join(', ') || 'none'}</div>
            <div>Jobs: {Object.entries(stats.data.jobs).map(([k, v]) => `${k} ${v}`).join(', ') || 'none'}</div>
          </div>
        )}
      </Card>
    </div>
  )
}
