import type { ReactNode } from 'react'

/*
 * Loading placeholders shaped like the real content, so pages don't jump when data arrives.
 * Pulse is turned off for prefers-reduced-motion.
 */

export function Shimmer({ className = '' }: { className?: string }) {
  return <div aria-hidden className={`animate-pulse rounded-xl bg-surface-2 motion-reduce:animate-none ${className}`} />
}

function Loading({ label, children, className = '' }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className={className}>
      <span className="sr-only">{label}</span>
      {children}
    </div>
  )
}

/** Dashboard: matches the 2 / 3 / 5 column grid of DraftCard. */
export function DraftGridSkeleton({ count = 5, className = '' }: { count?: number; className?: string }) {
  return (
    <Loading label="Loading your drafts" className={`space-y-3 ${className}`}>
      <Shimmer className="h-4 w-32" />
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: count }, (_, i) => (
          <div key={i} className="overflow-hidden rounded-2xl border border-line bg-surface">
            <Shimmer className="aspect-[9/16] max-h-64 w-full rounded-none" />
            <div className="space-y-2 p-3">
              <Shimmer className="h-3.5 w-full" />
              <Shimmer className="h-3.5 w-2/3" />
              <Shimmer className="h-3 w-1/2" />
            </div>
          </div>
        ))}
      </div>
    </Loading>
  )
}

/** Draft page: phone column on the left, stepper and cards on the right. */
export function DraftDetailSkeleton({ className = '' }: { className?: string }) {
  return (
    <Loading label="Loading draft" className={`space-y-5 ${className}`}>
      <div className="flex items-center gap-3">
        <Shimmer className="h-9 w-9" />
        <div className="space-y-2">
          <Shimmer className="h-6 w-40" />
          <Shimmer className="h-3 w-56" />
        </div>
      </div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,380px)_1fr]">
        <Shimmer className="mx-auto aspect-[9/19] w-full max-w-[300px] rounded-[2.6rem]" />
        <div className="space-y-4">
          <div className="space-y-3 rounded-2xl border border-line bg-surface p-5">
            <Shimmer className="h-5 w-24 rounded-full" />
            <Shimmer className="h-7 w-2/3" />
            <div className="flex items-center gap-2 pt-2">
              {Array.from({ length: 6 }, (_, i) => (
                <Shimmer key={i} className="h-8 w-8 shrink-0 rounded-full" />
              ))}
            </div>
          </div>
          {[0, 1].map((i) => (
            <div key={i} className="space-y-2.5 rounded-2xl border border-line bg-surface p-5">
              <Shimmer className="h-5 w-44" />
              <Shimmer className="h-3.5 w-full" />
              <Shimmer className="h-3.5 w-5/6" />
              <Shimmer className="h-3.5 w-3/5" />
            </div>
          ))}
        </div>
      </div>
    </Loading>
  )
}

/** Calendar: day heading plus a few rows. */
export function ListSkeleton({ rows = 3, className = '' }: { rows?: number; className?: string }) {
  return (
    <Loading label="Loading" className={`space-y-2 ${className}`}>
      <Shimmer className="h-4 w-40" />
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4 rounded-2xl border border-line bg-surface p-3">
          <Shimmer className="h-4 w-14" />
          <Shimmer className="h-16 w-9 rounded-md" />
          <div className="flex-1 space-y-2">
            <Shimmer className="h-3.5 w-3/4" />
            <Shimmer className="h-4 w-20 rounded-full" />
          </div>
        </div>
      ))}
    </Loading>
  )
}
