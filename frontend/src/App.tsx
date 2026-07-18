import { useEffect, useMemo, useRef, useState } from 'react'
import {
  fetchSource,
  insertFindingSorted,
  setVerdict,
  subscribeAnalyze,
  uploadZip,
} from './api'
import { AnalysisProgress } from './components/AnalysisProgress'
import {
  FindingsList,
  filterFindings,
  type BandFilter,
} from './components/FindingsList'
import { SourceViewer } from './components/SourceViewer'
import { SummaryReportView } from './components/SummaryReportView'
import { exportFindingsPdf } from './exportPdf'
import { buildSummaryReport } from './summaryReport'
import type { Citation, Finding, JobStatus, SourceView } from './types'
import { categoryLabel } from './types'
import './App.css'

type Phase = 'idle' | 'uploading' | 'streaming' | 'done' | 'error'

function withViewTransition(update: () => void) {
  const doc = document as Document & {
    startViewTransition?: (cb: () => void) => void
  }
  if (typeof doc.startViewTransition === 'function') {
    doc.startViewTransition(update)
  } else {
    update()
  }
}

export default function App() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null)
  const [findings, setFindings] = useState<Finding[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [count, setCount] = useState<number | null>(null)
  const [filter, setFilter] = useState<BandFilter>('all')
  const [category, setCategory] = useState<string | 'all'>('all')
  const [source, setSource] = useState<SourceView | null>(null)
  const [sourceLoading, setSourceLoading] = useState(false)
  const [sourceError, setSourceError] = useState<string | null>(null)
  const unsubRef = useRef<(() => void) | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    return () => unsubRef.current?.()
  }, [])

  const resetForNewRun = () => {
    unsubRef.current?.()
    unsubRef.current = null
    setFindings([])
    setCount(null)
    setMessage(null)
    setJobStatus(null)
    setBusyId(null)
    setFilter('all')
    setCategory('all')
    setSource(null)
    setSourceError(null)
  }

  const onFile = async (file: File | undefined) => {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.zip')) {
      setMessage('Please upload a .zip dossier (not the sealed ground-truth file).')
      setPhase('error')
      return
    }
    resetForNewRun()
    setPhase('uploading')
    try {
      const { job_id } = await uploadZip(file)
      setJobId(job_id)
      setPhase('streaming')
      setJobStatus('queued')

      unsubRef.current = subscribeAnalyze(job_id, {
        onStatus: (s) => setJobStatus(s.status),
        onFinding: (f) => {
          withViewTransition(() => {
            setFindings((prev) => insertFindingSorted(prev, f))
          })
        },
        onDone: (d) => {
          setCount(d.count)
          setPhase('done')
          setJobStatus('ready')
        },
        onError: (err) => {
          const text =
            err instanceof Error ? err.message : err.message || 'Stream error'
          setMessage(text)
          setPhase('error')
        },
      })
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Upload failed')
      setPhase('error')
    } finally {
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const onVerify = async (findingId: string) => {
    if (!jobId) return
    setBusyId(findingId)
    try {
      const res = await setVerdict(jobId, findingId, 'verify')
      setFindings((prev) =>
        prev.map((f) =>
          f.id === findingId ? { ...f, status: res.status } : f,
        ),
      )
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Verify failed')
    } finally {
      setBusyId(null)
    }
  }

  const onDismiss = async (findingId: string) => {
    if (!jobId) return
    setBusyId(findingId)
    try {
      const res = await setVerdict(jobId, findingId, 'dismiss')
      setFindings((prev) =>
        prev.map((f) =>
          f.id === findingId ? { ...f, status: res.status } : f,
        ),
      )
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Dismiss failed')
    } finally {
      setBusyId(null)
    }
  }

  const onOpenSource = async (citation: Citation) => {
    if (!jobId) return
    const path = citation.source_path || citation.file
    if (!path || path.startsWith('duckdb:')) {
      setSourceError('No openable source file for this citation.')
      setSource(null)
      return
    }
    setSourceLoading(true)
    setSourceError(null)
    try {
      const view = await fetchSource(jobId, {
        path,
        line: citation.line,
        locator: citation.locator,
        quote: citation.quote,
      })
      setSource(view)
    } catch (err) {
      setSource(null)
      setSourceError(err instanceof Error ? err.message : 'Failed to open source')
    } finally {
      setSourceLoading(false)
    }
  }

  const waiting = phase === 'uploading' || phase === 'streaming'

  // Cross-filter counts: band chips respect selected category; category chips respect band.
  const bandScoped = useMemo(
    () => filterFindings(findings, 'all', category),
    [findings, category],
  )
  const categoryScoped = useMemo(
    () => filterFindings(findings, filter, 'all'),
    [findings, filter],
  )
  const combined = useMemo(
    () => filterFindings(findings, filter, category),
    [findings, filter, category],
  )
  const highCount = bandScoped.filter((f) => f.band === 'high').length
  const reviewCount = bandScoped.filter(
    (f) => f.band === 'needs_human_verification',
  ).length
  const categoryCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const f of categoryScoped) {
      for (const c of f.categories) {
        m.set(c, (m.get(c) ?? 0) + 1)
      }
    }
    // Keep the active category chip visible even when the band combo yields 0
    if (category !== 'all' && !m.has(category)) {
      m.set(category, 0)
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [categoryScoped, category])
  const showSource = sourceLoading || sourceError != null || source != null
  const summary = useMemo(() => buildSummaryReport(findings), [findings])

  return (
    <div className="shell">
      <div className="shell__atmosphere" aria-hidden="true" />

      <header className="topbar no-print">
        <a className="brand" href="/">
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__name">Auditor</span>
        </a>
        <p className="topbar__aside">AI supports. Auditors decide.</p>
      </header>

      <main className="app">
        <section className="hero">
          <p className="hero__eyebrow">Fraud findings feed</p>
          <h1 className="hero__brand">Auditor</h1>
          <p className="hero__lead">
            Think like an auditor: priority risk patterns only. Findings are
            grouped by category — open evidence at the cited line to verify.
          </p>

          <div className="hero__actions no-print">
            <label className="upload-btn">
              <span>{waiting ? 'Working…' : 'Upload dossier zip'}</span>
              <input
                ref={inputRef}
                type="file"
                accept=".zip,application/zip"
                disabled={waiting}
                onChange={(e) => void onFile(e.target.files?.[0])}
              />
            </label>
            {findings.length > 0 && (
              <div className="export-actions">
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => exportFindingsPdf(findings, jobId, 'summary')}
                >
                  Export summary PDF
                </button>
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => exportFindingsPdf(findings, jobId, 'detailed')}
                >
                  Export detailed PDF
                </button>
              </div>
            )}
          </div>

          {phase === 'error' && message && (
            <p className="hero__error" role="alert">
              {message}
            </p>
          )}
          {phase === 'done' && (
            <p className="hero__done" role="status">
              Analysis complete
              {count !== null
                ? ` — ${count} finding${count === 1 ? '' : 's'}`
                : ''}
              {jobId ? ` · job ${jobId}` : ''}
            </p>
          )}
        </section>

        {waiting && (
          <AnalysisProgress
            phase={phase === 'uploading' ? 'uploading' : 'streaming'}
            jobStatus={jobStatus}
            findingCount={findings.length}
          />
        )}

        {(findings.length > 0 || phase === 'done') && (
          <section className="feed" aria-label="Findings">
            <div className="feed__toolbar no-print">
              <h2 className="feed__title">Findings</h2>
              <div className="filters" role="tablist" aria-label="Confidence filter">
                <button
                  type="button"
                  role="tab"
                  aria-selected={filter === 'all'}
                  className={filter === 'all' ? 'filter filter--active' : 'filter'}
                  onClick={() => setFilter('all')}
                >
                  All <span>{bandScoped.length}</span>
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={filter === 'high'}
                  className={
                    filter === 'high' ? 'filter filter--active' : 'filter'
                  }
                  onClick={() => setFilter('high')}
                >
                  High confidence <span>{highCount}</span>
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={filter === 'review'}
                  className={
                    filter === 'review' ? 'filter filter--active' : 'filter'
                  }
                  onClick={() => setFilter('review')}
                >
                  Needs verification <span>{reviewCount}</span>
                </button>
              </div>
            </div>

            {categoryCounts.length > 0 && (
              <div className="category-filters no-print" aria-label="Category filter">
                <button
                  type="button"
                  className={
                    category === 'all'
                      ? 'filter filter--active'
                      : 'filter'
                  }
                  onClick={() => setCategory('all')}
                >
                  All groups <span>{categoryScoped.length}</span>
                </button>
                {categoryCounts.map(([cat, n]) => (
                  <button
                    key={cat}
                    type="button"
                    className={
                      category === cat ? 'filter filter--active' : 'filter'
                    }
                    onClick={() => setCategory(cat)}
                  >
                    {categoryLabel(cat)} <span>{n}</span>
                  </button>
                ))}
              </div>
            )}

            {(filter !== 'all' || category !== 'all') && (
              <p className="filter-combo no-print" role="status">
                Showing <strong>{combined.length}</strong> of {findings.length}
                {filter !== 'all' && (
                  <>
                    {' '}
                    · band:{' '}
                    <strong>
                      {filter === 'high' ? 'high confidence' : 'needs verification'}
                    </strong>
                  </>
                )}
                {category !== 'all' && (
                  <>
                    {' '}
                    · group: <strong>{categoryLabel(category)}</strong>
                  </>
                )}
                <button
                  type="button"
                  className="filter-combo__clear"
                  onClick={() => {
                    setFilter('all')
                    setCategory('all')
                  }}
                >
                  Clear filters
                </button>
              </p>
            )}

            <div className="print-only print-detailed">
              <div className="print-cover">
                <h1>Auditor — detailed findings report</h1>
                <p>
                  Job {jobId ?? '—'} · {findings.length} findings · exported{' '}
                  {new Date().toLocaleString()}
                </p>
              </div>
            </div>

            <div className="print-only print-summary">
              <SummaryReportView report={summary} jobId={jobId} />
            </div>

            <div className="screen-findings">
              <FindingsList
                findings={findings}
                filter={filter}
                category={category}
                busyId={busyId}
                onVerify={(id) => void onVerify(id)}
                onDismiss={(id) => void onDismiss(id)}
                onOpenSource={(c) => void onOpenSource(c)}
              />
            </div>
          </section>
        )}

        {phase === 'idle' && findings.length === 0 && (
          <section className="empty-hint no-print">
            <p>
              Priority patterns: segregation of duties, unsupported payments,
              misclassification, cut-off, and threshold structuring. Legal-form
              near-duplicates (AG vs GmbH) are suppressed — auditors focus on
              risk, not master-data hygiene.
            </p>
          </section>
        )}
      </main>

      {showSource && (
        <SourceViewer
          data={source}
          loading={sourceLoading}
          error={sourceError}
          onClose={() => {
            setSource(null)
            setSourceError(null)
            setSourceLoading(false)
          }}
        />
      )}
    </div>
  )
}
