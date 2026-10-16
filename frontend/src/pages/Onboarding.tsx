import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { QRCodeSVG } from 'qrcode.react'
import { Camera as Instagram, CheckCircle2, MessageCircle, Palette } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Me } from '../api'
import { Button, Card, Input, Logo } from '../ui'
import { BrandForm } from './Brand'

interface LinkInfo {
  code: string
  wa_link: string
  bot_number: string
  expires_at: string
}

function Step({ n, title, done, icon: Icon, children }: { n: number; title: string; done: boolean; icon: typeof Instagram; children: React.ReactNode }) {
  return (
    <Card className={done ? 'border-emerald-200' : ''}>
      <div className="flex items-start gap-4">
        <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${done ? 'bg-emerald-100 text-emerald-700' : 'bg-brand-50 text-brand-600'}`}>
          {done ? <CheckCircle2 className="h-5 w-5" /> : <Icon className="h-5 w-5" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-xs font-bold text-slate-400">STEP {n}</div>
          <h2 className="text-lg font-bold">{title}</h2>
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
    <div className="min-h-screen bg-gradient-to-b from-brand-50 to-white px-4 py-8">
      <div className="mx-auto max-w-2xl space-y-4">
        <div className="flex items-center justify-between">
          <Logo name={data?.app_name} />
          <Link to="/app" className="text-sm font-semibold text-slate-500 hover:text-slate-800">
            Skip for now →
          </Link>
        </div>
        <h1 className="pt-2 text-2xl font-black">Let's set you up</h1>

        <Step n={1} title="Connect Instagram" done={igDone} icon={Instagram}>
          {igDone ? (
            <div className="flex items-center gap-3">
              {data?.instagram?.profile_picture_url && <img src={data.instagram.profile_picture_url} className="h-10 w-10 rounded-full" alt="" />}
              <div>
                <div className="font-semibold">@{data?.instagram?.username}</div>
                <div className="text-xs text-slate-500">{data?.instagram?.account_type?.replace('_', ' ').toLowerCase()} account</div>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-slate-600">Needs a Professional account (Creator or Business). Switch for free in Instagram settings.</p>
              <Button variant="ig" onClick={connectInstagram} loading={busy} disabled={!data?.instagram_configured}>
                <Instagram className="h-4 w-4" /> Connect Instagram
              </Button>
              {!data?.instagram_configured && <p className="text-xs text-amber-700">The Instagram app isn't configured on the server yet.</p>}
            </div>
          )}
        </Step>

        <Step n={2} title="Link WhatsApp" done={waDone} icon={MessageCircle}>
          {waDone ? (
            <p className="text-sm text-slate-600">Linked to +{data?.whatsapp?.phone}. Send your videos to the bot on WhatsApp.</p>
          ) : link ? (
            <div className="grid items-center gap-5 sm:grid-cols-[auto_1fr]">
              <div className="rounded-2xl bg-white p-3 shadow-sm ring-1 ring-slate-200">
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
                <p className="text-xs text-slate-500">On a computer? Scan the QR with your phone. This page updates by itself once the message arrives.</p>
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
