import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Check, Copy, ShieldCheck, Trash2, TriangleAlert } from 'lucide-react'
import { api } from '../api'
import { Button, Card, Input, Spinner, fmtDate } from '../ui'

interface TokenRow {
  id: string
  name: string
  prefix: string
  created_at: string
  last_used_at: string | null
}

interface NewToken extends TokenRow {
  token: string
}

function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setDone(true)
      setTimeout(() => setDone(false), 1800)
    } catch {
      toast.error('Could not copy. Select the text and copy it by hand.')
    }
  }
  return (
    <Button variant="secondary" onClick={copy} className="shrink-0 !px-3 !py-2">
      {done ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      {done ? 'Copied' : label}
    </Button>
  )
}

function Snippet({ title, text }: { title: string; text: string }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink-soft">{title}</h3>
        <CopyButton text={text} />
      </div>
      <pre className="overflow-x-auto rounded-xl border border-line bg-surface-2 p-3 text-xs leading-relaxed text-ink">{text}</pre>
    </div>
  )
}

export default function Connect() {
  const qc = useQueryClient()
  const tokens = useQuery({ queryKey: ['mcp-tokens'], queryFn: () => api<TokenRow[]>('/api/mcp/tokens') })
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [fresh, setFresh] = useState<NewToken | null>(null)

  const url = `${window.location.origin}/mcp`
  const token = fresh?.token ?? '<your-token>'
  const claudeCode = `claude mcp add --transport http socialagent ${url} --header "Authorization: Bearer ${token}"`
  const desktop = JSON.stringify(
    {
      mcpServers: {
        socialagent: {
          command: 'npx',
          args: ['mcp-remote', url, '--header', `Authorization: Bearer ${token}`],
        },
      },
    },
    null,
    2,
  )

  const create = async () => {
    setCreating(true)
    try {
      const made = await api<NewToken>('/api/mcp/tokens', { method: 'POST', json: { name: name.trim() || 'AI assistant' } })
      setFresh(made)
      setName('')
      qc.invalidateQueries({ queryKey: ['mcp-tokens'] })
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setCreating(false)
    }
  }

  const revoke = async (t: TokenRow) => {
    if (!window.confirm(`Revoke "${t.name}"? Any assistant using it loses access immediately.`)) return
    try {
      await api(`/api/mcp/tokens/${t.id}`, { method: 'DELETE' })
      if (fresh?.id === t.id) setFresh(null)
      qc.invalidateQueries({ queryKey: ['mcp-tokens'] })
      toast.success('Token revoked')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="font-display text-4xl font-semibold tracking-tight">AI assistants</h1>
        <p className="max-w-2xl text-ink-soft">
          Connect Claude Code, Claude Desktop or any MCP client. Your assistant can review drafts, ask for edits and pick captions.
        </p>
        <p className="inline-flex items-start gap-2 rounded-xl bg-brand-50 px-3 py-2 text-sm text-brand-800">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
          Any AI can ask, only you approve. Posting always needs your own approval on WhatsApp or in chat.
        </p>
      </div>

      <Card className="space-y-4">
        <h2 className="font-display text-xl font-semibold">Create a token</h2>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name, e.g. Claude Code on my laptop"
            maxLength={64}
            aria-label="Token name"
            onKeyDown={(e) => e.key === 'Enter' && !creating && create()}
          />
          <Button onClick={create} loading={creating} className="shrink-0">
            Create token
          </Button>
        </div>

        {fresh && (
          <div className="space-y-2 rounded-xl border border-warn/40 bg-warn-soft p-3">
            <p className="flex items-start gap-2 text-sm font-semibold text-warn">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
              Copy it now. It is shown once. Treat it like a password.
            </p>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 break-all rounded-lg bg-surface px-3 py-2 text-xs text-ink">{fresh.token}</code>
              <CopyButton text={fresh.token} />
            </div>
          </div>
        )}

        <div className="divide-y divide-line">
          {tokens.isLoading && <Spinner />}
          {tokens.data?.length === 0 && <p className="text-sm text-ink-faint">No tokens yet.</p>}
          {tokens.data?.map((t) => (
            <div key={t.id} className="flex items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="truncate font-semibold text-ink">{t.name}</p>
                <p className="text-xs text-ink-faint">
                  <code>{t.prefix}…</code> · created {fmtDate(t.created_at)} · {t.last_used_at ? `last used ${fmtDate(t.last_used_at)}` : 'never used'}
                </p>
              </div>
              <Button variant="danger" onClick={() => revoke(t)} aria-label={`Revoke ${t.name}`} className="shrink-0 !px-3 !py-2">
                <Trash2 className="h-4 w-4" />
                <span className="hidden sm:inline">Revoke</span>
              </Button>
            </div>
          ))}
        </div>
      </Card>

      <Card className="space-y-5">
        <div>
          <h2 className="font-display text-xl font-semibold">Set up your assistant</h2>
          <p className="text-sm text-ink-soft">
            {fresh ? 'Your new token is filled in below.' : 'Create a token first, then replace <your-token> below.'}
          </p>
        </div>
        <Snippet title="Claude Code" text={claudeCode} />
        <Snippet title="Claude Desktop or any other client (config JSON)" text={desktop} />
      </Card>
    </div>
  )
}
