import { useEffect, useState } from 'react'
import type { JobStatus } from '../types'

/** Default ETA for a full analysis run (upload + parse + detect + LLM). */
const DEFAULT_ETA_SEC = 60

type Props = {
  phase: 'uploading' | 'streaming'
  jobStatus: JobStatus | null
  findingCount: number
}

function labelFor(phase: Props['phase'], jobStatus: JobStatus | null): string {
  if (phase === 'uploading') return 'Uploading dossier…'
  if (jobStatus === 'queued') return 'Queued for analysis…'
  if (jobStatus === 'parsing') return 'Preprocessing documents & running detectors…'
  return 'Streaming ranked findings…'
}

function formatEta(seconds: number): string {
  const s = Math.max(1, Math.ceil(seconds))
  if (s >= 60) {
    const m = Math.floor(s / 60)
    const r = s % 60
    return r === 0 ? `~${m}m` : `~${m}m ${r.toString().padStart(2, '0')}s`
  }
  return `~${s}s`
}

export function AnalysisProgress({ phase, jobStatus, findingCount }: Props) {
  const [startedAt, setStartedAt] = useState(() => Date.now())
  const [now, setNow] = useState(() => Date.now())

  // One clock for the whole run (starts when upload/stream begins)
  useEffect(() => {
    if (phase === 'uploading') {
      setStartedAt(Date.now())
      setNow(Date.now())
    }
  }, [phase])

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(id)
  }, [phase])

  const elapsed = (now - startedAt) / 1000
  let remaining = Math.ceil(DEFAULT_ETA_SEC - elapsed)
  if (remaining < 1) {
    remaining = findingCount > 0 ? 1 : 2
  }

  return (
    <div className="progress" role="status" aria-live="polite">
      <div className="progress__spinner" aria-hidden="true" />
      <div className="progress__copy">
        <p className="progress__label">{labelFor(phase, jobStatus)}</p>
        <p className="progress__eta">
          Estimated time remaining <strong>{formatEta(remaining)}</strong>
        </p>
        {findingCount > 0 && (
          <p className="progress__partial">
            {findingCount} finding{findingCount === 1 ? '' : 's'} so far…
          </p>
        )}
      </div>
    </div>
  )
}
