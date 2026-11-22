// Browser storage helpers. Every access is wrapped: storage can be unavailable
// (private windows, blocked site data) and the app must still work without it.

const KEY_NAME = 'openai-key'
const MODEL_NAME = 'model'

function get(store: () => Storage, name: string): string | null {
  try {
    return store().getItem(name)
  } catch {
    return null
  }
}

function set(store: () => Storage, name: string, value: string | null): void {
  try {
    if (value === null) store().removeItem(name)
    else store().setItem(name, value)
  } catch {
    // Not available: the value just won't persist.
  }
}

const session = () => sessionStorage
const local = () => localStorage

/** The saved key and whether it's remembered across browser sessions. */
export function loadApiKey(): { key: string; remember: boolean } {
  const remembered = get(local, KEY_NAME)
  if (remembered) return { key: remembered, remember: true }
  return { key: get(session, KEY_NAME) ?? '', remember: false }
}

/** Session storage by default (cleared when the tab closes); local storage only if `remember`. */
export function saveApiKey(key: string, remember: boolean): void {
  const value = key.trim() || null
  set(remember ? local : session, KEY_NAME, value)
  set(remember ? session : local, KEY_NAME, null)
}

export function loadModel(): string | null {
  return get(local, MODEL_NAME)
}

export function saveModel(model: string): void {
  set(local, MODEL_NAME, model)
}

/** Free or AI mode, as last chosen. Free the first time. */
export function loadMode(): 'free' | 'ai' {
  return get(local, 'mode') === 'ai' ? 'ai' : 'free'
}

export function saveMode(mode: 'free' | 'ai'): void {
  set(local, 'mode', mode)
}

/** The read-aloud voice picked for a summary language. */
export function loadVoice(lang: string): string | null {
  return get(local, `voice.${lang}`)
}

export function saveVoice(lang: string, voice: string): void {
  set(local, `voice.${lang}`, voice)
}

export function loadNumber(name: string): number | null {
  const v = Number(get(local, name))
  return get(local, name) !== null && Number.isFinite(v) ? v : null
}

export function saveNumber(name: string, value: number): void {
  set(local, name, String(value))
}
