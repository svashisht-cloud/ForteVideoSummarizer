import { useState } from 'react'
import { maskKey } from '../format'

interface Props {
  apiKey: string
  remember: boolean
  required: boolean
  onChange: (key: string, remember: boolean) => void
}

/** Optional (or, when the server requires it, mandatory) user-supplied OpenAI key. */
export function ApiKeyField({ apiKey, remember, required, onChange }: Props) {
  const hasKey = apiKey.trim() !== ''
  // Open at first if a key is needed or saved; afterwards the user opens and closes it.
  const [open, setOpen] = useState(required || hasKey)
  return (
    <details
      open={open || required}
      onToggle={(e) => setOpen(e.currentTarget.open)}
      className="group rounded-lg text-sm"
    >
      <summary className="cursor-pointer text-muted select-none hover:text-foreground">
        {hasKey ? (
          <>
            Using your OpenAI key <span className="font-mono">{maskKey(apiKey)}</span>
          </>
        ) : required ? (
          'Your OpenAI API key (required)'
        ) : (
          'Use your own OpenAI API key (optional)'
        )}
      </summary>
      <div className="mt-2 space-y-2 rounded-lg border border-border bg-surface p-3">
        <div className="flex gap-2">
          <label className="min-w-0 flex-1">
            <span className="sr-only">OpenAI API key</span>
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={apiKey}
              onChange={(e) => onChange(e.target.value, remember)}
              placeholder="sk-…"
              className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 font-mono text-foreground outline-none placeholder:text-dim focus:border-accent focus:ring-2 focus:ring-accent/25"
            />
          </label>
          {hasKey && (
            <button
              type="button"
              onClick={() => onChange('', remember)}
              className="rounded-md border border-border px-3 text-foreground hover:border-accent hover:text-accent"
            >
              Clear
            </button>
          )}
        </div>
        <label className="flex items-center gap-2 text-muted">
          <input type="checkbox" checked={remember} onChange={(e) => onChange(apiKey, e.target.checked)} />
          Remember on this device
        </label>
        <p className="text-xs text-muted">
          {required ? '' : 'Leave empty to use the server’s key. '}
          Your key is sent only to this app’s server, used for this request, and never stored there. In your browser it’s
          kept until you close the tab, or on this device if you tick “Remember”, where other scripts on this page could
          read it.
        </p>
      </div>
    </details>
  )
}
