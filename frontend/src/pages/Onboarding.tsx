import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { QRCodeSVG } from 'qrcode.react'
import { Camera as Instagram, CheckCircle2, MessageCircle, Palette } from 'lucide-react'
import { toast } from 'sonner'
import { api, type InstagramStatus, type Me } from '../api'
import { Button, Card, Input, Logo } from '../ui'
import { BrandForm } from './Brand'
import { FacebookConnect } from '../components/FacebookConnect'
import { ThemeToggle } from '../theme'

interface LinkInfo {
  code: string
  wa_link: string
  bot_number: string
  expires_at: string
}

function Step({ n, title, done, icon: Icon, children }: { n: number; title: string; done: boolean; icon: typeof Instagram; children: React.ReactNode }) {
  return (
    <Card className={done ? 'border-success/40!' : ''}>
      <div className="flex items-start gap-4">
        <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${done ? 'bg-success-soft text-success' : 'bg-brand-100 text-brand-700'}`}>
          {done ? <CheckCircle2 className="h-5 w-5" aria-hidden /> : <Icon className="h-5 w-5" aria-hidden />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-xs font-bold tracking-[0.14em] text-ink-faint">STEP {n}</div>
          <h2 className="font-display text-2xl font-semibold">{title}</h2>
          <div className="mt-3">{children}</div>
        </div>
      </div>
    </Card>
  )
}

export default function Onboarding() {
  const [params, setParams] = useSearchParams()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [link, setLink] = useState<LinkInfo | null>(null)
  const [phone, setPhone] = useState('')
  const [busy, setBusy] = useState(false)
  const me = useQuery({
    queryKey: ['me'],
    queryFn: () => api<Me>('/api/me'),
    refetchInterval: link ? 3000 : false,
  })

  useEffect(() => {
    const ig = params.get('ig')
    if (ig === 'connected') toast.success('Instagram connected')
    if (ig === 'error') toast.error(`Instagram: ${params.get('reason') || 'could not connect'}`)
    if (ig) {
      params.delete('ig')
      params.delete('reason')
      setParams(params, { replace: true })
      qc.invalidateQueries({ queryKey: ['me'] })
    }
  }, [params, setParams, qc])

  const data = me.data
  const igDone = Boolean(data?.instagram)
  const waDone = Boolean(data?.whatsapp?.linked)
  const doneCount = Number(igDone) + Number(waDone)
  useEffect(() => {
    if (waDone && link) {
      toast.success('WhatsApp linked')
      setLink(null)
    }
  }, [waDone, link])

  const connectInstagram = async () => {
    setBusy(true)
    try {
      const { url } = await api<{ url: string }>('/api/instagram/connect')
      window.location.href = url
    } catch (err) {
      toast.error((err as Error).message)
      setBusy(false)
    }
  }

  const [igStatus, setIgStatus] = useState<InstagramStatus | null>(null)
  const [checking, setChecking] = useState(false)
  const checkInstagram = async () => {
    setChecking(true)
    try {
      setIgStatus(await api<InstagramStatus>('/api/instagram/status'))
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setChecking(false)
    }
  }

  const startLink = async () => {
    setBusy(true)
    try {
      setLink(await api<LinkInfo>('/api/whatsapp/link', { method: 'POST', json: { phone } }))
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen px-4 py-8">
      <div className="mx-auto max-w-2xl space-y-4">
        <div className="flex items-center justify-between gap-3">
          <Logo name={data?.app_name} />
          <div className="flex items-center gap-2">
            <Link to="/app" className="text-sm font-semibold whitespace-nowrap text-ink-soft hover:text-ink">
              Skip for now →
            </Link>
            <ThemeToggle />
          </div>
        </div>
        <h1 className="pt-4 font-display text-4xl font-semibold tracking-tight">Let's set you up</h1>
        <div>
          <div className="flex items-center justify-between text-xs font-semibold text-ink-soft">
            <span>{doneCount} of 2 required steps done</span>
            <span>{doneCount === 2 ? 'Ready to go' : 'Brand kit is optional'}</span>
          </div>
          <div
            className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-2"
            role="progressbar"
            aria-label="Setup progress"
            aria-valuemin={0}
            aria-valuemax={2}
            aria-valuenow={doneCount}
          >
            <div className="h-full rounded-full bg-brand-500 transition-[width] duration-500 motion-reduce:transition-none" style={{ width: `${(doneCount / 2) * 100}%` }} />
          </div>
        </div>

        <Step n={1} title="Connect Instagram" done={igDone} icon={Instagram}>
          {igDone ? (
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                {data?.instagram?.profile_picture_url && <img src={data.instagram.profile_picture_url} className="h-10 w-10 rounded-full ring-2 ring-line" alt="" />}
                <div>
                  <div className="font-semibold">@{data?.instagram?.username}</div>
                  <div className="text-xs text-ink-faint">{data?.instagram?.account_type?.replace('_', ' ').toLowerCase()} account</div>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="secondary" onClick={checkInstagram} loading={checking}>
                  Check connection
                </Button>
                <Button variant="ghost" onClick={connectInstagram} disabled={!data?.instagram_configured}>
                  Reconnect
                </Button>
              </div>
              {igStatus && (
                <p className={`rounded-xl p-3 text-sm ${igStatus.ok ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger'}`}>
                  {igStatus.ok
                    ? `Working. ${igStatus.quota_usage ?? 0} of ${igStatus.quota_total ?? 100} posts used in the last 24 h.`
                    : `Problem: ${igStatus.error}. Try Reconnect.`}
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-ink-soft">Needs a Professional account (Creator or Business). Switch for free in Instagram settings.</p>
              <Button variant="ig" onClick={connectInstagram} loading={busy} disabled={!data?.instagram_configured}>
                <Instagram className="h-4 w-4" /> Connect Instagram
              </Button>
              {!data?.instagram_configured && (
                <p className="rounded-xl bg-warn-soft p-3 text-xs text-warn">
                  Instagram isn't set up on this server yet. An admin needs to add the Meta app's Instagram App ID and
                  secret (IG_APP_ID / IG_APP_SECRET). Details on the Admin page.
                </p>
              )}
            </div>
          )}
          <FacebookConnect />
        </Step>

        <Step n={2} title="Link WhatsApp" done={waDone} icon={MessageCircle}>
          {waDone ? (
            <p className="text-sm text-ink-soft">Linked to +{data?.whatsapp?.phone}. Send your videos to the bot on WhatsApp.</p>
          ) : link ? (
            <div className="grid items-center gap-5 sm:grid-cols-[auto_1fr]">
              <div className="w-fit rounded-2xl bg-white p-3 shadow-sm ring-1 ring-line">
                <QRCodeSVG value={link.wa_link} size={150} />
              </div>
              <div className="space-y-3 text-sm">
                <p>
                  Send this code from <b>your</b> WhatsApp:
                  <span className="mt-1 block font-mono text-lg font-bold tracking-wider text-brand-700">{link.code}</span>
                </p>
                <a href={link.wa_link} target="_blank" rel="noreferrer">
                  <Button variant="wa">
                    <MessageCircle className="h-4 w-4" /> Open WhatsApp
                  </Button>
                </a>
                <p className="text-xs text-ink-faint">On a computer? Scan the QR with your phone. This page updates by itself once the message arrives.</p>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+92 300 1234567" inputMode="tel" />
              <Button variant="wa" onClick={startLink} loading={busy} disabled={phone.replace(/\D/g, '').length < 8}>
                Get my link code
              </Button>
            </div>
          )}
        </Step>

        <Step n={3} title="Brand kit (optional)" done={false} icon={Palette}>
          <BrandForm compact onSaved={() => navigate('/app')} />
        </Step>

        <div className="flex justify-end pt-2">
          <Button onClick={() => navigate('/app')} disabled={!waDone}>
            Go to my dashboard →
          </Button>
        </div>
      </div>
    </div>
  )
}
