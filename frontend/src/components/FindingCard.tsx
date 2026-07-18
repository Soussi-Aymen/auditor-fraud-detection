import { useState } from 'react'
import type { Citation, Finding } from '../types'

const BAND_LABEL: Record<Finding['band'], string> = {
  skip: 'Skip',
  needs_human_verification: 'Needs human verification',
  high: 'High confidence',
}

type Props = {
  finding: Finding
  busy: boolean
  onVerify: (id: string) => void
  onDismiss: (id: string) => void
}

export function FindingCard({ finding, busy, onVerify, onDismiss }: Props) {
  const [openCitation, setOpenCitation] = useState<number | null>(null)
  const review = finding.band === 'needs_human_verification'
  const closed = finding.status !== 'open'

  const toggleCitation = (n: number) => {
    setOpenCitation((cur) => (cur === n ? null : n))
  }

  const active: Citation | undefined =
    openCitation === null
      ? undefined
      : finding.citations.find((c) => c.n === openCitation)

  return (
    <article
      className={[
        'finding',
        review ? 'finding--review' : 'finding--high',
        closed ? 'finding--closed' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      style={{ viewTransitionName: `finding-${finding.id}` }}
    >
      <header className="finding__header">
        <div className="finding__meta">
          <span className="finding__confidence">
            {Math.round(finding.confidence)}%
          </span>
          <span
            className={
              review ? 'finding__badge finding__badge--review' : 'finding__badge'
            }
          >
            {BAND_LABEL[finding.band]}
          </span>
          {finding.status !== 'open' && (
            <span className="finding__status">{finding.status}</span>
          )}
        </div>
        <h2 className="finding__title">{finding.title}</h2>
      </header>

      <p className="finding__summary">{finding.summary}</p>

      {finding.categories.length > 0 && (
        <p className="finding__categories">
          {finding.categories.join(' · ')}
        </p>
      )}

      {finding.citations.length > 0 && (
        <div className="finding__citations">
          <span className="finding__citations-label">Evidence</span>
          <div className="finding__citation-refs">
            {finding.citations.map((c) => (
              <button
                key={c.n}
                type="button"
                className={
                  openCitation === c.n
                    ? 'citation-ref citation-ref--open'
                    : 'citation-ref'
                }
                onClick={() => toggleCitation(c.n)}
                aria-expanded={openCitation === c.n}
              >
                [{c.n}]
              </button>
            ))}
          </div>
          {active && (
            <div className="citation-detail">
              <div className="citation-detail__file">
                <strong>{active.file}</strong>
                <span>{active.locator}</span>
              </div>
              <blockquote className="citation-detail__quote">
                {active.quote}
              </blockquote>
            </div>
          )}
        </div>
      )}

      {finding.status === 'open' && (
        <div className="finding__actions no-print">
          <button
            type="button"
            className="btn btn--verify"
            disabled={busy}
            onClick={() => onVerify(finding.id)}
          >
            Verify
          </button>
          <button
            type="button"
            className="btn btn--dismiss"
            disabled={busy}
            onClick={() => onDismiss(finding.id)}
          >
            Dismiss
          </button>
        </div>
      )}
    </article>
  )
}
