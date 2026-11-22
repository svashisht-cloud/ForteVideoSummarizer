import { describe, expect, it } from 'vitest'
import { costText, formatTs, formatUsd, maskKey, modelLabel, sourceLabel, stageText, youtubeLink } from './format'

describe('formatTs', () => {
  it.each([
    [0, '0:00'],
    [5.9, '0:05'],
    [65, '1:05'],
    [599, '9:59'],
    [3599, '59:59'],
    [3600, '1:00:00'],
    [3725, '1:02:05'],
  ])('%s -> %s', (s, out) => expect(formatTs(s)).toBe(out))

  it('clamps negatives to 0:00', () => expect(formatTs(-3)).toBe('0:00'))
})

describe('youtubeLink', () => {
  it('floors seconds', () =>
    expect(youtubeLink('dQw4w9WgXcQ', 61.8)).toBe('https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=61s'))
})

describe('stageText', () => {
  it('names each stage', () => {
    expect(stageText('fetching_captions', null)).toBe('Fetching captions…')
    expect(stageText('downloading_audio', null)).toBe('Downloading audio…')
    expect(stageText('transcribing', null)).toBe('Transcribing audio…')
    expect(stageText('merging', { done: 0, total: 1 })).toBe('Merging…')
    expect(stageText(null, null)).toBe('Starting…')
  })

  it('shows the part being summarized', () => {
    expect(stageText('summarizing', { done: 2, total: 8 })).toBe('Summarizing part 3 of 8…')
    expect(stageText('summarizing', { done: 0, total: 8 })).toBe('Summarizing part 1 of 8…')
    expect(stageText('summarizing', { done: 8, total: 8 })).toBe('Summarizing part 8 of 8…')
  })

  it('plain text for a single part or no progress', () => {
    expect(stageText('summarizing', { done: 0, total: 1 })).toBe('Summarizing…')
    expect(stageText('summarizing', null)).toBe('Summarizing…')
  })
})

describe('sourceLabel', () => {
  it.each([
    ['captions', 'Captions'],
    ['stt-local', 'Speech-to-text (local)'],
    ['stt-openai', 'Speech-to-text (OpenAI)'],
    ['other', 'other'],
  ])('%s -> %s', (s, out) => expect(sourceLabel(s)).toBe(out))
})

describe('formatUsd', () => {
  it.each([
    [0, '$0.00'],
    [0.00003, '<$0.0001'],
    [0.003125, '$0.0031'],
    [0.0123, '$0.012'],
    [0.456, '$0.46'],
    [2.5, '$2.50'],
  ])('%s -> %s', (n, out) => expect(formatUsd(n)).toBe(out))
})

describe('costText', () => {
  const usage = {
    model: 'gpt-6.1-terra',
    calls: 1,
    input_tokens: 2410,
    cached_input_tokens: 1200,
    output_tokens: 512,
    cost_usd: 0.003125,
  }

  it('fresh summary', () =>
    expect(costText(usage, false)).toBe(
      'Estimated LLM cost: $0.0031 · 2,410 input tokens (1,200 cached) · 512 output tokens · 1 call · gpt-6.1-terra',
    ))

  it('multiple calls, nothing cached', () =>
    expect(costText({ ...usage, calls: 4, cached_input_tokens: 0 }, false)).toBe(
      'Estimated LLM cost: $0.0031 · 2,410 input tokens · 512 output tokens · 4 calls · gpt-6.1-terra',
    ))

  it('cached summary shows the original cost', () =>
    expect(costText(usage, true)).toBe(
      'From cache, no new LLM cost. Originally: $0.0031 · 2,410 input tokens (1,200 cached) · 512 output tokens · 1 call · gpt-6.1-terra',
    ))

  it('cached summary from before usage was tracked', () =>
    expect(costText(null, true)).toBe("From cache, no new LLM cost. The original cost wasn't recorded."))

  it('unknown price', () =>
    expect(costText({ ...usage, cost_usd: null }, false)).toBe(
      'Estimated LLM cost: unknown (no price for gpt-6.1-terra) · 2,410 input tokens (1,200 cached) · 512 output tokens · 1 call · gpt-6.1-terra',
    ))
})

describe('modelLabel', () => {
  const terra = { id: 'gpt-6.1-terra', label: 'GPT-6.1 Terra', input: 1, cached_input: 0.05, output: 5, cached_is_estimate: false, provider: 'openai' as const }
  it('shows input and output price per 1M tokens', () =>
    expect(modelLabel(terra)).toBe('GPT-6.1 Terra · $1 in / $5 out per 1M tokens'))
  it('keeps cents for sub-dollar prices', () =>
    expect(modelLabel({ ...terra, label: 'GPT-6 Luna', input: 0.1, output: 0.5 })).toBe(
      'GPT-6 Luna · $0.10 in / $0.50 out per 1M tokens',
    ))
})

describe('maskKey', () => {
  it('shows only the prefix and last 4 characters', () => expect(maskKey('sk-proj-abcdefghijklmnopwxyz')).toBe('sk-…wxyz'))
  it('hides short keys entirely', () => expect(maskKey('abc')).toBe('…'))
})

describe('costText for free summaries', () => {
  it('says no AI was used, cached or not', () => {
    expect(costText(null, false, 'extractive')).toBe('Free: no AI used. Key moments are quoted from the captions.')
    expect(costText(null, true, 'extractive')).toBe('Free: no AI used. Key moments are quoted from the captions.')
  })
  it('defaults to the AI wording', () => expect(costText(null, true)).toBe("From cache, no new LLM cost. The original cost wasn't recorded."))
})
