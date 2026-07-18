import type { Finding } from './types'
import { categoryLabel } from './types'

export type ReportMode = 'summary' | 'detailed'

export type CategoryDigest = {
  category: string
  label: string
  count: number
  highCount: number
  reviewCount: number
  maxConfidence: number
  /** One short pattern line for auditors */
  pattern: string
  /** Up to 2 representative headlines */
  examples: string[]
}

export type SummaryReport = {
  total: number
  highCount: number
  reviewCount: number
  verified: number
  dismissed: number
  open: number
  /** Highest-priority items (high band first, then confidence) */
  priority: Finding[]
  categories: CategoryDigest[]
  /** Cross-cutting notes when patterns repeat */
  commonFlags: string[]
}

const MAX_PRIORITY = 5
const MAX_EXAMPLES = 2

function primaryCategory(f: Finding): string {
  return f.categories[0] ?? 'other'
}

function patternFor(category: string, items: Finding[]): string {
  const n = items.length
  switch (category) {
    case 'segregation_of_duties':
      return n > 1
        ? `${n} four-eyes / creator=approver breaches — treat as control failure cluster`
        : 'Creator and approver are the same user on a sensitive change'
    case 'unsupported_transaction':
      return n > 1
        ? `${n} payments/postings lack supporting goods receipt or contract evidence`
        : 'Material payment or new-vendor activity without adequate support'
    case 'misclassification':
      return n > 1
        ? `${n} repair/expense-like items booked as assets — profit/asset overstatement risk`
        : 'Expense-like cost may be capitalised incorrectly'
    case 'cutoff_timing':
      return n > 1
        ? `${n} post-period invoices for prior-period service — year-end cut-off cluster`
        : 'Service in prior period, booking in next period'
    case 'threshold_structuring':
      return n > 1
        ? `${n} near-threshold / split-payment signals — approval-limit avoidance risk`
        : 'Amount sits just under a configured approval threshold'
    case 'near_duplicate_entities':
      return n > 1
        ? `${n} lookalike / shared-address vendor master pairs`
        : 'Possible duplicate or lookalike vendor master data'
    default:
      return `${n} finding${n === 1 ? '' : 's'} in this group`
  }
}

/** Build an auditor-oriented summary from the ranked findings list. */
export function buildSummaryReport(findings: Finding[]): SummaryReport {
  const high = findings.filter((f) => f.band === 'high')
  const review = findings.filter((f) => f.band === 'needs_human_verification')
  const verified = findings.filter((f) => f.status === 'verified').length
  const dismissed = findings.filter((f) => f.status === 'dismissed').length
  const open = findings.filter((f) => f.status === 'open').length

  const byCat = new Map<string, Finding[]>()
  for (const f of findings) {
    const key = primaryCategory(f)
    const bucket = byCat.get(key) ?? []
    bucket.push(f)
    byCat.set(key, bucket)
  }

  const categories: CategoryDigest[] = [...byCat.entries()]
    .map(([category, items]) => {
      const sorted = [...items].sort((a, b) => b.confidence - a.confidence)
      return {
        category,
        label: categoryLabel(category),
        count: items.length,
        highCount: items.filter((f) => f.band === 'high').length,
        reviewCount: items.filter((f) => f.band === 'needs_human_verification')
          .length,
        maxConfidence: sorted[0]?.confidence ?? 0,
        pattern: patternFor(category, items),
        examples: sorted.slice(0, MAX_EXAMPLES).map((f) => f.title),
      }
    })
    .sort((a, b) => b.maxConfidence - a.maxConfidence || b.count - a.count)

  const priority = [...findings]
    .sort((a, b) => {
      const bandRank = (f: Finding) => (f.band === 'high' ? 0 : 1)
      return bandRank(a) - bandRank(b) || b.confidence - a.confidence
    })
    .slice(0, MAX_PRIORITY)

  const commonFlags: string[] = []
  for (const dig of categories) {
    if (dig.count >= 3) {
      commonFlags.push(
        `${dig.label}: ${dig.count} related hits (common issue — review as a theme, not only one-offs)`,
      )
    }
  }
  if (high.length === 0 && review.length > 0) {
    commonFlags.push(
      'No high-confidence findings — mid-band items need human verification before any allegation',
    )
  }
  if (high.length > 0) {
    commonFlags.unshift(
      `${high.length} high-confidence finding${high.length === 1 ? '' : 's'} should be reviewed first`,
    )
  }

  return {
    total: findings.length,
    highCount: high.length,
    reviewCount: review.length,
    verified,
    dismissed,
    open,
    priority,
    categories,
    commonFlags,
  }
}
