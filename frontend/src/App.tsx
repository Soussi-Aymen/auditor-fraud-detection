import { useEffect, useRef, useState } from 'react'
import {
  insertFindingSorted,
  setVerdict,
  subscribeAnalyze,
  uploadZip,
} from './api'
import { AnalysisProgress } from './components/AnalysisProgress'
import {
  FindingsList,
  type BandFilter,
} from './components/FindingsList'
import { exportFindingsPdf } from './exportPdf'
import type { Finding, JobStatus } from './types'
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

  const waiting = phase === 'uploading' || phase === 'streaming'
  const highCount = findings.filter((f) => f.band === 'high').length
  const reviewCount = findings.filter(
    (f) => f.band === 'needs_human_verification',
  ).length

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
            Upload a GDPdU zip. Deterministic detectors stream ranked findings
            with evidence — high-confidence fraud first, mid-band items flagged
            for human verification.
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
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => exportFindingsPdf(findings, jobId)}
              >
                Export PDF
              </button>
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
                  All <span>{findings.length}</span>
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

            <div className="print-only print-cover">
              <h1>Auditor — findings report</h1>
              <p>
                Job {jobId ?? '—'} · {findings.length} findings · exported{' '}
                {new Date().toLocaleString()}
              </p>
            </div>

            <FindingsList
              findings={findings}
              filter={filter}
              busyId={busyId}
              onVerify={(id) => void onVerify(id)}
              onDismiss={(id) => void onDismiss(id)}
            />
          </section>
        )}

        {phase === 'idle' && findings.length === 0 && (
          <section className="empty-hint no-print">
            <p>
              Detectors stay general (SoD, misclassification, cutoff, threshold
              structuring, near-duplicates, unsupported). Skip-band findings stay
              hidden. Mid-band items need your judgment.
            </p>
          </section>
        )}
      </main>
    </div>
  )
}
