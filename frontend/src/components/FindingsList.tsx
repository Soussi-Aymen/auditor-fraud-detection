import { FindingCard } from './FindingCard'
import type { Citation, Finding } from '../types'
import { categoryLabel } from '../types'

export type BandFilter = 'all' | 'high' | 'review'

type Props = {
  findings: Finding[]
  filter: BandFilter
  category: string | 'all'
  busyId: string | null
  onVerify: (id: string) => void
  onDismiss: (id: string) => void
  onOpenSource: (citation: Citation) => void
}

export function filterFindings(
  findings: Finding[],
  filter: BandFilter,
  category: string | 'all',
): Finding[] {
  let list = findings
  if (filter === 'high') {
    list = list.filter((f) => f.band === 'high')
  } else if (filter === 'review') {
    list = list.filter((f) => f.band === 'needs_human_verification')
  }
  if (category !== 'all') {
    list = list.filter((f) => f.categories.includes(category))
  }
  return list
}

export function FindingsList({
  findings,
  filter,
  category,
  busyId,
  onVerify,
  onDismiss,
  onOpenSource,
}: Props) {
  const visible = filterFindings(findings, filter, category)

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
        No findings in this filter — try another band or category.
      </p>
    )
  }

  // Group by primary category for auditor scan
  const groups = new Map<string, Finding[]>()
  for (const f of visible) {
    const key = f.categories[0] ?? 'other'
    const bucket = groups.get(key) ?? []
    bucket.push(f)
    groups.set(key, bucket)
  }

  return (
    <div className="findings-groups">
      {[...groups.entries()].map(([cat, items]) => (
        <section key={cat} className="findings-group" aria-label={categoryLabel(cat)}>
          <h3 className="findings-group__title">
            {categoryLabel(cat)}
            <span>{items.length}</span>
          </h3>
          <ol className="findings-list">
            {items.map((f) => (
              <li key={f.id} className="findings-list__item">
                <FindingCard
                  finding={f}
                  busy={busyId === f.id}
                  onVerify={onVerify}
                  onDismiss={onDismiss}
                  onOpenSource={onOpenSource}
                />
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  )
}
