import { useCallback, useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { getModels, getTtsVoices, type Mode, type ModelsResponse, type TtsCatalog } from './api'
import { JobForm } from './components/JobForm'
import { LinkGuide } from './components/LinkGuide'
import { ReaderPane } from './components/ReaderPane'
import { NowViewing, Outline, Wordmark } from './components/Sidebar'
import { ErrorBox, Progress } from './components/Status'
import { Welcome } from './components/Welcome'
import { PlayerProvider } from './player'
import { loadMode, loadOnboarded, saveMode, saveOnboarded } from './storage'
import { useJob } from './useJob'

type Request = [url: string, lang: string, model: string | null, apiKey: string | null, mode: Mode]

/** Animate a layout change with the View Transitions API when available (the
 * link bar has the same view-transition-name in both layouts, so it glides
 * from the welcome screen into the sidebar). Instant otherwise. */
function withTransition(update: () => void) {
  const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown }
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (!doc.startViewTransition || reduce) return update()
  doc.startViewTransition(() => flushSync(update))
}

export default function App() {
  const { job, error, running, start } = useJob()
  const [models, setModels] = useState<ModelsResponse | null>(null)
  const [ttsCatalog, setTtsCatalog] = useState<TtsCatalog | null>(null)
  const [request, setRequest] = useState<Request | null>(null)
  const [mode, setMode] = useState<Mode>(loadMode)
  const [welcome, setWelcome] = useState(() => !loadOnboarded()) // first visit
  const [arrived, setArrived] = useState(false) // just came from the welcome screen
  const [url, setUrl] = useState('')
  const [editing, setEditing] = useState(false)
  const [formKey, setFormKey] = useState(0) // bump to reset the form ("New summary")
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())
  const [activeSection, setActiveSection] = useState<number | null>(null)
  const last = useRef<Request | null>(null)

  useEffect(() => {
    // Without the list the form still works and the server uses its default model.
    getModels()
      .then(setModels)
      .catch(() => setModels(null))
    // Natural voices; without them read-aloud uses the device voice. Also warms the model.
    getTtsVoices()
      .then(setTtsCatalog)
      .catch(() => setTtsCatalog(null))
  }, [])

  function choose(m: Mode) {
    changeMode(m)
    saveOnboarded()
    withTransition(() => {
      setWelcome(false)
      setArrived(true)
    })
  }

  function showWelcome() {
    withTransition(() => setWelcome(true))
  }

  function submit(...req: Request) {
    setArrived(false)
    last.current = req
    setRequest(req)
    setEditing(false)
    setCollapsed(new Set())
    setActiveSection(null)
    void start(...req)
  }

  function changeMode(m: Mode) {
    setMode(m)
    saveMode(m)
  }

  /** From a free result: switch to AI and show the options (URL kept) to run it. */
  function upgradeToAi() {
    changeMode('ai')
    setEditing(true)
  }

  const collapse = useCallback((sections: number[], shut: boolean) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      for (const i of sections) {
        if (shut) next.add(i)
        else next.delete(i)
      }
      return next
    })
  }, [])

  function jumpTo(i: number) {
    collapse([i], false)
    setActiveSection(i)
    // After the section re-renders open.
    requestAnimationFrame(() =>
      document.getElementById(`sec-${i}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
    )
  }

  const result = job?.status === 'done' ? job.result : null
  const showForm = !result || editing

  if (welcome) {
    return <Welcome models={models} url={url} onUrlChange={setUrl} onChoose={choose} />
  }

  return (
    <PlayerProvider>
      <div className="lg:grid lg:h-dvh lg:grid-cols-[minmax(320px,380px)_1fr]">
        <aside className="border-b border-border bg-sidebar lg:overflow-y-auto lg:border-r lg:border-b-0">
          <div className="space-y-7 px-5 py-5 lg:py-6">
            <div className="flex items-center justify-between gap-3">
              <Wordmark />
              <button
                type="button"
                onClick={showWelcome}
                title="Free or AI? Show the welcome screen"
                aria-label="Show the welcome screen"
                className="grid size-7 place-items-center rounded-full text-sm text-dim hover:bg-foreground/5 hover:text-foreground"
              >
                ?
              </button>
            </div>
            {result && request && (
              <NowViewing
                result={result}
                lang={request[1]}
                model={request[2]}
                mode={result.mode}
                models={models}
                editing={editing}
                onEdit={() => setEditing((e) => !e)}
                onNew={() => {
                  setFormKey((k) => k + 1)
                  setUrl('')
                  setEditing(true)
                }}
              />
            )}
            <div className={showForm ? '' : 'hidden'}>
              <JobForm
                key={formKey}
                running={running}
                models={models}
                mode={mode}
                onModeChange={changeMode}
                url={url}
                onUrlChange={setUrl}
                attention={arrived}
                onSubmit={submit}
              />
            </div>
            {result && !editing && (
              <div className="hidden lg:block">
                <Outline result={result} active={activeSection} onJump={jumpTo} />
              </div>
            )}
          </div>
        </aside>

        <main className="min-w-0 lg:overflow-y-auto">
          {running && (
            <div className="mx-auto max-w-[68ch] px-5 py-16 sm:px-8 lg:py-28">
              <Progress job={job} />
            </div>
          )}
          {error && !running && (
            <div className="mx-auto max-w-[68ch] px-5 py-16 sm:px-8 lg:py-28">
              <ErrorBox message={error} onRetry={() => last.current && submit(...last.current)} />
            </div>
          )}
          {result && request && (
            <ReaderPane
              result={result}
              lang={result.mode === 'free' ? result.language.split('-')[0].toLowerCase() : request[1]}
              ttsCatalog={ttsCatalog}
              onUpgrade={upgradeToAi}
              collapsed={collapsed}
              onCollapse={collapse}
              onSectionInView={setActiveSection}
            />
          )}
          {!running && !error && !result && (
            <LinkGuide
              onExample={(u) => {
                setUrl(u)
                document.getElementById('youtube-link')?.focus()
              }}
            />
          )}
        </main>
      </div>
    </PlayerProvider>
  )
}
