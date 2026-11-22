import { useCallback, useEffect, useRef, useState } from 'react'
import { createJob, getJob, type Job } from './api'

const POLL_MS = 1000

/** Starts a summary job and polls it every second until it is done or fails. */
export function useJob() {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  // Bumped on every start/unmount so stale polls from an older job stop.
  const run = useRef(0)

  useEffect(
    () => () => {
      run.current++
    },
    [],
  )

  const start = useCallback(async (url: string, lang: string, model: string | null, apiKey: string | null) => {
    const id = ++run.current
    const current = () => run.current === id
    setJob(null)
    setError(null)
    setRunning(true)
    try {
      const { job_id } = await createJob(url, lang, model, apiKey)
      while (current()) {
        const j = await getJob(job_id)
        if (!current()) return
        setJob(j)
        if (j.status === 'done') break
        if (j.status === 'error') {
          setError(j.error || 'Something went wrong.')
          break
        }
        await new Promise((r) => setTimeout(r, POLL_MS))
      }
    } catch (e) {
      if (current()) setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (current()) setRunning(false)
    }
  }, [])

  return { job, error, running, start }
}
