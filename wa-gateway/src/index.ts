/**
 * WhatsApp gateway (Baileys). Owns no business logic: it forwards allowed inbound messages to FastAPI and sends
 * what FastAPI asks it to. Listens on 127.0.0.1 only; every request needs the shared secret.
 */
import { createWriteStream } from 'node:fs'
import { mkdir, stat } from 'node:fs/promises'
import path from 'node:path'
import { pipeline } from 'node:stream/promises'
import type { Readable } from 'node:stream'
import express, { type NextFunction, type Request, type Response } from 'express'
import pino from 'pino'
import makeWASocket, {
  Browsers,
  DisconnectReason,
  downloadMediaMessage,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
  type proto,
  type WAMessage,
  type WASocket,
} from 'baileys'
import { createAuthStore, type AuthStore } from './authState.js'
import { config } from './config.js'
import { parseMessage, shouldForward, type Parsed } from './filters.js'

const logger = pino({ level: config.logLevel })
const log = pino({ level: 'info' })

type Status = 'starting' | 'disabled' | 'qr' | 'connecting' | 'open' | 'closed' | 'logged_out'
const state = {
  status: 'starting' as Status,
  qr: null as string | null,
  pairingCode: null as string | null,
  me: null as { id: string; name?: string } | null,
  lastError: null as string | null,
  paused: false,
}

let sock: WASocket | null = null
let store: AuthStore | null = null
let backoffMs = 2000
let reconnectTimer: NodeJS.Timeout | null = null
const allowlist = new Set<string>()
const sentCache = new Map<string, proto.IMessage>() // for Baileys retries (getMessage)

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function remember(id: string | null | undefined, message: proto.IMessage | null | undefined) {
  if (!id || !message) return
  sentCache.set(id, message)
  if (sentCache.size > 500) sentCache.delete(sentCache.keys().next().value as string)
}

// ------------------------------------------------------------------ talking to FastAPI

async function api(pathname: string, init: RequestInit = {}) {
  const res = await fetch(`${config.apiUrl}${pathname}`, {
    ...init,
    headers: { 'content-type': 'application/json', 'x-internal-secret': config.secret, ...(init.headers || {}) },
  })
  if (!res.ok) throw new Error(`API ${pathname} -> ${res.status}`)
  return res.json()
}

async function refreshAllowlist() {
  try {
    const data = (await api('/internal/wa/allowlist')) as { jids: string[] }
    allowlist.clear()
    for (const jid of data.jids) allowlist.add(jid)
  } catch (err) {
    log.warn({ err: String(err) }, 'allowlist refresh failed')
  }
}

async function forward(event: Record<string, unknown>) {
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      await api('/internal/wa/events', { method: 'POST', body: JSON.stringify({ events: [event] }) })
      return
    } catch (err) {
      log.warn({ err: String(err), attempt }, 'forward failed')
      await sleep(1000 * 2 ** attempt)
    }
  }
}

// ------------------------------------------------------------------ inbound

async function saveMedia(m: WAMessage, p: Parsed): Promise<string> {
  const dir = path.join(config.mediaDir, 'in')
  await mkdir(dir, { recursive: true })
  const file = path.join(dir, `wa_${p.id.replace(/[^A-Za-z0-9_-]/g, '')}${p.mediaExt || '.bin'}`)
  const stream = (await downloadMediaMessage(m, 'stream', {}, {
    logger,
    reuploadRequest: sock!.updateMediaMessage,
  })) as Readable
  await pipeline(stream, createWriteStream(file))
  return file
}

async function onMessage(m: WAMessage) {
  const p = parseMessage(m)
  if (!p || !shouldForward(p, allowlist)) return // not ours: stay silent, store nothing
  if (state.paused) return
  const linked = allowlist.has(p.jid) || (p.jidAlt !== null && allowlist.has(p.jidAlt))
  if (linked) await sock?.readMessages([m.key]).catch(() => undefined)

  const event: Record<string, unknown> = {
    id: p.id,
    jid: p.jid,
    jid_alt: p.jidAlt,
    kind: p.kind,
    text: p.text,
    reaction: p.reaction,
  }
  if (linked && (p.kind === 'video' || p.kind === 'audio')) {
    if (p.mediaSize > config.maxUploadMb * 1024 * 1024) {
      event.too_large = true
    } else {
      try {
        event.media_path = await saveMedia(m, p)
      } catch (err) {
        log.warn({ err: String(err) }, 'media download failed')
        event.too_large = true
      }
    }
  }
  await forward(event)
}

// ------------------------------------------------------------------ socket lifecycle

function scheduleReconnect(ms: number) {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  reconnectTimer = setTimeout(() => void connect(), ms)
}

