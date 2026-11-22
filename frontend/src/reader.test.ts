import { describe, expect, it } from 'vitest'
import type { Summary } from './api'
import { pointAtTime, sectionAtTime, summaryToMarkdown, summaryToText } from './reader'

const summary: Summary = {
  tldr: 'The gist.',
  sections: [
    {
      title: 'Intro',
      start: 0,
      end: 62,
      points: [
        { t: 0, text: 'First.' },
        { t: 30, text: 'Second.' },
        { t: 30, text: 'Same time.' },
      ],
    },
    { title: 'Later', start: 61, end: 125, points: [{ t: 61, text: 'Third.' }] },
  ],
  usage: null,
}

describe('pointAtTime', () => {
  it('is null before the first point', () => {
    const s = { ...summary, sections: [{ ...summary.sections[0], points: [{ t: 10, text: 'x' }] }] }
    expect(pointAtTime(s, 5)).toBeNull()
  })
  it('finds the latest point at or before the time', () => {
    expect(pointAtTime(summary, 0)).toEqual({ section: 0, point: 0 })
    expect(pointAtTime(summary, 29.9)).toEqual({ section: 0, point: 0 })
    expect(pointAtTime(summary, 200)).toEqual({ section: 1, point: 0 })
  })
  it('picks the first of several points sharing a time', () =>
    expect(pointAtTime(summary, 45)).toEqual({ section: 0, point: 1 }))
  it('crosses into the next section', () => expect(pointAtTime(summary, 61.5)).toEqual({ section: 1, point: 0 }))
})

describe('sectionAtTime', () => {
  it('is the last section that has started', () => {
    expect(sectionAtTime(summary, 10)).toBe(0)
    expect(sectionAtTime(summary, 61)).toBe(1)
  })
  it('defaults to the first section before any start', () => {
    const s = { ...summary, sections: [{ ...summary.sections[0], start: 5 }] }
    expect(sectionAtTime(s, 1)).toBe(0)
  })
  it('is null with no sections', () => expect(sectionAtTime({ ...summary, sections: [] }, 1)).toBeNull())
})

describe('export', () => {
  it('markdown links every timestamp to YouTube', () => {
    expect(summaryToMarkdown(summary, 'VID')).toBe(
      [
        '## TL;DR',
        '',
        'The gist.',
        '',
        '## Intro ([0:00–1:02](https://www.youtube.com/watch?v=VID&t=0s))',
        '',
        '- [0:00](https://www.youtube.com/watch?v=VID&t=0s) First.',
        '- [0:30](https://www.youtube.com/watch?v=VID&t=30s) Second.',
        '- [0:30](https://www.youtube.com/watch?v=VID&t=30s) Same time.',
        '',
        '## Later ([1:01–2:05](https://www.youtube.com/watch?v=VID&t=61s))',
        '',
        '- [1:01](https://www.youtube.com/watch?v=VID&t=61s) Third.',
        '',
      ].join('\n'),
    )
  })

  it('plain text keeps timestamps without links', () => {
    expect(summaryToText(summary)).toBe(
      [
        'TL;DR',
        'The gist.',
        '',
        'Intro (0:00–1:02)',
        '- 0:00 First.',
        '- 0:30 Second.',
        '- 0:30 Same time.',
        '',
        'Later (1:01–2:05)',
        '- 1:01 Third.',
        '',
      ].join('\n'),
    )
  })
})
