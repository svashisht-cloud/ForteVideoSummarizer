// Types mirror backend/app/api/main.py.

export type Status = 'queued' | 'running' | 'done' | 'error'
/** 'free': no AI, key moments from the captions. 'ai': LLM summary. */
export type Mode = 'free' | 'ai'
export type SummaryMethod = 'ai' | 'extractive'
export type Stage = 'fetching_captions' | 'downloading_audio' | 'transcribing' | 'summarizing' | 'merging'

export interface Progress {
  done: number
  total: number
}

export interface Point {
  t: number
  text: string
}

export interface Section {
  title: string
  start: number
  end: number
  points: Point[]
}

export interface Usage {
  model: string
  calls: number
  input_tokens: number // includes cached_input_tokens
  cached_input_tokens: number
  output_tokens: number
  cost_usd: number | null // null when the backend has no price for the model
}

export interface Summary {
  tldr: string
  sections: Section[]
  usage: Usage | null // null for free summaries and ones cached before usage was tracked
  method: SummaryMethod
}

export interface Block {
  start: number
  end: number
  text: string
}

export interface JobResult {
  summary: Summary
  transcript: Block[]
  video_id: string
  language: string
  source: string
  summary_cached: boolean // true: no LLM calls were made for this request
  mode: Mode
  title: string | null // video title, when known
}

export interface Job {
  status: Status
  stage: Stage | null
  progress: Progress | null
  result: JobResult | null
  error: string | null
}

export const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '')

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, init)
  } catch {
    throw new ApiError(`Can't reach the server at ${API_URL}. Is the backend running?`)
  }
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const detail = body?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d?.msg).filter(Boolean).join('; ')
          : `Request failed (${res.status})`
    throw new ApiError(message || `Request failed (${res.status})`)
  }
  return body as T
}

export interface ModelOption {
  id: string
  label: string
  input: number // USD per 1M tokens
  cached_input: number
  output: number
  cached_is_estimate: boolean
}

export interface ModelsResponse {
  default: string | null
  require_user_key: boolean
  models: ModelOption[]
}

export function getModels(): Promise<ModelsResponse> {
  return request('/models')
}

export interface TtsVoice {
  id: string
  label: string
  gender: 'female' | 'male'
  accent: string | null
}

/** Languages with a natural (Kokoro) voice: {lang: {default, voices}}. */
export type TtsCatalog = Record<string, { default: string; voices: TtsVoice[] }>

export function getTtsVoices(): Promise<TtsCatalog> {
  return request('/tts/voices')
}

/** One clip of natural speech as a WAV blob. Throws ApiError on failure. */
export async function fetchSpeech(text: string, lang: string, voice: string, signal?: AbortSignal): Promise<Blob> {
  let res: Response
  try {
    res = await fetch(`${API_URL}/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, lang, voice }),
      signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError(`Can't reach the server at ${API_URL}.`)
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(typeof body?.detail === 'string' ? body.detail : `Speech failed (${res.status})`)
  }
  return res.blob()
}

/** `apiKey`: the user's own OpenAI key. Sent only as a header, never in the URL or body. */
export function createJob(
  url: string,
  lang: string,
  model: string | null,
  apiKey: string | null,
  mode: Mode,
): Promise<{ job_id: string }> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey && mode === 'ai') headers['X-OpenAI-Key'] = apiKey
  return request('/jobs', {
    method: 'POST',
    headers,
    body: JSON.stringify({ url, lang, model, mode }),
  })
}

export function getJob(id: string): Promise<Job> {
  return request(`/jobs/${encodeURIComponent(id)}`)
}
