import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, type Brand } from '../api'
import { Button, Card, Field, Input, Spinner, Textarea } from '../ui'

const STYLE_HINTS: Record<string, string> = {
  clean: 'Simple, readable, natural colour',
  hype: 'Punchy zoom cuts, bold colour, progress bar',
  cinematic: 'Moody grade, calm captions',
  funny: 'Loud colours, popping words',
  deadpan: 'Flat and dry, lowercase captions',
  luxury: 'Warm, elegant, gold accents',
}

export function BrandForm({ compact = false, onSaved }: { compact?: boolean; onSaved?: () => void }) {
  const qc = useQueryClient()
  const brand = useQuery({ queryKey: ['brand'], queryFn: () => api<Brand>('/api/brand') })
  const [form, setForm] = useState<Brand | null>(null)
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (brand.data && !form) setForm(brand.data)
  }, [brand.data, form])
  if (!form) return <Spinner />

  const set = <K extends keyof Brand>(key: K, value: Brand[K]) => setForm({ ...form, [key]: value })
  const save = async () => {
    setSaving(true)
    try {
      const saved = await api<Brand>('/api/brand', { method: 'PUT', json: form })
      qc.setQueryData(['brand'], saved)
      setForm(saved)
      toast.success('Brand kit saved')
      onSaved?.()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="What do you post about?">
          <Input value={form.niche} onChange={(e) => set('niche', e.target.value)} placeholder="Home bakery in Islamabad" />
        </Field>
        <Field label="Tone of voice">
          <Input value={form.tone} onChange={(e) => set('tone', e.target.value)} placeholder="friendly, confident" />
        </Field>
        {!compact && (
          <Field label="Audience">
            <Input value={form.audience} onChange={(e) => set('audience', e.target.value)} placeholder="students, young families" />
          </Field>
        )}
        <Field label="Call to action" hint="Added to captions when it fits">
          <Input value={form.cta} onChange={(e) => set('cta', e.target.value)} placeholder="Order via the link in bio" />
        </Field>
      </div>
      <Field label="Default video style">
        <div className="grid gap-2 sm:grid-cols-3">
          {form.styles.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => set('default_style', s)}
              className={`rounded-xl border px-3 py-2 text-left text-sm transition ${form.default_style === s ? 'border-brand-500 bg-brand-50 ring-2 ring-brand-100' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
            >
              <div className="font-semibold capitalize">{s}</div>
              <div className="text-xs text-slate-500">{STYLE_HINTS[s]}</div>
            </button>
          ))}
        </div>
      </Field>
      {!compact && (
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Emoji level">
            <select
              value={form.emoji_level}
              onChange={(e) => set('emoji_level', e.target.value as Brand['emoji_level'])}
              className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm"
            >
              <option value="none">None</option>
              <option value="some">Some</option>
              <option value="lots">Lots</option>
            </select>
          </Field>
          <Field label="Caption highlight colour">
            <div className="flex items-center gap-2">
              <input type="color" value={form.accent_color} onChange={(e) => set('accent_color', e.target.value)} className="h-10 w-14 rounded-lg border border-slate-200" />
              <Input value={form.accent_color} onChange={(e) => set('accent_color', e.target.value)} />
            </div>
          </Field>
          <Field label="Default hashtags" hint="Comma separated, always included">
            <Input
              value={form.default_hashtags.join(',')}
              onChange={(e) => set('default_hashtags', e.target.value.split(','))}
              placeholder="homebaker, islamabadfood"
            />
          </Field>
          <Field label="Words to never use" hint="Comma separated">
            <Textarea
              rows={1}
              value={form.banned_words.join(',')}
              onChange={(e) => set('banned_words', e.target.value.split(','))}
            />
          </Field>
          <Field label="Preferred posting time">
            <Input type="time" value={form.preferred_post_time} onChange={(e) => set('preferred_post_time', e.target.value)} />
          </Field>
          <Field label="Timezone">
            <Input value={form.timezone} onChange={(e) => set('timezone', e.target.value)} placeholder="Asia/Karachi" />
          </Field>
        </div>
      )}
      <Button onClick={save} loading={saving}>
        Save brand kit
      </Button>
    </div>
  )
}

export default function BrandPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-2xl font-bold">Brand kit</h1>
        <p className="text-sm text-slate-500">The AI editor and caption writer follow these on every video.</p>
      </div>
      <Card>
        <BrandForm />
      </Card>
    </div>
  )
}
