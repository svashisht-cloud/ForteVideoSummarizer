import { useEffect, useMemo, useState } from 'react'
import type { JobResult, TtsCatalog } from '../api'
import { costText, formatTs } from '../format'
import { usePlayer } from '../playerContext'
import { pointAtTime, summaryToMarkdown, summaryToText, TEXT_SIZES } from '../reader'
import { speechSegments } from '../speech'
import { loadNumber, saveNumber } from '../storage'
import { ReadAloud } from './ReadAloud'
import { ReaderToolbar, type View } from './ReaderToolbar'
import { Timestamp } from './Timestamp'

interface Props {
  result: JobResult
  lang: string
  /** Natural read-aloud voices from the server (null: device voice only). */
  ttsCatalog: TtsCatalog | null
  collapsed: Set<number>
  onCollapse: (sections: number[], collapse: boolean) => void
  /** Reports the section scrolled into view (for the outline). */
  onSectionInView: (i: number) => void
  /** Free results: switch to AI mode to get a written summary. */
  onUpgrade: () => void
}

const DEFAULT_SIZE = 2

export function ReaderPane({ result, lang, ttsCatalog, collapsed, onCollapse, onSectionInView, onUpgrade }: Props) {
  const { video_id: videoId, summary, transcript } = result
  const { time, pause } = usePlayer()
  const [view, setView] = useState<View>('summary')
  const [reading, setReading] = useState<string | null>(null)
  const [sizeIndex, setSizeIndex] = useState(() => {
    const saved = loadNumber('text-size')
    return saved !== null && saved >= 0 && saved < TEXT_SIZES.length ? saved : DEFAULT_SIZE
  })
  const segments = useMemo(() => speechSegments(summary), [summary])
  const playing = time === null ? null : pointAtTime(summary, time)
  const free = summary.method === 'extractive'
  const allCollapsed = summary.sections.length > 0 && collapsed.size === summary.sections.length

  function changeSize(i: number) {
    const next = Math.max(0, Math.min(TEXT_SIZES.length - 1, i))
    setSizeIndex(next)
    saveNumber('text-size', next)
  }

  async function copy(format: 'markdown' | 'text') {
    await navigator.clipboard.writeText(format === 'markdown' ? summaryToMarkdown(summary, videoId) : summaryToText(summary))
  }

  // Read-aloud: open the section being read and keep it on screen.
  useEffect(() => {
    if (!reading) return
    const m = /^s(\d+)/.exec(reading)
    if (m && collapsed.has(Number(m[1]))) onCollapse([Number(m[1])], false)
    document.getElementById(`read-${reading}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [reading, collapsed, onCollapse])

  // Scroll-spy: the topmost section in the upper part of the reading pane.
  useEffect(() => {
    if (view !== 'summary') return
    const visible = new Set<number>()
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const i = Number((e.target as HTMLElement).dataset.section)
          if (e.isIntersecting) visible.add(i)
          else visible.delete(i)
        }
        if (visible.size) onSectionInView(Math.min(...visible))
      },
      { rootMargin: '-15% 0px -65% 0px' },
    )
    document.querySelectorAll('[data-section]').forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [view, summary, onSectionInView])

  const wash = (on: boolean, strong = false) =>
    on ? (strong ? 'bg-accent/15' : 'bg-accent/[0.07]') : 'bg-transparent'

  return (
    <div>
      <div className="sticky top-0 z-10 border-b border-border bg-background/90 px-4 py-2 backdrop-blur-md sm:px-8">
        <ReaderToolbar
          view={view}
          onView={setView}
          listen={<ReadAloud segments={segments} lang={lang} catalog={ttsCatalog} onActive={setReading} onStart={pause} />}
          sizeIndex={sizeIndex}
          onSize={changeSize}
          allCollapsed={allCollapsed}
          onCollapseAll={(c) => onCollapse(summary.sections.map((_, i) => i), c)}
          onCopy={copy}
        />
      </div>

      <article className="mx-auto max-w-[68ch] px-5 pt-10 pb-24 sm:px-8" style={{ fontSize: TEXT_SIZES[sizeIndex] }}>
        {view === 'summary' ? (
          <>
            {free && (
              <div className="mb-8 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border bg-surface px-4 py-3 font-sans text-sm">
                <p className="flex-1 text-muted">
                  <span className="font-medium text-foreground">Free summary</span> · key moments picked from the
                  captions without AI, in the video’s own words.
                </p>
                <button
                  type="button"
                  onClick={onUpgrade}
                  className="font-medium whitespace-nowrap text-accent hover:text-accent-hover"
                >
                  Get AI summary →
                </button>
              </div>
            )}
            <blockquote
              id="read-tldr"
              className={`-mx-3 rounded-r-md border-l-2 border-accent px-3 py-1 font-reading text-[1.08em] leading-[1.65] transition-colors ${wash(reading === 'tldr', true)}`}
            >
              <p className="mb-1 font-sans text-[0.7em] font-semibold tracking-[0.12em] text-accent uppercase">
                {free ? 'Most representative moments' : 'In short'}
              </p>
              <p dir="auto">{summary.tldr}</p>
            </blockquote>

            {summary.sections.map((s, i) => {
              const open = !collapsed.has(i)
              return (
                <section key={i} id={`sec-${i}`} data-section={i} className="mt-10 scroll-mt-20">
                  <div className="group flex items-baseline gap-3">
                    <button
                      type="button"
                      onClick={() => onCollapse([i], open)}
                      aria-expanded={open}
                      className={`flex flex-1 items-baseline gap-2 rounded-md text-left transition-colors sm:-ml-7 ${wash(reading === `s${i}`, true)}`}
                    >
                      <Chevron open={open} />
                      <h2 id={`read-s${i}`} dir="auto" className="font-sans text-[1.15em] leading-snug font-semibold tracking-tight">
                        {s.title}
                      </h2>
                      {!open && <span className="font-sans text-[0.75em] text-dim">{s.points.length} points</span>}
                    </button>
                    <Timestamp videoId={videoId} seconds={s.start} label={`${formatTs(s.start)}–${formatTs(s.end)}`} />
                  </div>
                  {open && (
                    <ul className="mt-3 space-y-1.5">
                      {s.points.map((p, j) => {
                        const isReading = reading === `s${i}p${j}`
                        const isPlaying = playing?.section === i && playing.point === j
                        return (
                          <li
                            key={j}
                            id={`read-s${i}p${j}`}
                            className={`relative -mx-3 grid grid-cols-[3.6em_1fr] gap-x-2 rounded-md px-3 py-1.5 transition-colors ${wash(isReading || isPlaying, isReading)}`}
                          >
                            {isPlaying && (
                              <span className="absolute top-1/2 -left-1 size-1.5 -translate-y-1/2 rounded-full bg-accent" aria-label="Now playing" />
                            )}
                            <Timestamp videoId={videoId} seconds={p.t} className="pt-[0.3em]" />
                            <span dir="auto" className="font-reading leading-[1.7]">
                              {p.text}
                            </span>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </section>
              )
            })}

            <p className="mt-14 border-t border-border pt-4 font-sans text-xs text-dim">
              {costText(summary.usage, result.summary_cached, summary.method)}
            </p>
          </>
        ) : (
          <div className="space-y-4">
            <p className="font-sans text-xs tracking-wide text-dim uppercase">Transcript · original language: {result.language}</p>
            {transcript.map((b, i) => (
              <p key={i} className="grid grid-cols-[3.6em_1fr] gap-x-2">
                <Timestamp videoId={videoId} seconds={b.start} className="pt-[0.3em]" />
                <span dir="auto" className="font-reading leading-[1.7]">
                  {b.text}
                </span>
              </p>
            ))}
          </div>
        )}
      </article>
    </div>
  )
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={`w-5 shrink-0 self-center text-dim transition-transform ${open ? 'rotate-90' : ''}`}
    >
      <path d="m9 6 6 6-6 6" />
    </svg>
  )
}
