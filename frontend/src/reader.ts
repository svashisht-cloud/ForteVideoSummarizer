import type { Summary } from './api'
import { formatTs, youtubeLink } from './format'

/** Reading text sizes in px for A−/A+. */
export const TEXT_SIZES = [16, 17, 18, 20] as const

export interface PointRef {
  section: number
  point: number
}

/** The point being discussed at video time `t`: the latest point at or before `t`
 * (the first one, if several share that time). Null before the first point. */
export function pointAtTime(summary: Summary, t: number): PointRef | null {
  let best: PointRef | null = null
  let bestT = -Infinity
  summary.sections.forEach((s, si) =>
    s.points.forEach((p, pi) => {
      if (p.t <= t && p.t > bestT) {
        best = { section: si, point: pi }
        bestT = p.t
      }
    }),
  )
  return best
}

/** The section being discussed at video time `t`: the last one that has started. */
export function sectionAtTime(summary: Summary, t: number): number | null {
  if (!summary.sections.length) return null
  let found = 0
  summary.sections.forEach((s, i) => {
    if (s.start <= t) found = i
  })
  return found
}

export function summaryToMarkdown(summary: Summary, videoId: string): string {
  const link = (t: number, label = formatTs(t)) => `[${label}](${youtubeLink(videoId, t)})`
  const lines = ['## TL;DR', '', summary.tldr.trim(), '']
  for (const s of summary.sections) {
    lines.push(`## ${s.title.trim()} (${link(s.start, `${formatTs(s.start)}–${formatTs(s.end)}`)})`, '')
    for (const p of s.points) lines.push(`- ${link(p.t)} ${p.text.trim()}`)
    lines.push('')
  }
  return lines.join('\n')
}

export function summaryToText(summary: Summary): string {
  const lines = ['TL;DR', summary.tldr.trim(), '']
  for (const s of summary.sections) {
    lines.push(`${s.title.trim()} (${formatTs(s.start)}–${formatTs(s.end)})`)
    for (const p of s.points) lines.push(`- ${formatTs(p.t)} ${p.text.trim()}`)
    lines.push('')
  }
  return lines.join('\n')
}
