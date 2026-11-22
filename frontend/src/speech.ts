import type { Summary } from './api'

export interface SpeechSegment {
  /** Matches the element to highlight: "tldr", "s{section}", "s{section}p{point}". */
  id: string
  text: string
}

/** What read-aloud says, in order. One short utterance each: Chrome can cut off long ones. */
export function speechSegments(summary: Summary): SpeechSegment[] {
  const out: SpeechSegment[] = []
  const add = (id: string, text: string) => {
    const t = text.trim()
    if (t) out.push({ id, text: t })
  }
  add('tldr', summary.tldr)
  summary.sections.forEach((s, i) => {
    const title = s.title.trim()
    add(`s${i}`, title && !/[.!?:。！？]$/.test(title) ? `${title}.` : title)
    s.points.forEach((p, j) => add(`s${i}p${j}`, p.text))
  })
  return out
}

const base = (tag: string) => tag.toLowerCase().replace('_', '-').split('-')[0]

/** Best installed voice for a language ("hi", "en-GB"), or null if none speaks it. */
export function pickVoice(voices: SpeechSynthesisVoice[], lang: string): SpeechSynthesisVoice | null {
  const want = lang.toLowerCase().replace('_', '-')
  const matching = voices.filter((v) => base(v.lang) === base(want))
  if (!matching.length) return null
  const norm = (v: SpeechSynthesisVoice) => v.lang.toLowerCase().replace('_', '-')
  return (
    matching.find((v) => norm(v) === want) ??
    matching.find((v) => v.default) ??
    (base(want) === 'en' ? matching.find((v) => norm(v) === 'en-us' && v.localService) : undefined) ??
    matching.find((v) => v.localService) ??
    matching[0]
  )
}
