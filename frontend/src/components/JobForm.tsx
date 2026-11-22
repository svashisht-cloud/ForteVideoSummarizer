import { useState, type FormEvent } from 'react'
import type { ModelsResponse } from '../api'
import { modelPrice } from '../format'
import { LANGUAGES } from '../languages'
import { loadApiKey, loadModel, saveApiKey, saveModel } from '../storage'
import { ApiKeyField } from './ApiKeyField'

const FIELD =
  'w-full rounded-lg border border-border bg-surface px-3 py-2 text-[15px] text-foreground outline-none placeholder:text-dim focus:border-accent focus:ring-2 focus:ring-accent/20'
const LABEL = 'mb-1.5 block text-xs font-medium tracking-wide text-muted uppercase'

interface Props {
  running: boolean
  models: ModelsResponse | null
  onSubmit: (url: string, lang: string, model: string | null, apiKey: string | null) => void
}

/** The options form in the sidebar. Stays mounted (hidden) after a run so its values persist. */
export function JobForm({ running, models, onSubmit }: Props) {
  const [url, setUrl] = useState('')
  const [lang, setLang] = useState('en')
  const [pickedModel, setPickedModel] = useState<string | null>(loadModel)
  const [{ key, remember }, setKey] = useState(loadApiKey)

  // A remembered model the server no longer offers falls back to the server default.
  const offered = models?.models ?? []
  const model =
    pickedModel && offered.some((m) => m.id === pickedModel) ? pickedModel : (models?.default ?? offered[0]?.id ?? null)
  const selected = offered.find((m) => m.id === model)
  const keyRequired = models?.require_user_key ?? false
  const canSubmit = !running && url.trim() !== '' && (!keyRequired || key.trim() !== '')

  function changeModel(id: string) {
    setPickedModel(id)
    saveModel(id)
  }

  function changeKey(newKey: string, newRemember: boolean) {
    setKey({ key: newKey, remember: newRemember })
    saveApiKey(newKey, newRemember)
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (canSubmit) onSubmit(url.trim(), lang, model, key.trim() || null)
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <label className="block">
        <span className={LABEL}>YouTube link</span>
        <input
          type="text"
          inputMode="url"
          autoFocus
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://youtube.com/watch?v=…"
          className={FIELD}
        />
      </label>

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

      <ApiKeyField apiKey={key} remember={remember} required={keyRequired} onChange={changeKey} />

      <button
        type="submit"
        disabled={!canSubmit}
        className="w-full rounded-lg bg-accent px-4 py-2.5 font-medium text-accent-foreground transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
      >
        {running ? 'Summarizing…' : 'Summarize'}
      </button>
    </form>
  )
}