async function connect() {
  if (!config.enabled) {
    state.status = 'disabled'
    return
  }
  state.status = 'connecting'
  store ??= await createAuthStore()
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }))
  sock = makeWASocket({
    version,
    auth: { creds: store.creds, keys: makeCacheableSignalKeyStore(store.keys, logger) },
    logger,
    browser: Browsers.ubuntu('Chrome'),
    markOnlineOnConnect: false,
    syncFullHistory: false, // default history sync stays on: v7 needs it for LID <-> phone mappings
    getMessage: async (key) => (key.id ? sentCache.get(key.id) : undefined),
  })
  const current = sock
  current.ev.on('creds.update', () => void store?.saveCreds())

  current.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update
    if (qr) {
      state.qr = qr
      state.status = 'qr'
    }
    if (connection === 'open') {
      state.status = 'open'
      state.qr = null
      state.pairingCode = null
      state.lastError = null
      state.me = current.user ? { id: current.user.id, name: current.user.name } : null
      backoffMs = 2000
      await refreshAllowlist()
      log.info({ me: state.me?.id }, 'whatsapp connected')
    }
    if (connection === 'close') {
      const code = (lastDisconnect?.error as { output?: { statusCode?: number } } | undefined)?.output?.statusCode
      state.lastError = `${code ?? ''} ${lastDisconnect?.error?.message ?? ''}`.trim()
      state.me = null
      if (sock !== current) return // an old socket closing after we already replaced it
      if (code === DisconnectReason.loggedOut) {
        state.status = 'logged_out'
        log.warn('logged out: clearing session; open the admin page to pair again')
        await store?.clear()
        store = null
        scheduleReconnect(3000)
      } else if (code === DisconnectReason.connectionReplaced) {
        state.status = 'closed'
        log.warn('another session took over (redeploy overlap?); backing off 60s')
        scheduleReconnect(60_000)
      } else if (code === DisconnectReason.restartRequired) {
        scheduleReconnect(500)
      } else {
        state.status = 'closed'
        scheduleReconnect(backoffMs)
        backoffMs = Math.min(backoffMs * 2, 60_000)
      }
    }
  })

  current.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return // skip history sync / appends
    for (const m of messages) {
      try {
        await onMessage(m)
      } catch (err) {
        log.warn({ err: String(err) }, 'message handling failed')
      }
    }
  })
}

// ------------------------------------------------------------------ HTTP API for FastAPI

const app = express()
app.use(express.json({ limit: '1mb' }))
app.use((req: Request, res: Response, next: NextFunction) => {
  if (req.get('x-internal-secret') !== config.secret) {
    res.status(403).json({ error: 'forbidden' })
    return
  }
  next()
})

function requireOpen(res: Response): WASocket | null {
  if (!sock || state.status !== 'open') {
    res.status(503).json({ error: `whatsapp not connected (${state.status})` })
    return null
  }
  if (state.paused) {
    res.status(423).json({ error: 'gateway paused' })
    return null
  }
  return sock
}

async function humanPause(s: WASocket, jid: string, chars: number) {
  await s.sendPresenceUpdate('composing', jid).catch(() => undefined)
  await sleep(500 + Math.min(2000, chars * 12))
}

app.get('/status', (_req, res) => {
  res.json({
    status: state.status,
    me: state.me,
    qr: state.qr,
    pairing_code: state.pairingCode,
    last_error: state.lastError,
    paused: state.paused,
    allowlist_size: allowlist.size,
  })
})

app.post('/send-text', async (req, res) => {
  const s = requireOpen(res)
  if (!s) return
  const { jid, text } = req.body as { jid: string; text: string }
  try {
    await humanPause(s, jid, text.length)
    const sent = await s.sendMessage(jid, { text })
    await s.sendPresenceUpdate('paused', jid).catch(() => undefined)
    remember(sent?.key.id, sent?.message)
    res.json({ id: sent?.key.id ?? null })
  } catch (err) {
    res.status(500).json({ error: String(err) })
  }
})

app.post('/send-video', async (req, res) => {
  const s = requireOpen(res)
  if (!s) return
  const { jid, path: file, caption } = req.body as { jid: string; path: string; caption?: string }
  const resolved = path.resolve(file)
  if (!resolved.startsWith(config.mediaDir + path.sep)) {
    res.status(400).json({ error: 'path outside media dir' })
    return
  }
  try {
    await stat(resolved)
    await humanPause(s, jid, 40)
    const sent = await s.sendMessage(jid, { video: { url: resolved }, caption: caption || undefined, mimetype: 'video/mp4' })
    await s.sendPresenceUpdate('paused', jid).catch(() => undefined)
    remember(sent?.key.id, sent?.message)
    res.json({ id: sent?.key.id ?? null })
  } catch (err) {
    res.status(500).json({ error: String(err) })
  }
})

app.post('/typing', async (req, res) => {
  const { jid } = req.body as { jid: string }
  if (sock && state.status === 'open' && !state.paused) await sock.sendPresenceUpdate('composing', jid).catch(() => undefined)
  res.json({ ok: true })
})

app.post('/pair-code', async (req, res) => {
  const { phone } = req.body as { phone: string }
  if (!sock || state.status === 'open') {
    res.status(409).json({ error: state.status === 'open' ? 'already paired' : 'socket not ready' })
    return
  }
  try {
    state.pairingCode = await sock.requestPairingCode(String(phone).replace(/\D/g, ''))
    res.json({ code: state.pairingCode })
  } catch (err) {
    res.status(500).json({ error: String(err) })
  }
})

app.post('/logout', async (_req, res) => {
  try {
    await sock?.logout()
  } catch {
    // socket may already be closed; clearing the store below still resets pairing
  }
  await store?.clear()
  store = null
  state.status = 'logged_out'
  scheduleReconnect(2000)
  res.json({ ok: true })
})

app.post('/pause', (req, res) => {
  state.paused = Boolean((req.body as { paused?: boolean }).paused)
  res.json({ paused: state.paused })
})

app.post('/allowlist/add', (req, res) => {
  for (const jid of (req.body as { jids?: string[] }).jids || []) if (jid) allowlist.add(jid)
  res.json({ size: allowlist.size })
})

app.listen(config.port, config.host, () => {
  log.info(`wa-gateway listening on ${config.host}:${config.port} (media: ${config.mediaDir})`)
})
setInterval(() => void refreshAllowlist(), 20_000)
void connect()
