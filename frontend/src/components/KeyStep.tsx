import { useState } from 'react'
import { checkKey, type Provider } from '../api'
import { KEY_LINKS, KEY_PLACEHOLDERS, PROVIDER_LABELS } from '../keys'
import { saveKey } from '../storage'

interface Props {
  provider: Provider
  /** Show the OpenAI | Claude switch (welcome screen). */
  onProviderChange?: (p: Provider) => void
  /** Called after the key was verified and saved. */
  onSaved: (provider: Provider, key: string) => void
  onCancel?: () => void
  cancelLabel?: string
  submitLabel?: string
}

/** Paste a key, verify it with the provider (a free call), save it in this browser. */
export function KeyStep({ provider, onProviderChange, onSaved, onCancel, cancelLabel = 'Cancel', submitLabel = 'Verify & save' }: Props) {
  const [key, setKey] = useState('')
  const [remember, setRemember] = useState(true)
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const name = PROVIDER_LABELS[provider]

  // Not a <form>: this sits inside the sidebar's job form, and forms can't nest.
  async function submit() {
    const k = key.trim()
    if (!k || checking) return
    setChecking(true)
    setError(null)
    try {
      const problem = await checkKey(provider, k)
      if (problem) setError(problem)
      else {
        saveKey(provider, k, remember)
        onSaved(provider, k)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Couldn’t check the key.')
    } finally {
      setChecking(false)
    }
  }

  return (
    <div role="group" aria-label={`${PROVIDER_LABELS[provider]} API key`} className="space-y-3 text-sm">
      {onProviderChange && (
        <div role="radiogroup" aria-label="AI provider" className="grid grid-cols-2 rounded-lg bg-foreground/5 p-0.5">
          {(Object.keys(PROVIDER_LABELS) as Provider[]).map((p) => (
            <button
              key={p}
              type="button"
              role="radio"
              aria-checked={provider === p}
              onClick={() => {
                onProviderChange(p)
                setError(null)
              }}
              className={`rounded-md py-1.5 font-medium transition-colors ${
                provider === p ? 'bg-background text-foreground shadow-sm' : 'text-muted hover:text-foreground'
              }`}
            >
              {PROVIDER_LABELS[p]}
            </button>
          ))}
        </div>
      )}
      <label className="block">
        <span className="mb-1.5 flex items-baseline justify-between gap-2">
          <span className="text-xs font-medium tracking-wide text-muted uppercase">{name} API key</span>
          <a href={KEY_LINKS[provider]} target="_blank" rel="noopener noreferrer" className="text-xs text-accent hover:text-accent-hover">
            Get a key ↗
          </a>
        </span>
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={key}
          onChange={(e) => {
            setKey(e.target.value)
            setError(null)
          }}
          placeholder={KEY_PLACEHOLDERS[provider]}
          aria-invalid={error ? true : undefined}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              void submit()
            }
          }}
          className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-foreground outline-none placeholder:text-dim focus:border-accent focus:ring-2 focus:ring-accent/20"
        />
      </label>
      {error && (
        <p role="alert" className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-danger-fg">
          {error}
        </p>
      )}
      <label className="flex items-center gap-2 text-muted">
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        Remember on this device
      </label>
      <p className="text-xs leading-relaxed text-dim">
        Your key stays in this browser and is sent only to this app’s server with each request; it’s never stored there.
        {remember ? '' : ' It’s forgotten when you close the tab.'}
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => void submit()}
          disabled={!key.trim() || checking}
          className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 font-medium text-accent-foreground hover:bg-accent-hover disabled:opacity-40"
        >
          {checking && <span className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
          {checking ? 'Checking…' : submitLabel}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} className="rounded-lg px-3 py-2 text-muted hover:text-foreground">
            {cancelLabel}
          </button>
        )}
      </div>
    </div>
  )
}
