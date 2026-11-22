import { useState, type ReactNode } from 'react'
import type { Mode, ModelsResponse, Provider } from '../api'
import { needsKey } from '../keys'
import { loadKey, loadProvider, saveProvider } from '../storage'
import { KeyStep } from './KeyStep'
import { Wordmark } from './Sidebar'

interface Props {
  models: ModelsResponse | null
  url: string
  onUrlChange: (url: string) => void
  onChoose: (mode: Mode) => void
}

/** First-visit screen: the link bar plus a clear choice between Free and AI. */
export function Welcome({ models, url, onUrlChange, onChoose }: Props) {
  const [provider, setProvider] = useState<Provider>(loadProvider)
  const [askingKey, setAskingKey] = useState(false)

  function chooseAi() {
    if (needsKey(provider, models, loadKey(provider).key !== '')) setAskingKey(true)
    else onChoose('ai')
  }

  function changeProvider(p: Provider) {
    setProvider(p)
    saveProvider(p)
  }

  return (
    <div className="welcome-glow min-h-dvh px-5 py-10 sm:py-16">
      <div className="mx-auto max-w-4xl">
        <div className="flex justify-center">
          <Wordmark />
        </div>
        <h1 className="mt-10 text-center font-reading text-3xl leading-tight font-semibold tracking-tight sm:text-5xl">
          Summarize any YouTube video
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-center text-lg text-muted">
          Read it, listen to it, and jump straight to the moments that matter.
        </p>

        <label className="mx-auto mt-8 block max-w-2xl" style={{ viewTransitionName: 'url-bar' }}>
          <span className="sr-only">YouTube link</span>
          <input
            type="text"
            inputMode="url"
            value={url}
            onChange={(e) => onUrlChange(e.target.value)}
            placeholder="Paste a YouTube link (optional, you can add it next)"
            className="w-full rounded-2xl border border-border bg-surface px-5 py-4 text-lg text-foreground shadow-sm outline-none placeholder:text-dim focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
        </label>

        <p className="mt-10 text-center text-sm font-medium tracking-wide text-muted uppercase">
          How would you like it summarized?
        </p>

        <div className="mt-4 grid gap-5 md:grid-cols-2">
          <ModeCard
            icon={<QuoteIcon />}
            title="Free"
            badge="$0 · no key needed"
            tone="neutral"
            items={[
              [true, 'Key moments quoted from the captions'],
              [true, 'Chapters, outline and read-aloud'],
              [true, 'Click any moment to play it'],
              [false, 'Stays in the video’s language, not rewritten'],
            ]}
            cta="Start free"
            onCta={() => onChoose('free')}
          />
          <ModeCard
            icon={<PenIcon />}
            title="AI summary"
            badge="Your OpenAI or Claude key · about a cent a video"
            tone="accent"
            items={[
              [true, 'A clear written TL;DR plus every point'],
              [true, 'In any of 12 languages'],
              [true, 'Works even without captions'],
              [true, 'Chapters, outline and read-aloud'],
            ]}
            cta={models ? 'Use AI' : 'Loading…'}
            ctaDisabled={!models}
            onCta={chooseAi}
          >
            {askingKey && (
              <div className="mt-5 border-t border-border pt-5 text-left">
                <p className="mb-3 text-sm text-muted">
                  Add your API key. It’s checked with a free call, then remembered on this device so you won’t need it again.
                </p>
                <KeyStep
                  key={provider}
                  provider={provider}
                  onProviderChange={changeProvider}
                  onSaved={() => onChoose('ai')}
                  onCancel={() => setAskingKey(false)}
                  cancelLabel="Back"
                  submitLabel="Verify & continue"
                />
                {!needsKey(provider, models, false) && (
                  <button
                    type="button"
                    onClick={() => onChoose('ai')}
                    className="mt-3 text-sm text-accent hover:text-accent-hover"
                  >
                    Or continue with this server’s key →
                  </button>
                )}
              </div>
            )}
          </ModeCard>
        </div>

        <p className="mt-8 text-center text-sm text-dim">You can switch between Free and AI at any time.</p>
      </div>
    </div>
  )
}

interface CardProps {
  icon: ReactNode
  title: string
  badge: string
  tone: 'neutral' | 'accent'
  items: [boolean, string][]
  cta: string
  ctaDisabled?: boolean
  onCta: () => void
  children?: ReactNode
}

function ModeCard({ icon, title, badge, tone, items, cta, ctaDisabled, onCta, children }: CardProps) {
  const accent = tone === 'accent'
  return (
    <section
      className={`group flex flex-col rounded-2xl border bg-surface p-6 shadow-sm transition duration-200 hover:-translate-y-0.5 hover:shadow-lg ${
        accent ? 'border-accent/40 hover:border-accent' : 'border-border hover:border-foreground/25'
      }`}
    >
      <div className="flex items-start gap-4">
        <span
          className={`grid size-11 shrink-0 place-items-center rounded-xl ${accent ? 'bg-accent/15 text-accent' : 'bg-foreground/5 text-foreground'}`}
        >
          {icon}
        </span>
        <div>
          <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
          <p className={`mt-1 inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${accent ? 'bg-accent/10 text-accent' : 'bg-foreground/5 text-muted'}`}>
            {badge}
          </p>
        </div>
      </div>
      <ul className="mt-5 flex-1 space-y-2 text-[15px]">
        {items.map(([yes, text]) => (
          <li key={text} className={`flex gap-2.5 ${yes ? '' : 'text-muted'}`}>
            <span aria-hidden className={`mt-0.5 shrink-0 ${yes ? (accent ? 'text-accent' : 'text-foreground') : 'text-dim'}`}>
              {yes ? '✓' : '–'}
            </span>
            <span>
              <span className="sr-only">{yes ? 'Included: ' : 'Not included: '}</span>
              {text}
            </span>
          </li>
        ))}
      </ul>
      {children || (
        <button
          type="button"
          onClick={onCta}
          disabled={ctaDisabled}
          className={`mt-6 w-full rounded-xl px-4 py-3 font-medium transition-colors disabled:opacity-50 ${
            accent
              ? 'bg-accent text-accent-foreground hover:bg-accent-hover'
              : 'border border-border bg-background text-foreground hover:border-foreground/40'
          }`}
        >
          {cta} →
        </button>
      )}
    </section>
  )
}

const svg = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true } as const

const QuoteIcon = () => (
  <svg {...svg}>
    <path d="M7 7h4v4c0 2.5-1.5 4-4 5M15 7h4v4c0 2.5-1.5 4-4 5" />
  </svg>
)

const PenIcon = () => (
  <svg {...svg}>
    <path d="m14.5 5.5 4 4M4 20l1-5L15.5 4.5a2.1 2.1 0 0 1 3 3L8 18l-4 2Z" />
    <path d="M19 15v4M17 17h4" />
  </svg>
)
