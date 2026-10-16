/**
 * Decide what the gateway forwards. The bot runs on a personal number, so it must stay silent for everyone
 * except linked users and people sending a link code. Content from other chats is never forwarded or stored.
 */
import {
  getContentType,
  isJidBroadcast,
  isJidGroup,
  isJidNewsletter,
  isJidStatusBroadcast,
  normalizeMessageContent,
  type WAMessage,
} from 'baileys'

export const LINK_RE = /LINK-[A-Z0-9]{6}/i

export type Kind = 'text' | 'video' | 'audio' | 'image' | 'reaction' | 'other'

export interface Parsed {
  id: string
  jid: string
  jidAlt: string | null
  kind: Kind
  text: string
  reaction: string | null
  mediaSize: number
  mediaExt: string
}

export function isIgnoredChat(jid: string): boolean {
  return Boolean(isJidGroup(jid) || isJidBroadcast(jid) || isJidStatusBroadcast(jid) || isJidNewsletter(jid))
}

export function parseMessage(m: WAMessage): Parsed | null {
  const jid = m.key.remoteJid
  if (!m.message || m.key.fromMe || !jid || !m.key.id || isIgnoredChat(jid)) return null
  const content = normalizeMessageContent(m.message)
  if (!content) return null
  const type = getContentType(content)
  const base: Parsed = {
    id: m.key.id,
    jid,
    jidAlt: m.key.remoteJidAlt || null,
    kind: 'other',
    text: '',
    reaction: null,
    mediaSize: 0,
    mediaExt: '',
  }
  switch (type) {
    case 'conversation':
      return { ...base, kind: 'text', text: content.conversation || '' }
    case 'extendedTextMessage':
      return { ...base, kind: 'text', text: content.extendedTextMessage?.text || '' }
    case 'videoMessage':
      return {
        ...base,
        kind: 'video',
        text: content.videoMessage?.caption || '',
        mediaSize: Number(content.videoMessage?.fileLength || 0),
        mediaExt: '.mp4',
      }
    case 'documentMessage': {
      const doc = content.documentMessage
      if (!doc?.mimetype?.startsWith('video/')) return base
      const ext = (doc.fileName?.match(/\.[a-z0-9]{2,4}$/i)?.[0] || '.mp4').toLowerCase()
      return { ...base, kind: 'video', text: doc.caption || '', mediaSize: Number(doc.fileLength || 0), mediaExt: ext }
    }
    case 'audioMessage':
      return { ...base, kind: 'audio', mediaSize: Number(content.audioMessage?.fileLength || 0), mediaExt: '.ogg' }
    case 'imageMessage':
      return { ...base, kind: 'image', text: content.imageMessage?.caption || '' }
    case 'reactionMessage': {
      const emoji = content.reactionMessage?.text || ''
      return emoji ? { ...base, kind: 'reaction', reaction: emoji } : null
    }
    default:
      return base
  }
}

/** Forward only for linked users, or a link-code text from anyone. */
export function shouldForward(p: Parsed, allowlist: Set<string>): boolean {
  if (allowlist.has(p.jid) || (p.jidAlt && allowlist.has(p.jidAlt))) return true
  return p.kind === 'text' && LINK_RE.test(p.text)
}
