import { describe, expect, it } from 'vitest'
import type { Summary } from './api'
import { pickVoice, speechSegments, startIndex } from './speech'

const summary: Summary = {
  tldr: '  The gist.  ',
  sections: [
    { title: 'Intro', start: 0, end: 60, points: [{ t: 0, text: 'First point.' }, { t: 30, text: ' ' }] },
    { title: 'Middle', start: 60, end: 120, points: [{ t: 60, text: 'Second point.' }] },
  ],
  usage: null,
  method: 'ai',
}

describe('speechSegments', () => {
  it('reads the TL;DR, then each section title and its points, skipping empty text', () => {
    expect(speechSegments(summary)).toEqual([
      { id: 'tldr', text: 'The gist.' },
      { id: 's0', text: 'Intro.' },
      { id: 's0p0', text: 'First point.' },
      { id: 's1', text: 'Middle.' },
      { id: 's1p0', text: 'Second point.' },
    ])
  })

  it("doesn't add a full stop after a title that already ends in punctuation", () => {
    const s = { ...summary, sections: [{ ...summary.sections[0], title: 'Why it matters?', points: [] }] }
    expect(speechSegments(s)[1]).toEqual({ id: 's0', text: 'Why it matters?' })
  })
})

const voice = (lang: string, name: string, extra: Partial<SpeechSynthesisVoice> = {}) =>
  ({ lang, name, default: false, localService: true, voiceURI: name, ...extra }) as SpeechSynthesisVoice

describe('pickVoice', () => {
  const voices = [
    voice('en-GB', 'Daniel'),
    voice('en-US', 'Samantha'),
    voice('en-US', 'Google US English', { localService: false }),
    voice('hi-IN', 'Lekha'),
    voice('es_ES', 'Monica'),
  ]

  it('matches the base language', () => expect(pickVoice(voices, 'hi')?.name).toBe('Lekha'))
  it('accepts underscore-style tags', () => expect(pickVoice(voices, 'es')?.name).toBe('Monica'))
  it('prefers the default voice for that language', () =>
    expect(pickVoice([...voices, voice('en-AU', 'Karen', { default: true })], 'en')?.name).toBe('Karen'))
  it('prefers US English when no default', () => expect(pickVoice(voices, 'en')?.name).toBe('Samantha'))
  it('returns null when no voice speaks the language', () => expect(pickVoice(voices, 'ar')).toBeNull())
  it('works with full tags as input', () => expect(pickVoice(voices, 'en-GB')?.name).toBe('Daniel'))
})

describe('startIndex', () => {
  const segs = speechSegments(summary)
  it('starts at the selected segment', () => expect(startIndex(segs, 's1p0')).toBe(4))
  it('starts at the top with no selection or an unknown one', () => {
    expect(startIndex(segs, null)).toBe(0)
    expect(startIndex(segs, 'nope')).toBe(0)
  })
})
