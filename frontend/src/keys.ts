import type { ModelOption, ModelsResponse, Provider } from './api'

export const PROVIDER_LABELS: Record<Provider, string> = { openai: 'OpenAI', anthropic: 'Claude' }

/** Where people create a key for each provider. */
export const KEY_LINKS: Record<Provider, string> = {
  openai: 'https://platform.openai.com/api-keys',
  anthropic: 'https://console.anthropic.com/settings/keys',
}

export const KEY_PLACEHOLDERS: Record<Provider, string> = { openai: 'sk-…', anthropic: 'sk-ant-…' }

/** Must the user give their own key to use this provider? */
export function needsKey(provider: Provider, models: ModelsResponse | null, hasSavedKey: boolean): boolean {
  if (hasSavedKey) return false
  if (!models) return true
  return models.require_user_key || !models.server_keys?.[provider]
}

export function providerOf(models: ModelsResponse | null, modelId: string): Provider {
  const m = models?.models.find((x) => x.id === modelId)
  if (m) return m.provider
  return modelId.startsWith('claude-') ? 'anthropic' : 'openai'
}

export function modelsFor(models: ModelsResponse | null, provider: Provider): ModelOption[] {
  return (models?.models ?? []).filter((m) => m.provider === provider)
}

export function defaultModelFor(models: ModelsResponse | null, provider: Provider): string | null {
  const offered = modelsFor(models, provider)
  const preferred = models?.defaults?.[provider]
  if (preferred && offered.some((m) => m.id === preferred)) return preferred
  return offered[0]?.id ?? null
}
