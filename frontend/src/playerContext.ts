import { createContext, useContext } from 'react'

// Minimal typing for the YouTube IFrame Player API.
export interface YTPlayer {
  seekTo(seconds: number, allowSeekAhead: boolean): void
  playVideo(): void
  pauseVideo(): void
  getCurrentTime(): number
  getPlayerState(): number
  destroy(): void
}
interface YTNamespace {
  Player: new (el: HTMLElement, opts: object) => YTPlayer
  PlayerState: { PLAYING: number; PAUSED: number }
}
declare global {
  interface Window {
    YT?: YTNamespace
    onYouTubeIframeAPIReady?: () => void
  }
}

let apiPromise: Promise<YTNamespace> | null = null

/** Loads https://www.youtube.com/iframe_api once. */
export function loadApi(): Promise<YTNamespace> {
  if (window.YT?.Player) return Promise.resolve(window.YT)
  apiPromise ??= new Promise<YTNamespace>((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady
    window.onYouTubeIframeAPIReady = () => {
      previous?.()
      if (window.YT) resolve(window.YT)
    }
    const script = document.createElement('script')
    script.src = 'https://www.youtube.com/iframe_api'
    script.async = true
    script.onerror = () => {
      apiPromise = null
      reject(new Error('YouTube player failed to load'))
    }
    document.head.appendChild(script)
  })
  return apiPromise
}

export interface PlayerApi {
  /** Seek the embedded player and play. False if no player is ready (caller falls back to a link). */
  seek: (seconds: number) => boolean
  pause: () => void
  /** Current playback time once the video has been started, else null. */
  time: number | null
  register: (p: YTPlayer | null) => void
}

export const PlayerContext = createContext<PlayerApi>({ seek: () => false, pause: () => {}, time: null, register: () => {} })

export function usePlayer() {
  return useContext(PlayerContext)
}
