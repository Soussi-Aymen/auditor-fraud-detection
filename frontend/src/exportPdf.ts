import type { Finding } from './types'

/** Open the browser print dialog — users choose “Save as PDF”. */
export function exportFindingsPdf(findings: Finding[], jobId: string | null) {
  const previous = document.title
  const stamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-')
  const n = findings.length
  document.title = `auditor-findings-${jobId ?? 'export'}-${n}items-${stamp}`
  document.body.dataset.pdfExport = '1'
  const cleanup = () => {
    document.title = previous
    delete document.body.dataset.pdfExport
    window.removeEventListener('afterprint', cleanup)
  }
  window.addEventListener('afterprint', cleanup)
  window.print()
}
