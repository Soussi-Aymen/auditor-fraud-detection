import { useEffect, useRef } from "react";
import type { SourceView } from "../types";

type Props = {
  data: SourceView | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
};

export function SourceViewer({ data, loading, error, onClose }: Props) {
  const focusRef = useRef<HTMLLIElement | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (focusRef.current) {
      focusRef.current.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [data?.path, data?.focus_line]);

  return (
    <div className="source-modal" role="dialog" aria-modal="true" aria-label="Source file">
      <button
        type="button"
        className="source-modal__backdrop"
        onClick={onClose}
        aria-label="Close"
      />
      <div className="source-modal__panel">
        <header className="source-modal__header">
          <div>
            <p className="source-modal__eyebrow">Source evidence</p>
            <h3 className="source-modal__title">{data?.path ?? "Opening…"}</h3>
          </div>
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Close
          </button>
        </header>

        {loading && <p className="source-modal__status">Loading file…</p>}
        {error && <p className="source-modal__error">{error}</p>}

        {data?.note && <p className="source-modal__note">{data.note}</p>}
        {data?.quote && <blockquote className="source-modal__quote">{data.quote}</blockquote>}

        {data && data.lines.length > 0 && (
          <ol className="source-lines">
            {data.lines.map((ln) => {
              const focused = data.focus_line != null && ln.n === data.focus_line;
              return (
                <li
                  key={ln.n}
                  ref={focused ? focusRef : undefined}
                  className={focused ? "source-line source-line--focus" : "source-line"}
                >
                  <span className="source-line__n">{ln.n}</span>
                  <code className="source-line__text">{ln.text || " "}</code>
                </li>
              );
            })}
          </ol>
        )}

        {data?.kind === "binary_note" && !data.lines.length && (
          <p className="source-modal__status">
            This file type cannot be rendered inline. Use the citation details above.
          </p>
        )}
      </div>
    </div>
  );
}
