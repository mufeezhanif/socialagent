export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init
  const res = await fetch(path, {
    credentials: 'include',
    ...rest,
    headers: json !== undefined ? { 'content-type': 'application/json', ...(headers || {}) } : headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })
  if (!res.ok) {
    let message = res.statusText
    try {
      const data = await res.json()
      message = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data)
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, message)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export interface Me {
  id: string
  email: string
  name: string
  timezone: string
  is_admin: boolean
  app_name: string
  instagram: { username: string; account_type: string; profile_picture_url: string; status: string } | null
  whatsapp: { linked: boolean; phone: string; pending_code: string | null } | null
  instagram_configured: boolean
}

export interface DraftSummary {
  id: string
  status: string
  status_label: string
  channel: string
  style: string
  revision: number
  duration_in: number | null
  duration_out: number | null
  cover_url: string | null
  caption_final: string | null
  publish_at: string | null
  ig_permalink: string | null
  created_at: string
  updated_at: string | null
}

export interface CaptionPack {
  options: { style: string; text: string }[]
  hashtags: string[]
  facts_to_confirm: string[]
}

export interface DraftDetail extends DraftSummary {
  source_url: string | null
  master_url: string | null
  preview_url: string | null
  edit_summary: string[]
  storyboard: Record<string, unknown>
  transcript: string
  user_context: string | null
  revision_notes: string[]
  caption_pack: CaptionPack | null
  hashtags_final: string[]
  error: string | null
  failed_stage: string | null
  gates: { video_approved: boolean; caption_approved: boolean; publish_confirmed: boolean }
  events: { actor: 'ai' | 'human' | 'system'; action: string; detail: Record<string, unknown>; at: string }[]
}

export interface ChatMessage {
  id: string
  direction: 'in' | 'out'
  channel: string
  kind: string
  text: string
  video_url: string | null
  draft_id: string | null
  at: string
}

export interface Brand {
  niche: string
  tone: string
  audience: string
  emoji_level: 'none' | 'some' | 'lots'
  cta: string
  default_hashtags: string[]
  banned_words: string[]
  primary_color: string
  accent_color: string
  default_style: string
  preferred_post_time: string
  timezone: string
  styles: string[]
}

export const WORKING = new Set(['processing', 'revising', 'captioning', 'publishing'])
