import { useEffect, useState } from 'react'
import type { JobStatus } from '../types'

/** Initial ETA while parse + detect (+ optional LLM) run. */
const INITIAL_ETA_SEC = 20

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

export function AnalysisProgress({ phase, jobStatus, findingCount }: Props) {
  const [eta, setEta] = useState(INITIAL_ETA_SEC)

  useEffect(() => {
    setEta(INITIAL_ETA_SEC)
  }, [phase])

  useEffect(() => {
    if (phase !== 'uploading' && phase !== 'streaming') return
    const id = window.setInterval(() => {
      setEta((s) => {
        // Keep a soft floor so the clock never reads “done” while still waiting
        if (s <= 3) return 3
        const step = findingCount > 0 ? 2 : 1
        return Math.max(3, s - step)
      })
    }, 1000)
    return () => window.clearInterval(id)
  }, [phase, findingCount])

  const mins = Math.floor(eta / 60)
  const secs = eta % 60
  const etaLabel =
    mins > 0 ? `~${mins}m ${secs.toString().padStart(2, '0')}s` : `~${secs}s`

  return (
    <div className="progress" role="status" aria-live="polite">
      <div className="progress__spinner" aria-hidden="true" />
      <div className="progress__copy">
        <p className="progress__label">{labelFor(phase, jobStatus)}</p>
        <p className="progress__eta">
          Estimated time remaining <strong>{etaLabel}</strong>
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
