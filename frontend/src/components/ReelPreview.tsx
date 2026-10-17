import { useEffect, useRef, useState } from 'react'
import { Bookmark, Camera, Eye, Heart, Loader2, MessageCircle, MoreHorizontal, Music2, Pause, Play, Send, Volume2, VolumeX } from 'lucide-react'

/*
 * What the post will look like on Instagram, before anything is posted: the edited Reel inside a phone,
 * with the account name, the chosen caption and hashtags laid over it like the real Reels UI.
 */

export interface ReelPreviewProps {
  videoUrl: string | null
  posterUrl?: string | null
  username?: string | null
  avatarUrl?: string | null
  caption?: string | null
  hashtags?: string[]
  /** Shown over the screen while there is no video yet, e.g. "Editing…". */
  busyLabel?: string | null
  /** Chip under the phone, e.g. "Preview · not posted yet". Pass null to hide. */
  badge?: string | null
  className?: string
}

function prefersReducedMotion() {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

export default function ReelPreview({
  videoUrl,
  posterUrl,
  username,
  avatarUrl,
  caption,
  hashtags = [],
  busyLabel,
  badge = 'Preview · not posted yet',
  className = '',
}: ReelPreviewProps) {
  const ref = useRef<HTMLVideoElement>(null)
  const [reduced] = useState(prefersReducedMotion)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(true)
  const [progress, setProgress] = useState(0)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    setProgress(0)
    setPlaying(false)
    setMuted(true)
  }, [videoUrl])

  const toggle = () => {
    const v = ref.current
    if (!v) return
    if (v.paused) void v.play().catch(() => undefined)
    else v.pause()
  }

  const toggleMute = () => {
    const v = ref.current
    if (!v) return
    v.muted = !v.muted
    setMuted(v.muted)
  }

  const handle = (username || 'yourbrand').replace(/^@/, '')
  const tags = hashtags.map((t) => `#${t.replace(/^#/, '')}`).join(' ')
  const text = [caption?.trim(), tags].filter(Boolean).join('\n')

  return (
    <figure className={`mx-auto w-full max-w-[300px] ${className}`} aria-label="Instagram Reel preview">
      <div className="rounded-[2.6rem] bg-brand-900 p-2 shadow-2xl ring-1 ring-line dark:bg-black">
        <div className="relative aspect-[9/19] overflow-hidden rounded-[2.15rem] bg-black text-white">
          {videoUrl ? (
            <video
              key={videoUrl}
              ref={ref}
              src={videoUrl}
              poster={posterUrl || undefined}
              autoPlay={!reduced}
              muted
              loop
              playsInline
              preload="metadata"
              onClick={toggle}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onTimeUpdate={(e) => {
                const v = e.currentTarget
                setProgress(v.duration ? v.currentTime / v.duration : 0)
              }}
              className="absolute inset-0 h-full w-full cursor-pointer object-cover"
            />
          ) : posterUrl ? (
            <img src={posterUrl} alt="" className="absolute inset-0 h-full w-full object-cover opacity-70" />
          ) : (
            <div className="absolute inset-0 bg-gradient-to-b from-white/15 to-black" />
          )}

          {!videoUrl && busyLabel && (
            <div className="absolute inset-0 grid place-items-center bg-black/40" role="status">
              <div className="flex flex-col items-center gap-2 text-sm font-semibold">
                <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none" aria-hidden />
                {busyLabel}
              </div>
            </div>
          )}

          {/* top: notch + Reels header */}
          <span aria-hidden className="absolute top-2 left-1/2 z-20 h-5 w-20 -translate-x-1/2 rounded-full bg-black" />
          <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-between bg-gradient-to-b from-black/50 to-transparent px-4 pt-9 pb-6">
            <span className="text-lg font-bold tracking-tight drop-shadow">Reels</span>
            <Camera className="h-5 w-5 drop-shadow" />
          </div>

          {videoUrl && (
            <button
              type="button"
              onClick={toggleMute}
              aria-label={muted ? 'Unmute preview' : 'Mute preview'}
              className="absolute top-20 right-3 z-20 grid h-8 w-8 place-items-center rounded-full bg-black/45 backdrop-blur-sm transition hover:bg-black/60 focus-visible:ring-2 focus-visible:ring-white focus-visible:outline-none"
            >
              {muted ? <VolumeX className="h-4 w-4" aria-hidden /> : <Volume2 className="h-4 w-4" aria-hidden />}
            </button>
          )}

          {videoUrl && !playing && (
            <button
              type="button"
              onClick={toggle}
              aria-label="Play preview"
              className="absolute top-1/2 left-1/2 z-20 grid h-16 w-16 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-black/45 backdrop-blur-sm transition hover:scale-105 focus-visible:ring-2 focus-visible:ring-white focus-visible:outline-none motion-reduce:transition-none motion-reduce:hover:scale-100"
            >
              <Play className="ml-1 h-7 w-7 fill-white" aria-hidden />
            </button>
          )}
          {videoUrl && playing && (
            <button type="button" onClick={toggle} aria-label="Pause preview" className="sr-only focus:not-sr-only focus:absolute focus:top-1/2 focus:left-1/2 focus:z-20 focus:grid focus:h-14 focus:w-14 focus:-translate-x-1/2 focus:-translate-y-1/2 focus:place-items-center focus:rounded-full focus:bg-black/50 focus:ring-2 focus:ring-white focus:outline-none">
              <Pause className="h-6 w-6 fill-white" aria-hidden />
            </button>
          )}

          {/* right rail */}
          <div aria-hidden className="pointer-events-none absolute right-2.5 bottom-24 z-10 flex flex-col items-center gap-4 text-[10px] font-semibold drop-shadow">
            <span className="flex flex-col items-center gap-0.5">
              <Heart className="h-6 w-6" />
              Like
            </span>
            <span className="flex flex-col items-center gap-0.5">
              <MessageCircle className="h-6 w-6" />
              0
            </span>
            <Send className="h-6 w-6" />
            <Bookmark className="h-6 w-6" />
            <MoreHorizontal className="h-6 w-6" />
          </div>

          {/* bottom: account, caption, audio */}
          <div className={`absolute inset-x-0 bottom-0 z-10 bg-gradient-to-t px-3 pt-16 pb-4 ${expanded ? 'from-black/85 via-black/60' : 'from-black/70'} to-transparent`}>
            <div className="flex items-center gap-2 pr-12">
              <span className="ig-gradient grid h-8 w-8 shrink-0 place-items-center rounded-full p-[2px]">
                {avatarUrl ? (
                  <img src={avatarUrl} alt="" className="h-full w-full rounded-full border-2 border-black object-cover" />
                ) : (
                  <span className="grid h-full w-full place-items-center rounded-full border-2 border-black bg-white/20 text-xs font-bold uppercase">{handle.charAt(0)}</span>
                )}
              </span>
              <span className="truncate text-sm font-semibold">{handle}</span>
              <span aria-hidden className="shrink-0 rounded-lg border border-white/70 px-2 py-0.5 text-[11px] font-semibold">
                Follow
              </span>
            </div>
            {text ? (
              <div className="mt-2 pr-12 text-[13px] leading-snug">
                <p className={`whitespace-pre-line drop-shadow ${expanded ? 'max-h-48 overflow-y-auto' : 'line-clamp-2'}`}>{text}</p>
                {text.length > 70 && (
                  <button
                    type="button"
                    onClick={() => setExpanded((x) => !x)}
                    aria-expanded={expanded}
                    className="mt-0.5 rounded text-[13px] font-semibold text-white/75 hover:text-white focus-visible:ring-2 focus-visible:ring-white focus-visible:outline-none"
                  >
                    {expanded ? 'less' : 'more'}
                  </button>
                )}
              </div>
            ) : (
              <p className="mt-2 pr-12 text-[13px] text-white/60 italic">Caption appears here once you pick one.</p>
            )}
            <div className="mt-2 flex items-center gap-1.5 pr-12 text-xs text-white/85">
              <Music2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
              <span className="truncate">{handle} · Original audio</span>
            </div>
          </div>

          {videoUrl && (
            <div className="absolute inset-x-0 bottom-0 z-20 h-0.5 bg-white/20" aria-hidden>
              <div className="h-full bg-white" style={{ width: `${progress * 100}%` }} />
            </div>
          )}
        </div>
      </div>
      {badge && (
        <figcaption className="mt-3 flex items-center justify-center gap-1.5 text-xs font-semibold text-ink-soft">
          <Eye className="h-3.5 w-3.5" aria-hidden /> {badge}
        </figcaption>
      )}
    </figure>
  )
}
