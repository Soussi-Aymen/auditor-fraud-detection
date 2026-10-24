export type ConfidenceBand = "skip" | "needs_human_verification" | "high";

export type FindingStatus = "open" | "verified" | "dismissed";

export type JobStatus = "queued" | "parsing" | "ready" | "error";

export interface Citation {
  n: number;
  file: string;
  locator: string;
  quote: string;
  source_path?: string | null;
  line?: number | null;
  row?: number | null;
  detail?: string | null;
}

export interface Finding {
  id: string;
  title: string;
  summary: string;
  confidence: number;
  band: ConfidenceBand;
  categories: string[];
  citations: Citation[];
  status: FindingStatus;
}

export interface UploadResponse {
  job_id: string;
}

export interface VerdictResponse {
  job_id: string;
  finding_id: string;
  status: FindingStatus;
}

export type StreamStatus = {
  job_id: string;
  status: JobStatus;
  tables?: number;
};

export type StreamError = {
  job_id: string;
  message: string;
};

export type StreamDone = {
  job_id: string;
  count: number;
};

export type SourceLine = {
  n: number;
  text: string;
};

export type SourceView = {
  path: string;
  kind: "text" | "document_extract" | "binary_note" | string;
  lines: SourceLine[];
  focus_line: number | null;
  focus_end: number | null;
  note: string | null;
  quote: string | null;
};

/** Human labels for detector category groups (auditor language). */
export const CATEGORY_LABELS: Record<string, string> = {
  segregation_of_duties: "Segregation of duties",
  misclassification: "Misclassification",
  cutoff_timing: "Cut-off / timing",
  threshold_structuring: "Threshold structuring",
  near_duplicate_entities: "Near-duplicate entities",
  unsupported_transaction: "Unsupported transactions",
};

export function categoryLabel(cat: string): string {
  return CATEGORY_LABELS[cat] ?? cat.replaceAll("_", " ");
}
