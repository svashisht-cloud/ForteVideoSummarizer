import type { MouseEvent } from 'react'
import { formatTs, youtubeLink } from '../format'
import { usePlayer } from '../playerContext'

interface Props {
  videoId: string
  seconds: number
  label?: string
  className?: string
}

/** A timestamp: seeks the embedded player on click. It's still a real link, so
 * ⌘/Ctrl/Shift/middle-click opens YouTube at that second in a new tab. */
export function Timestamp({ videoId, seconds, label, className = '' }: Props) {
  const { seek } = usePlayer()
  function click(e: MouseEvent<HTMLAnchorElement>) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
    if (seek(seconds)) e.preventDefault()
  }
  return (
    <a
      href={youtubeLink(videoId, seconds)}
      target="_blank"
      rel="noopener noreferrer"
      onClick={click}
      title={`Play from ${formatTs(seconds)}`}
      className={`font-mono text-[0.8em] whitespace-nowrap text-dim tabular-nums transition-colors hover:text-accent ${className}`}
    >
      {label ?? formatTs(seconds)}
    </a>
  )
}
