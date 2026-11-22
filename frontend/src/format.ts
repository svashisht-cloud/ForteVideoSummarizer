import type { ModelOption, Progress, Stage, Usage } from './api'

/** Seconds -> "m:ss", or "h:mm:ss" from one hour up (same as the backend's format_ts). */
export function formatTs(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = String(total % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

export function youtubeLink(videoId: string, seconds: number): string {
  return `https://www.youtube.com/watch?v=${videoId}&t=${Math.max(0, Math.floor(seconds))}s`
}

export function stageText(stage: Stage | null, progress: Progress | null): string {
  switch (stage) {
    case 'fetching_captions':
      return 'Fetching captions…'
    case 'downloading_audio':
      return 'Downloading audio…'
    case 'transcribing':
      return 'Transcribing audio…'
    case 'summarizing':
      if (!progress || progress.total <= 1) return 'Summarizing…'
      return `Summarizing part ${Math.min(progress.done + 1, progress.total)} of ${progress.total}…`
    case 'merging':
      return 'Merging…'
    default:
      return 'Starting…'
  }
}

const SOURCE_LABELS: Record<string, string> = {
  captions: 'Captions',
  'stt-local': 'Speech-to-text (local)',
  'stt-openai': 'Speech-to-text (OpenAI)',
}

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source
}

function formatRate(n: number): string {
  return Number.isInteger(n) ? `$${n}` : `$${n.toFixed(2)}`
}

/** "$1 in / $5 out per 1M tokens". */
export function modelPrice(m: ModelOption): string {
  return `${formatRate(m.input)} in / ${formatRate(m.output)} out per 1M tokens`
}

/** Picker label: "GPT-6.1 Terra · $1 in / $5 out per 1M tokens". */
export function modelLabel(m: ModelOption): string {
  return `${m.label} · ${modelPrice(m)}`
}

/** "sk-…wxyz": enough to recognise a key without showing it. */
export function maskKey(key: string): string {
  const k = key.trim()
  return k.length < 12 ? '…' : `${k.slice(0, 3)}…${k.slice(-4)}`
}

/** Dollars with enough precision to be useful for tiny per-video costs. */
export function formatUsd(n: number): string {
  if (n === 0) return '$0.00'
  if (n < 0.0001) return '<$0.0001'
  return `$${n < 0.1 ? n.toPrecision(2) : n.toFixed(2)}`
}

function usageDetails(u: Usage): string {
  const fmt = (n: number) => n.toLocaleString('en-US')
  const cached = u.cached_input_tokens ? ` (${fmt(u.cached_input_tokens)} cached)` : ''
  return [
    `${fmt(u.input_tokens)} input tokens${cached}`,
    `${fmt(u.output_tokens)} output tokens`,
    `${u.calls} ${u.calls === 1 ? 'call' : 'calls'}`,
    u.model,
  ].join(' · ')
}

/** The cost line under a summary. `cached`: this request reused a cached summary. */
export function costText(usage: Usage | null, cached: boolean): string {
  if (!usage) {
    return cached ? "From cache, no new LLM cost. The original cost wasn't recorded." : 'LLM cost not available.'
  }
  const cost = usage.cost_usd === null ? `unknown (no price for ${usage.model})` : formatUsd(usage.cost_usd)
  const lead = cached ? 'From cache, no new LLM cost. Originally:' : 'Estimated LLM cost:'
  return `${lead} ${cost} · ${usageDetails(usage)}`
}
