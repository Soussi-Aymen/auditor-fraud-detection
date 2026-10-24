import type {
  Finding,
  SourceView,
  StreamDone,
  StreamError,
  StreamStatus,
  UploadResponse,
  VerdictResponse,
} from "./types";

export async function uploadZip(file: File): Promise<UploadResponse> {
  const body = new FormData();
  body.append("file", file);
  const res = await fetch("/api/upload", { method: "POST", body });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Upload failed (${res.status})`);
  }
  return (await res.json()) as UploadResponse;
}

export async function setVerdict(
  jobId: string,
  findingId: string,
  action: "verify" | "dismiss",
): Promise<VerdictResponse> {
  const res = await fetch(`/api/analyze/${jobId}/findings/${findingId}/${action}`, {
    method: "POST",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Verdict failed (${res.status})`);
  }
  return (await res.json()) as VerdictResponse;
}

export async function fetchSource(
  jobId: string,
  opts: {
    path: string;
    line?: number | null;
    locator?: string;
    quote?: string;
  },
): Promise<SourceView> {
  const q = new URLSearchParams();
  q.set("path", opts.path);
  if (opts.line != null) q.set("line", String(opts.line));
  if (opts.locator) q.set("locator", opts.locator);
  if (opts.quote) q.set("quote", opts.quote);
  const res = await fetch(`/api/analyze/${jobId}/source?${q.toString()}`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Source open failed (${res.status})`);
  }
  return (await res.json()) as SourceView;
}

export type AnalyzeHandlers = {
  onStatus?: (status: StreamStatus) => void;
  onFinding?: (finding: Finding) => void;
  onDone?: (done: StreamDone) => void;
  onError?: (error: StreamError | Error) => void;
};

/** Subscribe to analysis SSE. Returns an unsubscribe function. */
export function subscribeAnalyze(jobId: string, handlers: AnalyzeHandlers): () => void {
  const es = new EventSource(`/api/analyze/${jobId}/stream`);
  let intentionalClose = false;

  const close = () => {
    intentionalClose = true;
    es.close();
  };

  const parse = <T>(raw: MessageEvent): T | null => {
    try {
      return JSON.parse(raw.data as string) as T;
    } catch {
      handlers.onError?.(new Error("Invalid SSE payload"));
      return null;
    }
  };

  es.addEventListener("status", (ev) => {
    const data = parse<StreamStatus>(ev as MessageEvent);
    if (data) handlers.onStatus?.(data);
  });

  es.addEventListener("finding", (ev) => {
    const data = parse<Finding>(ev as MessageEvent);
    if (data) handlers.onFinding?.(data);
  });

  es.addEventListener("done", (ev) => {
    const data = parse<StreamDone>(ev as MessageEvent);
    if (data) handlers.onDone?.(data);
    close();
  });

  es.addEventListener("error", (ev) => {
    // Named server "error" events are MessageEvents; connection failures are not.
    if (ev instanceof MessageEvent && typeof ev.data === "string" && ev.data) {
      const data = parse<StreamError>(ev);
      if (data) handlers.onError?.(data);
      close();
      return;
    }
    if (!intentionalClose && es.readyState === EventSource.CLOSED) {
      handlers.onError?.(new Error("SSE connection closed"));
    }
  });

  return () => close();
}

/** Insert finding sorted by confidence desc; skip-band never shown. */
export function insertFindingSorted(list: Finding[], finding: Finding): Finding[] {
  if (finding.band === "skip") return list;
  if (list.some((f) => f.id === finding.id)) return list;
  const next = [...list, finding];
  next.sort((a, b) => b.confidence - a.confidence);
  return next;
}
