import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchSpeech, type TtsCatalog } from '../api'
import { prefetchIndices, previewText, ttsVoiceFor } from '../narrator'
import { pickVoice, type SpeechSegment } from '../speech'
import { loadVoice, saveVoice } from '../storage'

const RATES = [0.75, 1, 1.25, 1.5] as const
const PREFETCH = 2 // clips fetched ahead of the one playing
type State = 'idle' | 'loading' | 'playing' | 'paused'

const synth = (): SpeechSynthesis | null =>
  typeof window !== 'undefined' && 'speechSynthesis' in window ? window.speechSynthesis : null

/** The device's voices; they load asynchronously in Chrome. */
function useDeviceVoices(): SpeechSynthesisVoice[] {
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>(() => synth()?.getVoices() ?? [])
  useEffect(() => {
    const s = synth()
    if (!s) return
    const update = () => setVoices(s.getVoices())
    update()
    s.addEventListener('voiceschanged', update)
    return () => s.removeEventListener('voiceschanged', update)
  }, [])
  return voices
}

interface Props {
  segments: SpeechSegment[]
  /** Language of the summary text, e.g. "hi". */
  lang: string
  /** Natural voices offered by the server, or null (device voice only). */
  catalog: TtsCatalog | null
  /** Called with the id of the segment being read, or null when reading stops. */
  onActive: (id: string | null) => void
  /** Called when reading starts from the beginning (e.g. to pause the video). */
  onStart?: () => void
}

/**
 * Reads the summary aloud. Uses the server's natural voice (Kokoro) when the
 * language has one, one clip per segment with the next ones prefetched; falls
 * back to the browser's built-in voice for other languages or if the server fails.
 */
