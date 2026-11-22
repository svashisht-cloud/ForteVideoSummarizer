import type { Job } from '../api'
import { stageText } from '../format'

export function Progress({ job }: { job: Job | null }) {
  return (
    <div role="status" className="flex items-center gap-3 text-muted">
      <span className="size-4 animate-spin rounded-full border-2 border-border border-t-accent" />
      {stageText(job?.stage ?? null, job?.progress ?? null)}
    </div>
  )
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-danger-border bg-danger-bg p-4 text-danger-fg">
      <p className="break-words">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 rounded-md border border-danger-border px-3 py-1 text-sm font-medium text-danger hover:bg-danger-bg"
      >
        Try again
      </button>
    </div>
  )
}
