import type { Finding } from './types'
import type { ReportMode } from './summaryReport'

/** Open the browser print dialog — users choose “Save as PDF”. */
export function exportFindingsPdf(
  findings: Finding[],
  jobId: string | null,
  mode: ReportMode = 'detailed',
) {
  const previous = document.title
  const stamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-')
  const n = findings.length
  const prefix = mode === 'summary' ? 'auditor-summary' : 'auditor-detailed'
  document.title = `${prefix}-${jobId ?? 'export'}-${n}items-${stamp}`
  document.body.dataset.pdfExport = '1'
  document.body.dataset.pdfMode = mode
  const cleanup = () => {
    document.title = previous
    delete document.body.dataset.pdfExport
    delete document.body.dataset.pdfMode
    window.removeEventListener('afterprint', cleanup)
  }
  window.addEventListener('afterprint', cleanup)
  // Let React apply print-mode classes before the dialog opens
  window.setTimeout(() => window.print(), 50)
}
