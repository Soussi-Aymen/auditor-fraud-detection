export type ConfidenceBand = 'skip' | 'needs_human_verification' | 'high'

export type FindingStatus = 'open' | 'verified' | 'dismissed'

export type JobStatus = 'queued' | 'parsing' | 'ready' | 'error'

export interface Citation {
  n: number
  file: string
  locator: string
  quote: string
}

export interface Finding {
  id: string
  title: string
  summary: string
  confidence: number
  band: ConfidenceBand
  categories: string[]
  citations: Citation[]
  status: FindingStatus
}

export interface UploadResponse {
  job_id: string
}

export interface VerdictResponse {
  job_id: string
  finding_id: string
  status: FindingStatus
}

export type StreamStatus = {
  job_id: string
  status: JobStatus
  tables?: number
}

export type StreamError = {
  job_id: string
  message: string
}

export type StreamDone = {
  job_id: string
  count: number
}
