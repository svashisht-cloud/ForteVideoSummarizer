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

/** Right-pane placeholder before the first summary. */
export function EmptyState() {
  const hints = [
    ['Jump around', 'Click any timestamp to play the video from that moment.'],
    ['Listen', 'Have the summary read aloud, with the current line highlighted.'],
    ['Take it with you', 'Copy the summary as Markdown or plain text.'],
  ]
  return (
    <div className="mx-auto max-w-[60ch] px-5 py-16 sm:px-8 lg:py-28">
      <h1 className="font-reading text-3xl leading-tight font-semibold tracking-tight sm:text-4xl">
        Summarize any YouTube video
      </h1>
      <p className="mt-3 text-lg text-muted">
        Paste a link on the left, pick a language, and get a timestamped summary you can read, listen to and explore.
      </p>
      <dl className="mt-10 space-y-4">
        {hints.map(([t, d]) => (
          <div key={t} className="border-l-2 border-border pl-4">
            <dt className="text-sm font-medium">{t}</dt>
            <dd className="text-sm text-muted">{d}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
