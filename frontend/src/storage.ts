// Browser storage helpers. Every access is wrapped: storage can be unavailable
// (private windows, blocked site data) and the app must still work without it.

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

const LEGACY_KEY = 'openai-key' // before per-provider keys
const keyName = (provider: string) => `key.${provider}`

/** Move the old single OpenAI key to the per-provider slot (same storage). */
function migrateLegacyKey(): void {
  for (const store of [local, session]) {
    const old = get(store, LEGACY_KEY)
    if (old) {
      if (!get(store, keyName('openai'))) set(store, keyName('openai'), old)
      set(store, LEGACY_KEY, null)
    }
  }
}

/** The user's saved key for a provider. `remember`: kept on this device (the
 * default) rather than only until the tab closes. */
export function loadKey(provider: string): { key: string; remember: boolean } {
  migrateLegacyKey()
  const remembered = get(local, keyName(provider))
  if (remembered) return { key: remembered, remember: true }
  const sessionOnly = get(session, keyName(provider))
  return sessionOnly ? { key: sessionOnly, remember: false } : { key: '', remember: true }
}

export function saveKey(provider: string, key: string, remember: boolean): void {
  const value = key.trim() || null
  set(remember ? local : session, keyName(provider), value)
  set(remember ? session : local, keyName(provider), null)
}

export function forgetKey(provider: string): void {
  set(local, keyName(provider), null)
  set(session, keyName(provider), null)
}

/** Has the visitor been through the welcome screen? */
export function loadOnboarded(): boolean {
  return get(local, 'onboarded') === '1'
}

export function saveOnboarded(): void {
  set(local, 'onboarded', '1')
}

export function loadProvider(): 'openai' | 'anthropic' {
  return get(local, 'provider') === 'anthropic' ? 'anthropic' : 'openai'
}

export function saveProvider(provider: 'openai' | 'anthropic'): void {
  set(local, 'provider', provider)
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
