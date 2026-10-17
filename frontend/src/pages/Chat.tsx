import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Paperclip, Send } from 'lucide-react'
import { toast } from 'sonner'
import { api, type ChatMessage } from '../api'
import { Button, Spinner } from '../ui'

function Bubble({ m }: { m: ChatMessage }) {
  const mine = m.direction === 'in'
  return (
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm break-words text-ink shadow-xs sm:max-w-[70%] ${mine ? 'rounded-tr-sm bg-bubble' : 'rounded-tl-sm bg-surface'}`}>
        {m.video_url && <video src={m.video_url} controls playsInline className="mb-1.5 max-h-96 w-full rounded-lg bg-black" />}
        {m.text && <p className="whitespace-pre-wrap">{m.text.replace(/\*(.+?)\*/g, '$1')}</p>}
        <div className="mt-1 flex items-center justify-end gap-2 text-[10px] text-ink-faint">
          {m.channel === 'whatsapp' && <span className="font-semibold text-wa-dark dark:text-wa">WhatsApp</span>}
          {m.draft_id && !mine && (
            <Link to={`/app/drafts/${m.draft_id}`} className="font-semibold text-brand-600">
              open draft
            </Link>
          )}
          {new Date(m.at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
        </div>
      </div>
    </div>
  )
}

export default function Chat() {
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const messages = useQuery({
    queryKey: ['chat'],
    queryFn: () => api<ChatMessage[]>('/api/chat/messages'),
    refetchInterval: 2000,
  })
  const count = messages.data?.length || 0
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [count])

  const send = async (e?: FormEvent) => {
    e?.preventDefault()
    const value = text.trim()
    if (!value) return
    setText('')
    try {
      await api('/api/chat/messages', { method: 'POST', json: { text: value } })
      setTimeout(() => qc.invalidateQueries({ queryKey: ['chat'] }), 600)
    } catch (err) {
      setText(value) // keep what they typed
      toast.error((err as Error).message)
    }
  }

  const upload = async (file: File) => {
    setUploading(true)
    try {
      const body = new FormData()
      body.append('file', file)
      body.append('caption', text.trim())
      setText('')
      await api('/api/chat/upload', { method: 'POST', body })
      toast.success('Video sent')
      qc.invalidateQueries({ queryKey: ['chat'] })
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-10rem)] max-w-3xl flex-col overflow-hidden rounded-2xl border border-line shadow-md md:h-[calc(100dvh-7.5rem)]">
      <div className="flex items-center gap-3 bg-wa-dark px-4 py-3 text-white">
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-white/20">🎬</div>
        <div className="min-w-0">
          <div className="font-semibold">Your AI video editor</div>
          <div className="text-xs text-white/80">Same assistant as on WhatsApp. Send a video to start.</div>
        </div>
      </div>
      <div className="chat-bg flex-1 space-y-2 overflow-y-auto p-4">
        {messages.isLoading && <Spinner />}
        {messages.data?.length === 0 && (
          <div className="mx-auto mt-10 max-w-sm rounded-xl bg-surface/90 p-4 text-center text-sm text-ink-soft shadow-sm">
            Attach a video with the 📎 button. Add a note first (for example "promo for our weekend sale") and it will be used for the caption.
          </div>
        )}
        {messages.data?.map((m) => <Bubble key={m.id} m={m} />)}
        <div ref={bottomRef} />
      </div>
      <form onSubmit={send} className="flex items-center gap-2 border-t border-line bg-surface p-3">
        <input ref={fileRef} type="file" accept="video/*" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        <Button type="button" variant="ghost" onClick={() => fileRef.current?.click()} loading={uploading} title="Attach video">
          {!uploading && <Paperclip className="h-5 w-5" />}
        </Button>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type a reply, e.g. 1 or 'make it cinematic'"
          className="min-w-0 flex-1 rounded-full border border-line bg-surface-2/60 px-4 py-2.5 text-sm text-ink outline-none transition placeholder:text-ink-faint focus:border-wa focus:bg-surface focus:ring-4 focus:ring-wa/15"
        />
        <Button type="submit" variant="wa" className="rounded-full px-3" disabled={!text.trim()}>
          <Send className="h-4 w-4" />
        </Button>
      </form>
    </div>
  )
}
