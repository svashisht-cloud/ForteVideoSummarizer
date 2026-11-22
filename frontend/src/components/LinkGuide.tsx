import type { ReactNode } from 'react'

const EXAMPLES: [string, string, string][] = [
  ['How to never procrastinate', '3:32 · English', 'https://www.youtube.com/watch?v=wUrtcsDTDek'],
  ['Las ecuaciones de Maxwell en 5 minutos', '5:03 · Spanish', 'https://www.youtube.com/watch?v=kx20kG6m-JA'],
]

/** Right pane before the first summary: how to get a YouTube link, plus examples. */
export function LinkGuide({ onExample }: { onExample: (url: string) => void }) {
  return (
    <div className="mx-auto max-w-[62ch] px-5 py-12 sm:px-8 lg:py-20">
      <h1 className="font-reading text-3xl leading-tight font-semibold tracking-tight">Add a YouTube link</h1>
      <p className="mt-2 text-muted">Copy the link of any YouTube video and paste it on the left.</p>

      <ol className="mt-8 space-y-4">
        <Step n={1} title="Open the video on YouTube" art={<BrowserArt />}>
          Any video works: regular videos, Shorts and live recordings.
        </Step>
        <Step n={2} title="Copy its link" art={<ShareArt />}>
          Click <b className="font-semibold text-foreground">Share</b> under the video, then{' '}
          <b className="font-semibold text-foreground">Copy</b>. Or copy the address bar. On a phone: Share → Copy link.
        </Step>
        <Step n={3} title="Paste it into the box on the left" art={<PasteArt />}>
          Then press the button under it. The summary appears right here.
        </Step>
      </ol>

      <div className="mt-10">
        <p className="text-xs font-medium tracking-wide text-muted uppercase">Or try an example</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map(([title, meta, url]) => (
            <button
              key={url}
              type="button"
              onClick={() => onExample(url)}
              className="rounded-full border border-border bg-surface px-3.5 py-1.5 text-left text-sm hover:border-accent hover:text-accent"
            >
              {title} <span className="text-dim">· {meta}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function Step({ n, title, art, children }: { n: number; title: string; art: ReactNode; children: ReactNode }) {
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-5 rounded-xl border border-border bg-surface p-4 sm:p-5">
      <div className="min-w-0">
        <p className="flex items-center gap-2.5 font-medium">
          <span className="grid size-6 shrink-0 place-items-center rounded-full bg-accent text-xs font-semibold text-accent-foreground">
            {n}
          </span>
          {title}
        </p>
        <p className="mt-1.5 pl-8.5 text-sm leading-relaxed text-muted">{children}</p>
      </div>
      <div className="hidden w-36 text-dim sm:block" aria-hidden>
        {art}
      </div>
    </li>
  )
}

// Small, schematic illustrations in the theme's colors (currentColor = dim text, accent highlights).
const box = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.5 } as const

const BrowserArt = () => (
  <svg viewBox="0 0 144 84" className="w-full">
    <rect x="2" y="2" width="140" height="80" rx="8" {...box} />
    <line x1="2" y1="18" x2="142" y2="18" {...box} />
    <rect x="22" y="7" width="100" height="7" rx="3.5" className="fill-accent/20 stroke-accent" strokeWidth="1.2" />
    <rect x="30" y="28" width="84" height="44" rx="6" className="fill-foreground/5" stroke="currentColor" strokeWidth="1.2" />
    <path d="M67 42v16l13-8Z" className="fill-accent" />
  </svg>
)

const ShareArt = () => (
  <svg viewBox="0 0 144 84" className="w-full">
    <rect x="2" y="22" width="74" height="26" rx="13" {...box} />
    <path d="M14 35l7-6v4h6v4h-6v4Z" className="fill-current" />
    <text x="34" y="39" fontSize="10" className="fill-current" fontFamily="Inter, sans-serif">
      Share
    </text>
    <path d="M80 35h9" {...box} strokeDasharray="3 3" />
    <rect x="92" y="22" width="48" height="26" rx="13" className="fill-accent" />
    <text x="104" y="39" fontSize="10" className="fill-accent-foreground" fontFamily="Inter, sans-serif" fontWeight="600">
      Copy
    </text>
  </svg>
)

const PasteArt = () => (
  <svg viewBox="0 0 144 84" className="w-full">
    <path d="M140 42H62" className="stroke-accent" strokeWidth="2" fill="none" />
    <path d="M70 34l-9 8 9 8" className="stroke-accent" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    <rect x="2" y="28" width="54" height="28" rx="6" className="stroke-accent fill-accent/10" strokeWidth="1.5" />
    <text x="9" y="46" fontSize="9" className="fill-current" fontFamily="JetBrains Mono, monospace">
      youtu.be/…
    </text>
  </svg>
)
