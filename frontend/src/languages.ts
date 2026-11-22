/** Summary languages offered in the picker (ISO code, English name). */
export const LANGUAGES = [
  ['en', 'English'],
  ['hi', 'Hindi'],
  ['es', 'Spanish'],
  ['fr', 'French'],
  ['de', 'German'],
  ['pt', 'Portuguese'],
  ['ja', 'Japanese'],
  ['ko', 'Korean'],
  ['zh', 'Chinese'],
  ['ar', 'Arabic'],
  ['ru', 'Russian'],
  ['it', 'Italian'],
] as const

export function languageName(code: string): string {
  return LANGUAGES.find(([c]) => c === code)?.[1] ?? code
}
