import { useState, type FormEvent } from 'react'
import type { Mode, ModelsResponse, Provider } from '../api'
import { maskKey, modelPrice } from '../format'
import { defaultModelFor, modelsFor, needsKey, PROVIDER_LABELS } from '../keys'
import { LANGUAGES } from '../languages'
import { forgetKey, loadKey, loadModel, loadProvider, saveModel, saveProvider } from '../storage'
import { KeyStep } from './KeyStep'

const FIELD =
  'w-full rounded-lg border border-border bg-surface px-3 py-2 text-[15px] text-foreground outline-none placeholder:text-dim focus:border-accent focus:ring-2 focus:ring-accent/20'
const LABEL = 'mb-1.5 block text-xs font-medium tracking-wide text-muted uppercase'
const SEGMENTED = 'grid grid-cols-2 rounded-lg bg-foreground/5 p-0.5 text-sm'
const segment = (on: boolean) =>
  `rounded-md py-1.5 font-medium transition-colors ${on ? 'bg-background text-foreground shadow-sm' : 'text-muted hover:text-foreground'}`

const MODES: [Mode, string][] = [
  ['free', 'Free'],
  ['ai', 'AI summary'],
]

interface Props {
  running: boolean
  models: ModelsResponse | null
  /** Free (no AI) or AI summary; owned by App so a result can switch it. */
  mode: Mode
  onModeChange: (mode: Mode) => void
  /** The YouTube link, owned by App (the welcome screen and examples fill it). */
  url: string
  onUrlChange: (url: string) => void
  /** Briefly highlight the link field (just arrived from the welcome screen). */
  attention?: boolean
  onSubmit: (url: string, lang: string, model: string | null, apiKey: string | null, mode: Mode) => void
}

/** The options form in the sidebar. Stays mounted (hidden) after a run so its values persist. */
export function JobForm({ running, models, mode, onModeChange, url, onUrlChange, attention, onSubmit }: Props) {
  const [lang, setLang] = useState('en')
  const [provider, setProvider] = useState<Provider>(loadProvider)
  const [pickedModel, setPickedModel] = useState<string | null>(loadModel)
  // Saved keys per provider; re-read from storage when the key area changes them.
  const [keys, setKeys] = useState<Record<Provider, string>>(() => ({
    openai: loadKey('openai').key,
    anthropic: loadKey('anthropic').key,
  }))
  const [editingKey, setEditingKey] = useState(false)

  const offered = modelsFor(models, provider)
  const model = pickedModel && offered.some((m) => m.id === pickedModel) ? pickedModel : defaultModelFor(models, provider)
  const selected = offered.find((m) => m.id === model)
  const savedKey = keys[provider]
  const keyMissing = needsKey(provider, models, savedKey !== '')
  const canSubmit = !running && url.trim() !== '' && (mode === 'free' || (!keyMissing && model !== null))

  function changeProvider(p: Provider) {
    setProvider(p)
    saveProvider(p)
    setEditingKey(false)
  }

  function changeModel(id: string) {
    setPickedModel(id)
    saveModel(id)
  }

  function keySaved(p: Provider, k: string) {
    setKeys((prev) => ({ ...prev, [p]: k }))
    setEditingKey(false)
  }

  function forget() {
    forgetKey(provider)
    setKeys((prev) => ({ ...prev, [provider]: '' }))
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (canSubmit) onSubmit(url.trim(), lang, mode === 'ai' ? model : null, mode === 'ai' ? savedKey || null : null, mode)
  }

  const small = 'text-accent hover:text-accent-hover'

  return (
    <form onSubmit={submit} className="space-y-5">
      <div>
        <div role="radiogroup" aria-label="Summary type" className={SEGMENTED}>
          {MODES.map(([m, label]) => (
            <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => onModeChange(m)} className={segment(mode === m)}>
              {label}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs leading-relaxed text-muted">
          {mode === 'free'
            ? 'No AI, no cost. Key moments are quoted from the video’s captions, in its original language.'
            : 'Written by an AI model in the language you choose, using your OpenAI or Claude key.'}
        </p>
      </div>

      <label className="block" style={{ viewTransitionName: 'url-bar' }}>
        <span className={LABEL}>YouTube link</span>
        <input
          id="youtube-link"
          type="text"
          inputMode="url"
          autoFocus
          value={url}
          onChange={(e) => onUrlChange(e.target.value)}
          placeholder="https://youtube.com/watch?v=…"
          className={`${FIELD} ${attention && !url ? 'animate-attention' : ''}`}
        />
      </label>

      {mode === 'ai' && (
        <>
          <label className="block">
            <span className={LABEL}>Summary language</span>
            <select value={lang} onChange={(e) => setLang(e.target.value)} className={FIELD}>
              {LANGUAGES.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </label>

          <div>
            <span className={LABEL}>AI provider</span>
            <div role="radiogroup" aria-label="AI provider" className={SEGMENTED}>
              {(Object.keys(PROVIDER_LABELS) as Provider[]).map((p) => (
                <button key={p} type="button" role="radio" aria-checked={provider === p} onClick={() => changeProvider(p)} className={segment(provider === p)}>
                  {PROVIDER_LABELS[p]}
                </button>
              ))}
            </div>
          </div>

          {offered.length > 0 && model && (
            <label className="block">
              <span className={LABEL}>Model</span>
              <select value={model} onChange={(e) => changeModel(e.target.value)} className={FIELD}>
                {offered.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
              {selected && <span className="mt-1.5 block text-xs text-dim">{modelPrice(selected)}</span>}
            </label>
          )}

          <div className="rounded-lg border border-border bg-surface p-3 text-sm">
            {editingKey || (keyMissing && !savedKey) ? (
              <>
                {keyMissing && !editingKey && (
                  <p className="mb-3 text-muted">
                    Add your {PROVIDER_LABELS[provider]} key to use {PROVIDER_LABELS[provider]} models.
                  </p>
                )}
                <KeyStep
                  key={provider}
                  provider={provider}
                  onSaved={keySaved}
                  onCancel={editingKey ? () => setEditingKey(false) : undefined}
                />
              </>
            ) : savedKey ? (
              <p className="text-muted">
                Using your {PROVIDER_LABELS[provider]} key <span className="font-mono text-foreground">{maskKey(savedKey)}</span>
                <span className="mt-1 flex gap-3">
                  <button type="button" className={small} onClick={() => setEditingKey(true)}>
                    Change
                  </button>
                  <button type="button" className={small} onClick={forget}>
                    Forget
                  </button>
                </span>
              </p>
            ) : (
              <p className="text-muted">
                Using this server’s {PROVIDER_LABELS[provider]} key.{' '}
                <button type="button" className={small} onClick={() => setEditingKey(true)}>
                  Use my own key
                </button>
              </p>
            )}
          </div>
        </>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="w-full rounded-lg bg-accent px-4 py-2.5 font-medium text-accent-foreground transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
      >
        {running ? 'Summarizing…' : mode === 'free' ? 'Get key moments' : 'Summarize'}
      </button>
    </form>
  )
}
