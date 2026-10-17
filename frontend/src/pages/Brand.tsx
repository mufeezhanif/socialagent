import { useEffect, useState } from 'react'
import { Brain, Check, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, type Brand } from '../api'
import { Button, Card, Field, Input, Spinner, Textarea, fmtDate } from '../ui'

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
              className={`rounded-xl border px-3 py-2 text-left text-sm transition ${form.default_style === s ? 'border-brand-500 bg-brand-50 ring-4 ring-brand-500/15' : 'border-line bg-surface hover:border-brand-200 hover:bg-surface-2'}`}
            >
              <div className="font-semibold capitalize">{s}</div>
              <div className="text-xs text-ink-faint">{STYLE_HINTS[s]}</div>
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
              className="w-full rounded-xl border border-line bg-surface-2/50 px-3.5 py-2.5 text-sm text-ink outline-none transition hover:border-brand-200 focus:border-brand-500 focus:bg-surface focus:ring-4 focus:ring-brand-500/15"
            >
              <option value="none">None</option>
              <option value="some">Some</option>
              <option value="lots">Lots</option>
            </select>
          </Field>
          <Field label="Caption highlight colour">
            <div className="flex items-center gap-2">
              <input type="color" value={form.accent_color} onChange={(e) => set('accent_color', e.target.value)} className="h-10 w-14 shrink-0 cursor-pointer rounded-lg border border-line bg-surface p-1" />
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

interface Taste {
  notes: string[]
  updated_at: string | null
  signals_seen: number
}

const MAX_NOTES = 8
const MAX_LINE = 120

function TasteMemory() {
  const qc = useQueryClient()
  const taste = useQuery({ queryKey: ['taste'], queryFn: () => api<Taste>('/api/brand/taste') })
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [adding, setAdding] = useState('')
  const [busy, setBusy] = useState(false)
  if (!taste.data) return taste.isError ? <p className="text-sm text-danger">Could not load what the AI learned.</p> : <Spinner />
  const notes = taste.data.notes

  const save = async (next: string[]) => {
    setBusy(true)
    try {
      const saved = await api<Taste>('/api/brand/taste', { method: 'PUT', json: { notes: next } })
      qc.setQueryData(['taste'], saved)
      setEditing(null)
      return true
    } catch (err) {
      toast.error((err as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }
  const clear = async () => {
    if (!window.confirm('Forget everything the AI learned about your style?')) return
    setBusy(true)
    try {
      qc.setQueryData(['taste'], await api<Taste>('/api/brand/taste', { method: 'DELETE' }))
      setEditing(null)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const commitEdit = () => {
    const text = draft.trim()
    if (editing === null) return
    if (!text) return void save(notes.filter((_, i) => i !== editing))
    void save(notes.map((n, i) => (i === editing ? text : n)))
  }
  const add = async () => {
    const text = adding.trim()
    if (text && (await save([...notes, text]))) setAdding('')
  }

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 font-display text-2xl font-semibold tracking-tight">
            <Brain className="h-5 w-5 text-brand-600" /> What the AI learned about your style
          </h2>
          <p className="text-sm text-ink-soft">
            Learned from your own choices. Every edit and caption follows these. Edit or delete anything you disagree with.
          </p>
        </div>
        {notes.length > 0 && (
          <Button variant="danger" onClick={clear} disabled={busy} className="px-3 py-1.5">
            Clear all
          </Button>
        )}
      </div>

      {notes.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line bg-surface-2/50 px-4 py-5 text-center text-sm text-ink-soft">
          Ask for changes or pick captions and I'll learn your style.
        </p>
      ) : (
        <ul className="space-y-2">
          {notes.map((note, i) => (
            <li key={`${i}-${note}`} className="flex items-center gap-2 rounded-xl border border-line bg-surface-2/50 px-3 py-2">
              {editing === i ? (
                <>
                  <Input
                    autoFocus
                    value={draft}
                    maxLength={MAX_LINE}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') commitEdit()
                      if (e.key === 'Escape') setEditing(null)
                    }}
                  />
                  <Button variant="ghost" aria-label="Save" onClick={commitEdit} disabled={busy} className="px-2 py-2">
                    <Check className="h-4 w-4" />
                  </Button>
                  <Button variant="ghost" aria-label="Cancel" onClick={() => setEditing(null)} className="px-2 py-2">
                    <X className="h-4 w-4" />
                  </Button>
                </>
              ) : (
                <>
                  <span className="min-w-0 flex-1 break-words text-sm text-ink">{note}</span>
                  <Button
                    variant="ghost"
                    aria-label="Edit"
                    onClick={() => {
                      setEditing(i)
                      setDraft(note)
                    }}
                    className="px-2 py-2"
                  >
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button variant="ghost" aria-label="Delete" onClick={() => save(notes.filter((_, j) => j !== i))} disabled={busy} className="px-2 py-2">
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {notes.length < MAX_NOTES && (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            void add()
          }}
        >
          <Input value={adding} maxLength={MAX_LINE} onChange={(e) => setAdding(e.target.value)} placeholder="Add a preference, e.g. No emojis in captions" />
          <Button type="submit" variant="secondary" disabled={!adding.trim() || busy} aria-label="Add a preference">
            <Plus className="h-4 w-4" /> Add
          </Button>
        </form>
      )}
      {taste.data.updated_at && notes.length > 0 && <p className="text-xs text-ink-faint">Last updated {fmtDate(taste.data.updated_at)}</p>}
    </Card>
  )
}

export default function BrandPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="font-display text-4xl font-semibold tracking-tight">Brand kit</h1>
        <p className="text-sm text-ink-soft">The AI editor and caption writer follow these on every video.</p>
      </div>
      <Card>
        <BrandForm />
      </Card>
      <TasteMemory />
    </div>
  )
}
