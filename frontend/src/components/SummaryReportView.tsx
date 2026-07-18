import type { SummaryReport } from '../summaryReport'

type Props = {
  report: SummaryReport
  jobId: string | null
}

export function SummaryReportView({ report, jobId }: Props) {
  return (
    <div className="summary-report">
      <header className="summary-report__cover">
        <h1>Auditor — summary report</h1>
        <p>
          Job {jobId ?? '—'} · {report.total} findings ·{' '}
          {report.highCount} high · {report.reviewCount} need verification ·{' '}
          exported {new Date().toLocaleString()}
        </p>
        <p className="summary-report__note">
          Condensed view for partners / planning. Open the detailed report for
          full citations and evidence.
        </p>
      </header>

      <section className="summary-report__section">
        <h2>Status</h2>
        <ul className="summary-report__stats">
          <li>
            Open <strong>{report.open}</strong>
          </li>
          <li>
            Verified <strong>{report.verified}</strong>
          </li>
          <li>
            Dismissed <strong>{report.dismissed}</strong>
          </li>
        </ul>
      </section>

      {report.commonFlags.length > 0 && (
        <section className="summary-report__section">
          <h2>Common issues flagged</h2>
          <ul className="summary-report__flags">
            {report.commonFlags.map((flag) => (
              <li key={flag}>{flag}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="summary-report__section">
        <h2>Priority focus</h2>
        <ol className="summary-report__priority">
          {report.priority.map((f) => (
            <li key={f.id}>
              <span className="summary-report__pct">
                {Math.round(f.confidence)}%
              </span>
              <span className="summary-report__band">
                {f.band === 'high' ? 'High' : 'Verify'}
              </span>
              <div>
                <strong>{f.title}</strong>
                <p>{f.summary.length > 180 ? `${f.summary.slice(0, 177)}…` : f.summary}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="summary-report__section">
        <h2>Issues by category</h2>
        {report.categories.map((dig) => (
          <article key={dig.category} className="summary-report__cat">
            <h3>
              {dig.label}{' '}
              <span>
                {dig.count} · max {Math.round(dig.maxConfidence)}%
                {dig.highCount > 0 ? ` · ${dig.highCount} high` : ''}
              </span>
            </h3>
            <p className="summary-report__pattern">{dig.pattern}</p>
            {dig.examples.length > 0 && (
              <ul>
                {dig.examples.map((ex) => (
                  <li key={ex}>{ex}</li>
                ))}
              </ul>
            )}
          </article>
        ))}
      </section>
    </div>
  )
}
