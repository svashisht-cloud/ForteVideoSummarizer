import { useEffect, useRef, useState, type ReactNode } from 'react'
import { TEXT_SIZES } from '../reader'

export type View = 'summary' | 'transcript'

interface Props {
  view: View
  onView: (v: View) => void
  /** The read-aloud player (only shown on the summary view). */
  listen: ReactNode
  sizeIndex: number
  onSize: (i: number) => void
  allCollapsed: boolean
  onCollapseAll: (collapse: boolean) => void
  onCopy: (format: 'markdown' | 'text') => Promise<void>
}

const ghost =
  'inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-sm text-muted hover:bg-foreground/5 hover:text-foreground disabled:opacity-40 disabled:hover:bg-transparent'

export function ReaderToolbar(p: Props) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <div className="mr-2 inline-flex rounded-lg bg-foreground/5 p-0.5 text-sm" role="tablist">
        {(['summary', 'transcript'] as const).map((v) => (
          <button
            key={v}
            type="button"
            role="tab"
            aria-selected={p.view === v}
            onClick={() => p.onView(v)}
            className={`rounded-md px-3 py-1 font-medium capitalize transition-colors ${
              p.view === v ? 'bg-background text-foreground shadow-sm' : 'text-muted hover:text-foreground'
            }`}
          >
            {v}
          </button>
        ))}
      </div>
      {p.view === 'summary' && p.listen}
      <div className="ml-auto flex items-center gap-0.5">
        <button
          type="button"
          className={ghost}
          onClick={() => p.onSize(p.sizeIndex - 1)}
          disabled={p.sizeIndex <= 0}
          aria-label="Smaller text"
          title="Smaller text"
        >
          <span className="text-xs font-semibold">A−</span>
        </button>
        <button
          type="button"
          className={ghost}
          onClick={() => p.onSize(p.sizeIndex + 1)}
          disabled={p.sizeIndex >= TEXT_SIZES.length - 1}
          aria-label="Larger text"
          title="Larger text"
        >
          <span className="text-base font-semibold">A+</span>
        </button>
        {p.view === 'summary' && (
          <>
            <button
              type="button"
              className={ghost}
              onClick={() => p.onCollapseAll(!p.allCollapsed)}
              title={p.allCollapsed ? 'Expand all sections' : 'Collapse all sections'}
            >
              <FoldIcon open={p.allCollapsed} />
              <span className="hidden sm:inline">{p.allCollapsed ? 'Expand' : 'Collapse'}</span>
            </button>
            <CopyMenu onCopy={p.onCopy} />
          </>
        )}
      </div>
    </div>
  )
}

function CopyMenu({ onCopy }: { onCopy: Props['onCopy'] }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  async function copy(format: 'markdown' | 'text') {
    setOpen(false)
    try {
      await onCopy(format)
      setCopied('Copied')
    } catch {
      setCopied('Copy failed')
    }
    window.setTimeout(() => setCopied(null), 1600)
  }

  const item = 'block w-full rounded-md px-3 py-1.5 text-left text-sm hover:bg-foreground/5'
  return (
    <div className="relative" ref={ref}>
      <button type="button" className={ghost} onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}>
        <CopyIcon />
        <span className="hidden sm:inline">{copied ?? 'Copy'}</span>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-1 w-44 rounded-lg border border-border bg-surface p-1 shadow-lg"
        >
          <button type="button" role="menuitem" className={item} onClick={() => copy('markdown')}>
            As Markdown
          </button>
          <button type="button" role="menuitem" className={item} onClick={() => copy('text')}>
            As plain text
          </button>
        </div>
      )}
    </div>
  )
}

const svg = { width: 15, height: 15, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true } as const

const CopyIcon = () => (
  <svg {...svg}>
    <rect x="9" y="9" width="12" height="12" rx="2" />
    <path d="M5 15V5a2 2 0 0 1 2-2h10" />
  </svg>
)

const FoldIcon = ({ open }: { open: boolean }) => (
  <svg {...svg}>{open ? <path d="m7 15 5 5 5-5M7 9l5-5 5 5" /> : <path d="m7 20 5-5 5 5M7 4l5 5 5-5" />}</svg>
)
