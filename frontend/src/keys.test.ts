import { beforeEach, describe, expect, it } from 'vitest'
import type { ModelsResponse } from './api'
import { defaultModelFor, modelsFor, needsKey, providerOf } from './keys'
import { forgetKey, loadKey, saveKey } from './storage'

const models: ModelsResponse = {
  default: 'gpt-6.1-terra',
  defaults: { openai: 'gpt-6.1-terra', anthropic: 'claude-opus-5-5' },
  server_keys: { openai: true, anthropic: false },
  require_user_key: false,
  models: [
    { id: 'gpt-6.1-terra', label: 'GPT-6.1 Terra', input: 1, cached_input: 0.05, output: 5, cached_is_estimate: false, provider: 'openai' },
    { id: 'claude-haiku-5-5', label: 'Claude Haiku 5.5', input: 0.1, cached_input: 0.01, output: 0.5, cached_is_estimate: true, provider: 'anthropic' },
    { id: 'claude-opus-5-5', label: 'Claude Opus 5.5', input: 4, cached_input: 0.2, output: 20, cached_is_estimate: false, provider: 'anthropic' },
  ],
}

describe('needsKey', () => {
  it('not when the user has a key saved', () => expect(needsKey('anthropic', models, true)).toBe(false))
  it('not when the server has a key for the provider', () => expect(needsKey('openai', models, false)).toBe(false))
  it('yes when the server has no key for the provider', () => expect(needsKey('anthropic', models, false)).toBe(true))
  it('yes when the server requires users to bring keys', () =>
    expect(needsKey('openai', { ...models, require_user_key: true }, false)).toBe(true))
  it('yes when the server settings are unknown', () => expect(needsKey('openai', null, false)).toBe(true))
})

describe('model helpers', () => {
  it('providerOf', () => {
    expect(providerOf(models, 'claude-opus-5-5')).toBe('anthropic')
    expect(providerOf(models, 'gpt-6.1-terra')).toBe('openai')
    expect(providerOf(models, 'unknown')).toBe('openai')
    expect(providerOf(null, 'claude-x')).toBe('anthropic')
  })
  it('modelsFor keeps the server order', () =>
    expect(modelsFor(models, 'anthropic').map((m) => m.id)).toEqual(['claude-haiku-5-5', 'claude-opus-5-5']))
  it('defaultModelFor uses the server default, else the first model', () => {
    expect(defaultModelFor(models, 'anthropic')).toBe('claude-opus-5-5')
    expect(defaultModelFor({ ...models, defaults: { openai: null, anthropic: null } }, 'anthropic')).toBe('claude-haiku-5-5')
    expect(defaultModelFor(null, 'openai')).toBeNull()
  })
})

class MemoryStorage implements Storage {
  private m = new Map<string, string>()
  get length() {
    return this.m.size
  }
  clear() {
    this.m.clear()
  }
  getItem(k: string) {
    return this.m.get(k) ?? null
  }
  key(i: number) {
    return [...this.m.keys()][i] ?? null
  }
  removeItem(k: string) {
    this.m.delete(k)
  }
  setItem(k: string, v: string) {
    this.m.set(k, v)
  }
}

describe('saved keys', () => {
  beforeEach(() => {
    Object.assign(globalThis, { localStorage: new MemoryStorage(), sessionStorage: new MemoryStorage() })
  })

  it('remembers on this device by default, per provider', () => {
    saveKey('anthropic', 'sk-ant-123', true)
    expect(loadKey('anthropic')).toEqual({ key: 'sk-ant-123', remember: true })
    expect(loadKey('openai')).toEqual({ key: '', remember: true })
  })

  it('session-only keys live in sessionStorage', () => {
    saveKey('openai', 'sk-1', false)
    expect(localStorage.getItem('key.openai')).toBeNull()
    expect(loadKey('openai')).toEqual({ key: 'sk-1', remember: false })
  })

  it('forget removes it everywhere', () => {
    saveKey('openai', 'sk-1', true)
    forgetKey('openai')
    expect(loadKey('openai').key).toBe('')
  })

  it('migrates the old single OpenAI key', () => {
    localStorage.setItem('openai-key', 'sk-old')
    expect(loadKey('openai')).toEqual({ key: 'sk-old', remember: true })
    expect(localStorage.getItem('openai-key')).toBeNull()
    expect(localStorage.getItem('key.openai')).toBe('sk-old')
  })
})
