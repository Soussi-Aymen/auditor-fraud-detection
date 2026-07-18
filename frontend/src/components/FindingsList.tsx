import { FindingCard } from './FindingCard'
import type { Finding } from '../types'

export type BandFilter = 'all' | 'high' | 'review'

type Props = {
  findings: Finding[]
  filter: BandFilter
  busyId: string | null
  onVerify: (id: string) => void
  onDismiss: (id: string) => void
}

export function filterFindings(
  findings: Finding[],
  filter: BandFilter,
): Finding[] {
  if (filter === 'high') {
    return findings.filter((f) => f.band === 'high')
  }
  if (filter === 'review') {
    return findings.filter((f) => f.band === 'needs_human_verification')
  }
  return findings
}

export function FindingsList({
  findings,
  filter,
  busyId,
  onVerify,
  onDismiss,
}: Props) {
  const visible = filterFindings(findings, filter)

  if (findings.length === 0) {
    return (
      <p className="findings-empty">
        Upload a GDPdU zip to stream ranked fraud findings.
      </p>
    )
  }

  if (visible.length === 0) {
    return (
      <p className="findings-empty">
        No findings in this filter — try another band.
      </p>
    )
  }

  return (
    <ol className="findings-list">
      {visible.map((f) => (
        <li key={f.id} className="findings-list__item">
          <FindingCard
            finding={f}
            busy={busyId === f.id}
            onVerify={onVerify}
            onDismiss={onDismiss}
          />
        </li>
      ))}
    </ol>
  )
}