export function ReadAloud({ segments, lang, catalog, onActive, onStart }: Props) {
  const deviceVoice = pickVoice(useDeviceVoices(), lang)
  // Voices picked this session (else the one saved on this device), per language.
  const [picked, setPicked] = useState<Record<string, string>>({})
  const naturalVoice = ttsVoiceFor(catalog, lang, picked[lang] ?? loadVoice(lang))
  // The summary for which the server voice failed; it uses the device voice from then on.
  const [fellBackFor, setFellBackFor] = useState<SpeechSegment[] | null>(null)
  const fellBack = fellBackFor === segments
  const engine: 'natural' | 'device' | null = naturalVoice && !fellBack ? 'natural' : deviceVoice ? 'device' : null

  const [state, setState] = useState<State>('idle')
  const [rate, setRate] = useState<number>(1)
  const [previewing, setPreviewing] = useState(false)

  const index = useRef(0)
  const run = useRef(0) // bumped on every (re)start or stop; stale callbacks check it
  const paused = useRef(false)
  const ready = useRef(false) // the audio element holds the current segment's clip
  const audio = useRef<HTMLAudioElement | null>(null)
  const preview = useRef<HTMLAudioElement | null>(null)
  const clips = useRef(new Map<number, Promise<string>>())
  const urls = useRef<string[]>([])
  const abort = useRef<AbortController | null>(null)

  const player = () => (audio.current ??= new Audio())

  const resetClips = useCallback(() => {
    abort.current?.abort()
    abort.current = null
    clips.current.clear()
    urls.current.forEach((u) => URL.revokeObjectURL(u))
    urls.current = []
  }, [])

  const stop = useCallback(() => {
    run.current++
    paused.current = false
    synth()?.cancel()
    audio.current?.pause()
    preview.current?.pause()
    resetClips()
    index.current = 0
    setState('idle')
    onActive(null)
  }, [onActive, resetClips])

  const finish = useCallback(() => {
    index.current = 0
    setState('idle')
    onActive(null)
  }, [onActive])

  // --- device voice (Web Speech API) ---
  const speakDevice = useCallback(
    (from: number, speed: number) => {
      const s = synth()
      if (!s || !deviceVoice) return finish()
      const id = ++run.current
      s.cancel()
      const next = (k: number) => {
        if (run.current !== id) return
        if (k >= segments.length) return finish()
        index.current = k
        onActive(segments[k].id)
        const u = new SpeechSynthesisUtterance(segments[k].text)
        u.voice = deviceVoice
        u.lang = deviceVoice.lang
        u.rate = speed
        u.onend = () => next(k + 1)
        u.onerror = (e) => {
          // "interrupted"/"canceled" come from our own cancel(); anything else skips ahead.
          if (e.error !== 'interrupted' && e.error !== 'canceled') next(k + 1)
        }
        s.speak(u)
      }
      setState('playing')
      next(from)
    },
    [segments, deviceVoice, onActive, finish],
  )

  // --- natural voice (server, Kokoro) ---
  const clip = useCallback(
    (k: number, voice: string) => {
      let p = clips.current.get(k)
      if (!p) {
        abort.current ??= new AbortController()
        p = fetchSpeech(segments[k].text, lang, voice, abort.current.signal).then((blob) => {
          const url = URL.createObjectURL(blob)
          urls.current.push(url)
          return url
        })
        p.catch(() => {}) // handled where awaited
        clips.current.set(k, p)
      }
      return p
    },
    [segments, lang],
  )

  const speakNatural = useCallback(
    (from: number, voice: string, speed: number) => {
      const id = ++run.current
      synth()?.cancel()
      const a = player()
      a.pause()
      const step = async (k: number) => {
        if (run.current !== id) return
        if (k >= segments.length) return finish()
        index.current = k
        ready.current = false
        onActive(segments[k].id)
        prefetchIndices(k, segments.length, PREFETCH).forEach((j) => void clip(j, voice))
        let url: string
        try {
          if (!paused.current) setState('loading')
          url = await clip(k, voice)
        } catch {
          if (run.current !== id) return
          // Server can't speak right now: carry on with the device voice.
          setFellBackFor(segments)
          resetClips()
          return speakDevice(k, speed)
        }
        if (run.current !== id) return
        a.src = url
        ready.current = true
        a.playbackRate = speed
        a.onended = () => void step(k + 1)
        if (paused.current) return setState('paused')
        setState('playing')
        a.play().catch(() => {
          if (run.current === id) setState('paused') // autoplay blocked: let the user press Resume
        })
      }
      void step(from)
    },
    [segments, clip, onActive, finish, resetClips, speakDevice],
  )

  // Stop when the summary or language changes, or the component goes away.
  useEffect(() => stop, [segments, lang, stop])

  if (!engine) {
    return (
      <span className="text-xs text-dim" title={`No ${lang} voice is available`}>
        Read aloud isn’t available in this language
      </span>
    )
  }

  function playPause() {
    if (state === 'playing' || state === 'loading') {
      paused.current = true
      if (engine === 'natural') audio.current?.pause()
      else synth()?.pause()
      setState('paused')
    } else if (state === 'paused') {
      paused.current = false
      if (engine === 'natural') {
        const a = player()
        if (ready.current) {
          setState('playing')
          void a.play()
        } else setState('loading') // still fetching; step() starts it
      } else {
        synth()?.resume()
        setState('playing')
      }
    } else {
      onStart?.()
      paused.current = false
      if (engine === 'natural' && naturalVoice) speakNatural(0, naturalVoice, rate)
      else speakDevice(0, rate)
    }
  }

  function changeRate(r: number) {
    setRate(r)
    if (state === 'idle') return
    if (engine === 'natural') player().playbackRate = r
    else speakDevice(index.current, r) // restart the segment so the new speed applies
  }

  function changeVoice(v: string) {
    setPicked((prev) => ({ ...prev, [lang]: v }))
    saveVoice(lang, v)
    if (state !== 'idle') stop()
  }

  async function playPreview() {
    if (!naturalVoice) return
    if (state !== 'idle') stop()
    setPreviewing(true)
    try {
      const blob = await fetchSpeech(previewText(lang), lang, naturalVoice)
      const url = URL.createObjectURL(blob)
      const p = new Audio(url)
      preview.current = p
      p.onended = () => URL.revokeObjectURL(url)
      await p.play()
    } catch {
      // Preview is optional; Listen reports real problems by falling back.
    } finally {
      setPreviewing(false)
    }
  }

  const btn =
    'inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium text-muted hover:bg-foreground/5 hover:text-foreground disabled:opacity-50'
  const voices = catalog?.[lang]?.voices ?? []

  return (
    <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Read aloud">
      <button type="button" onClick={playPause} className={btn}>
        {state === 'loading' ? <Spinner /> : state === 'playing' ? <PauseIcon /> : <PlayIcon />}
        {state === 'idle' ? 'Listen' : state === 'loading' ? 'Preparing…' : state === 'playing' ? 'Pause' : 'Resume'}
      </button>
      {state !== 'idle' && (
        <>
          <button type="button" onClick={stop} className={btn} aria-label="Stop">
            <StopIcon />
          </button>
          <label className="sr-only" htmlFor="read-aloud-rate">
            Speed
          </label>
          <select
            id="read-aloud-rate"
            value={rate}
            onChange={(e) => changeRate(Number(e.target.value))}
            className="h-8 rounded-md border-0 bg-transparent px-1 text-sm text-muted hover:bg-foreground/5"
          >
            {RATES.map((r) => (
              <option key={r} value={r}>
                {r}×
              </option>
            ))}
          </select>
        </>
      )}
      {engine === 'natural' && naturalVoice && voices.length > 0 ? (
        <>
          <label className="sr-only" htmlFor="read-aloud-voice">
            Voice
          </label>
          <select
            id="read-aloud-voice"
            value={naturalVoice}
            onChange={(e) => changeVoice(e.target.value)}
            title="Voice"
            className="h-8 max-w-36 rounded-md border-0 bg-transparent px-1 text-sm text-muted hover:bg-foreground/5"
          >
            {voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
                {v.accent ? ` (${v.accent})` : ''} · {v.gender === 'female' ? '♀' : '♂'}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void playPreview()}
            disabled={previewing}
            className={btn}
            title="Preview this voice"
            aria-label="Preview this voice"
          >
            {previewing ? <Spinner /> : <SpeakerIcon />}
          </button>
        </>
      ) : (
        <span className="px-1 text-xs text-dim" title="This language uses your device's built-in voice">
          Device voice
        </span>
      )}
    </div>
  )
}

const icon = { width: 14, height: 14, viewBox: '0 0 24 24', fill: 'currentColor', 'aria-hidden': true } as const
const PlayIcon = () => (
  <svg {...icon}>
    <path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5Z" />
  </svg>
)
const PauseIcon = () => (
  <svg {...icon}>
    <rect x="6" y="4.5" width="4" height="15" rx="1" />
    <rect x="14" y="4.5" width="4" height="15" rx="1" />
  </svg>
)
const StopIcon = () => (
  <svg {...icon}>
    <rect x="5.5" y="5.5" width="13" height="13" rx="1.5" />
  </svg>
)
const SpeakerIcon = () => (
  <svg {...icon} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 5 6 9H3v6h3l5 4V5Z" />
    <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
  </svg>
)
const Spinner = () => (
  <span className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />
)
