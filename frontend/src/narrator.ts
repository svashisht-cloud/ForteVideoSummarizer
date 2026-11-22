import type { TtsCatalog } from './api'

/** The natural voice to use for `lang`: the saved one if it belongs to the
 * language, else the language's default. Null if there's no natural voice. */
export function ttsVoiceFor(catalog: TtsCatalog | null, lang: string, saved: string | null): string | null {
  const entry = catalog?.[lang]
  if (!entry) return null
  return saved && entry.voices.some((v) => v.id === saved) ? saved : entry.default
}

/** Segments to have ready: the current one and the next `n`. */
export function prefetchIndices(index: number, total: number, n: number): number[] {
  const out: number[] = []
  for (let i = index; i <= index + n && i < total; i++) out.push(i)
  return out
}

const PREVIEW: Record<string, string> = {
  en: 'Hi! This is how I’ll sound when I read your summaries aloud.',
  es: '¡Hola! Así sonaré cuando lea tus resúmenes en voz alta.',
  fr: 'Bonjour ! Voici ma voix quand je lirai vos résumés à voix haute.',
  hi: 'नमस्ते! जब मैं आपके सारांश पढ़ूँगी, तो मेरी आवाज़ ऐसी होगी।',
  it: 'Ciao! Ecco come suonerò quando leggerò ad alta voce i tuoi riassunti.',
  pt: 'Olá! É assim que vou soar quando ler seus resumos em voz alta.',
  zh: '你好！我朗读你的摘要时，听起来就是这样。',
}

/** A short sample sentence for the voice preview. */
export function previewText(lang: string): string {
  return PREVIEW[lang] ?? PREVIEW.en
}
