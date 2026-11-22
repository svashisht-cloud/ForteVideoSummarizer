import { useCallback, useEffect, useRef, useState } from 'react'
import { getModels, getTtsVoices, type ModelsResponse, type TtsCatalog } from './api'
import { JobForm } from './components/JobForm'
import { ReaderPane } from './components/ReaderPane'
import { NowViewing, Outline, Wordmark } from './components/Sidebar'
import { EmptyState, ErrorBox, Progress } from './components/Status'
import { PlayerProvider } from './player'
import { useJob } from './useJob'

type Request = [url: string, lang: string, model: string | null, apiKey: string | null]

export default function App() {
  const { job, error, running, start } = useJob()
  const [models, setModels] = useState<ModelsResponse | null>(null)
  const [ttsCatalog, setTtsCatalog] = useState<TtsCatalog | null>(null)
  const [request, setRequest] = useState<Request | null>(null)
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

  function submit(...req: Request) {
    last.current = req
    setRequest(req)
    setEditing(false)
    setCollapsed(new Set())
    setActiveSection(null)
    void start(...req)
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

  return (
    <PlayerProvider>
      <div className="lg:grid lg:h-dvh lg:grid-cols-[minmax(320px,380px)_1fr]">
        <aside className="border-b border-border bg-sidebar lg:overflow-y-auto lg:border-r lg:border-b-0">
          <div className="space-y-7 px-5 py-5 lg:py-6">
            <Wordmark />
            {result && request && (
              <NowViewing
                result={result}
                lang={request[1]}
                model={request[2]}
                models={models}
                editing={editing}
                onEdit={() => setEditing((e) => !e)}
                onNew={() => {
                  setFormKey((k) => k + 1)
                  setEditing(true)
                }}
              />
            )}
            <div className={showForm ? '' : 'hidden'}>
              <JobForm key={formKey} running={running} models={models} onSubmit={submit} />
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
              lang={request[1]}
              ttsCatalog={ttsCatalog}
              collapsed={collapsed}
              onCollapse={collapse}
              onSectionInView={setActiveSection}
            />
          )}
          {!running && !error && !result && <EmptyState />}
        </main>
      </div>
    </PlayerProvider>
  )
}
