import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { loadApi, PlayerContext, usePlayer, type YTPlayer } from './playerContext'

export function PlayerProvider({ children }: { children: ReactNode }) {
  const player = useRef<YTPlayer | null>(null)
  const [time, setTime] = useState<number | null>(null)
  const [started, setStarted] = useState(false)

  const register = useCallback((p: YTPlayer | null) => {
    player.current = p
    setTime(null)
    setStarted(false)
  }, [])

  const seek = useCallback((seconds: number) => {
    const p = player.current
    if (!p) return false
    p.seekTo(seconds, true)
    p.playVideo()
    setStarted(true)
    setTime(seconds)
    return true
  }, [])

  const pause = useCallback(() => player.current?.pauseVideo(), [])

  // Track playback time while the video plays (also catches play pressed inside the iframe).
  useEffect(() => {
    const id = window.setInterval(() => {
      const p = player.current
      if (!p || typeof p.getPlayerState !== 'function') return
      const state = p.getPlayerState()
      if (state === 1 /* PLAYING */) {
        setStarted(true)
        setTime(p.getCurrentTime())
      }
    }, 500)
    return () => window.clearInterval(id)
  }, [])

  const value = useMemo(
    () => ({ seek, pause, register, time: started ? time : null }),
    [seek, pause, register, time, started],
  )
  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>
}

/** The embedded YouTube player (privacy-enhanced youtube-nocookie.com host). */
export function Player({ videoId }: { videoId: string }) {
  const { register } = usePlayer()
  const host = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    let instance: YTPlayer | null = null
    const el = host.current
    // The API replaces the element it's given with an iframe, so give it a
    // child we create ourselves rather than a React-managed node.
    const mount = document.createElement('div')
    el?.appendChild(mount)
    loadApi()
      .then((YT) => {
        if (cancelled) return
        instance = new YT.Player(mount, {
          host: 'https://www.youtube-nocookie.com',
          videoId,
          width: '100%',
          height: '100%',
          playerVars: { rel: 0, playsinline: 1, modestbranding: 1 },
          events: { onReady: () => !cancelled && register(instance) },
        })
      })
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
      register(null)
      instance?.destroy()
      el?.replaceChildren()
    }
  }, [videoId, register])

  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-black/90">
      <div ref={host} className="absolute inset-0 [&_iframe]:h-full [&_iframe]:w-full" />
      {failed && (
        <p className="absolute inset-0 grid place-items-center p-4 text-center text-sm text-white/80">
          The video player couldn’t load. Timestamps will open YouTube in a new tab.
        </p>
      )}
    </div>
  )
}
