import type { JobResult, Mode, ModelsResponse } from '../api'
import { formatTs, formatUsd } from '../format'
import { languageName } from '../languages'
import { Player } from '../player'
import { usePlayer } from '../playerContext'
import { sectionAtTime } from '../reader'

export function Wordmark() {
  return (
    <a href="/" aria-label="Forte video summarizer home" className="flex items-baseline gap-2 hover:opacity-80">
      <span className="font-brand text-xl font-semibold tracking-tight text-foreground">forte</span>
      <span className="text-dim select-none" aria-hidden>
        /
      </span>
      <span className="text-sm font-medium text-muted">video summarizer</span>
    </a>
  )
}

interface NowViewingProps {
  result: JobResult
  lang: string
  model: string | null
  models: ModelsResponse | null
  mode: Mode
  editing: boolean
  onEdit: () => void
  onNew: () => void
}

/** The video being read, with what produced the summary. */
export function NowViewing({ result, lang, model, models, mode, editing, onEdit, onNew }: NowViewingProps) {
  const usedModel = result.summary.usage?.model ?? model
  const modelLabel = models?.models.find((m) => m.id === usedModel)?.label ?? usedModel
  const usage = result.summary.usage
  const cost = result.summary_cached
    ? 'from cache'
    : usage?.cost_usd != null
      ? formatUsd(usage.cost_usd)
      : null
  const meta =
    mode === 'free'
      ? ['Free · no AI', languageName(result.language.split('-')[0].toLowerCase())].join(' · ')
      : [languageName(lang), modelLabel, cost].filter(Boolean).join(' · ')
  const btn = 'rounded-md px-2.5 py-1 text-sm font-medium text-muted hover:bg-foreground/5 hover:text-foreground'

  return (
    <div className="space-y-3">
      <Player videoId={result.video_id} />
      {result.title && (
        <p dir="auto" className="line-clamp-2 text-sm leading-snug font-medium">
          {result.title}
        </p>
      )}
      <p className="text-xs text-muted">{meta}</p>
      <div className="-ml-2.5 flex gap-1">
        <button type="button" className={btn} onClick={onEdit} aria-expanded={editing}>
          {editing ? 'Hide options' : 'Change options'}
        </button>
        <button type="button" className={btn} onClick={onNew}>
          + New summary
        </button>
      </div>
    </div>
  )
}

interface OutlineProps {
  result: JobResult
  active: number | null
  onJump: (i: number) => void
}

/** Section list: highlights the section in view; a dot marks the one playing. */
export function Outline({ result, active, onJump }: OutlineProps) {
  const { time } = usePlayer()
  const playing = time === null ? null : sectionAtTime(result.summary, time)
  const sections = result.summary.sections
  if (!sections.length) return null
  return (
    <nav aria-label="Outline">
      <p className="mb-2 text-xs font-medium tracking-wide text-muted uppercase">Outline</p>
      <ol className="space-y-0.5">
        {sections.map((s, i) => (
          <li key={i}>
            <button
              type="button"
              onClick={() => onJump(i)}
              aria-current={active === i ? 'true' : undefined}
              className={`relative flex w-full items-baseline gap-3 rounded-md py-1.5 pr-2 pl-3 text-left text-sm transition-colors hover:bg-foreground/5 ${
                active === i ? 'font-medium text-foreground' : 'text-muted'
              }`}
            >
              <span
                className={`absolute top-1.5 bottom-1.5 left-0 w-0.5 rounded-full ${active === i ? 'bg-accent' : 'bg-transparent'}`}
              />
              <span dir="auto" className="line-clamp-2 flex-1">
                {s.title}
              </span>
              {playing === i && <span className="size-1.5 shrink-0 self-center rounded-full bg-accent" aria-label="Playing" />}
              <span className="font-mono text-xs text-dim tabular-nums">{formatTs(s.start)}</span>
            </button>
          </li>
        ))}
      </ol>
    </nav>
  )
}
