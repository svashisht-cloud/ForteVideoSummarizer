import { describe, expect, it } from 'vitest'
import type { TtsCatalog } from './api'
import { prefetchIndices, previewText, ttsVoiceFor } from './narrator'

const catalog: TtsCatalog = {
  en: {
    default: 'af_heart',
    voices: [
      { id: 'af_heart', label: 'Heart', gender: 'female', accent: 'US' },
      { id: 'bf_emma', label: 'Emma', gender: 'female', accent: 'UK' },
    ],
  },
  hi: { default: 'hf_alpha', voices: [{ id: 'hf_alpha', label: 'Alpha', gender: 'female', accent: null }] },
}

describe('ttsVoiceFor', () => {
  it('is null when the language has no natural voice or there is no catalog', () => {
    expect(ttsVoiceFor(catalog, 'de', null)).toBeNull()
    expect(ttsVoiceFor(null, 'en', null)).toBeNull()
  })
  it('uses the saved voice when it belongs to the language', () =>
    expect(ttsVoiceFor(catalog, 'en', 'bf_emma')).toBe('bf_emma'))
  it('falls back to the default for an unknown or foreign saved voice', () => {
    expect(ttsVoiceFor(catalog, 'en', 'hf_alpha')).toBe('af_heart')
    expect(ttsVoiceFor(catalog, 'hi', null)).toBe('hf_alpha')
  })
})

describe('prefetchIndices', () => {
  it('is the current segment plus the next n, within bounds', () => {
    expect(prefetchIndices(0, 5, 2)).toEqual([0, 1, 2])
    expect(prefetchIndices(3, 5, 2)).toEqual([3, 4])
    expect(prefetchIndices(4, 5, 2)).toEqual([4])
    expect(prefetchIndices(5, 5, 2)).toEqual([])
  })
})

describe('previewText', () => {
  it('has a sentence for every natural-voice language and English as a fallback', () => {
    for (const lang of ['en', 'es', 'fr', 'hi', 'it', 'pt', 'zh']) expect(previewText(lang).length).toBeGreaterThan(10)
    expect(previewText('xx')).toBe(previewText('en'))
  })
})
