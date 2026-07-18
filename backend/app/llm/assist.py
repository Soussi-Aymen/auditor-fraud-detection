"""Narration, quote trim, and policy extract with offline template fallbacks."""

from __future__ import annotations

import json
import re
from typing import Any

from app.llm.client import model_fast, model_primary, openai_enabled, structured_parse
from app.llm.schemas import NarrationOut, PolicyExtractOut, QuoteTrimOut
from app.parsing.documents import DocumentChunk
from app.schemas import Citation, Finding

# Policy docs tend to live under Begleitdokumente; prefer planning/materiality-ish names.
_POLICY_NAME_HINTS = (
    "pruefung",
    "prüfung",
    "material",
    "wesentlich",
    "jet",
    "planung",
    "richtlinie",
    "policy",
)


def narrate_finding(finding: Finding) -> Finding:
    """Rewrite title/summary only. Confidence, band, citations, categories unchanged."""
    if not openai_enabled():
        return _fallback_narrate(finding)

    cite_lines = [
        f"[{c.n}] file={c.file} locator={c.locator} quote={c.quote}"
        for c in finding.citations
    ]
    user = (
        "Rewrite this detector finding as an audit headline + short evidence story.\n"
        "Use only the facts below. Do not add new entities, amounts, or citations.\n"
        "Do not mention confidence scores.\n\n"
        f"categories: {', '.join(finding.categories)}\n"
        f"detector_title: {finding.title}\n"
        f"detector_summary: {finding.summary}\n"
        "citations:\n"
        + ("\n".join(cite_lines) if cite_lines else "(none)")
    )
    try:
        out = structured_parse(
            model=model_primary(),
            user_content=user,
            response_model=NarrationOut,
        )
        title = (out.title or "").strip() or finding.title
        summary = (out.summary or "").strip() or finding.summary
        return finding.model_copy(update={"title": title, "summary": summary})
    except Exception:  # noqa: BLE001 — offline-quality fallback on any LLM failure
        return _fallback_narrate(finding)


def trim_citation_quotes(citations: list[Citation], *, max_chars: int = 160) -> list[Citation]:
    """Shorten citation quotes. Locator/file unchanged; never invent new quote text."""
    if not citations:
        return citations

    if not openai_enabled():
        return [_hard_trim(c, max_chars) for c in citations]

    payload = [
        {"n": c.n, "file": c.file, "locator": c.locator, "quote": c.quote}
        for c in citations
    ]
    user = (
        "Trim each citation quote to the most relevant span for an auditor.\n"
        f"Max ~{max_chars} characters per quote.\n"
        "Each output quote MUST be a contiguous substring of that citation's input quote "
        "(whitespace normalization allowed). Same order, same count.\n\n"
        f"citations_json:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        out = structured_parse(
            model=model_fast(),
            user_content=user,
            response_model=QuoteTrimOut,
        )
        if len(out.quotes) != len(citations):
            return [_hard_trim(c, max_chars) for c in citations]
        trimmed: list[Citation] = []
        for c, q in zip(citations, out.quotes, strict=True):
            quote = _safe_substring_quote(c.quote, q, max_chars)
            trimmed.append(c.model_copy(update={"quote": quote}))
        return trimmed
    except Exception:  # noqa: BLE001
        return [_hard_trim(c, max_chars) for c in citations]


def extract_policy_overrides(chunks: list[DocumentChunk]) -> dict[str, Any]:
    """
    One-shot policy/threshold extract from document text cache.

    Returns a partial detector-config overlay (may be empty). No-op without API key.
    """
    if not openai_enabled() or not chunks:
        return {}

    policy_text = _select_policy_text(chunks)
    if not policy_text.strip():
        return {}

    user = (
        "Extract numeric approval/materiality thresholds (EUR) and fiscal year-end "
        "from this audit/policy accompanying text if present.\n"
        "If a value is not clearly stated, omit it (empty list / null).\n"
        "Do not invent thresholds.\n\n"
        f"policy_text:\n{policy_text[:12000]}"
    )
    try:
        out = structured_parse(
            model=model_fast(),
            user_content=user,
            response_model=PolicyExtractOut,
        )
    except Exception:  # noqa: BLE001
        return {}

    overlay: dict[str, Any] = {}
    thresholds = [float(x) for x in out.thresholds_eur if float(x) > 0]
    # Dedupe preserving order
    seen: set[float] = set()
    uniq: list[float] = []
    for t in thresholds:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    if uniq:
        overlay.setdefault("threshold_structuring", {})["thresholds_eur"] = uniq

    month = out.fiscal_year_end_month
    day = out.fiscal_year_end_day
    if month is not None and 1 <= int(month) <= 12:
        overlay.setdefault("cutoff_timing", {})["fiscal_year_end_month"] = int(month)
    if day is not None and 1 <= int(day) <= 31:
        overlay.setdefault("cutoff_timing", {})["fiscal_year_end_day"] = int(day)
    return overlay


def _fallback_narrate(finding: Finding) -> Finding:
    """Template polish without calling OpenAI."""
    cats = ", ".join(finding.categories) if finding.categories else "control"
    title = finding.title.strip()
    if not title.lower().startswith(("possible", "potential", "review")):
        title = f"Review: {title}"
    cite_bits = []
    for c in finding.citations[:3]:
        cite_bits.append(f"[{c.n}] {c.file} ({c.locator})")
    evidence = "; ".join(cite_bits) if cite_bits else "see detector citations"
    summary = (
        f"{finding.summary.strip()} "
        f"Category signal: {cats}. Key sources: {evidence}."
    )
    # Keep summary readable
    summary = re.sub(r"\s+", " ", summary).strip()
    return finding.model_copy(update={"title": title, "summary": summary})


def _hard_trim(citation: Citation, max_chars: int) -> Citation:
    quote = citation.quote.strip().replace("\n", " ")
    if len(quote) > max_chars:
        quote = quote[: max_chars - 1] + "…"
    return citation.model_copy(update={"quote": quote})


def _safe_substring_quote(source: str, candidate: str, max_chars: int) -> str:
    """Accept LLM trim only when it is (approx) a substring of the source quote."""
    src_norm = re.sub(r"\s+", " ", source.strip())
    cand_norm = re.sub(r"\s+", " ", (candidate or "").strip().replace("\n", " "))
    if not cand_norm:
        extracted = src_norm
    elif cand_norm.lower() in src_norm.lower():
        idx = src_norm.lower().find(cand_norm.lower())
        extracted = src_norm[idx : idx + len(cand_norm)] if idx >= 0 else cand_norm
    else:
        extracted = src_norm

    if len(extracted) > max_chars:
        extracted = extracted[: max_chars - 1] + "…"
    return extracted


def _select_policy_text(chunks: list[DocumentChunk]) -> str:
    preferred = [
        c
        for c in chunks
        if any(h in c.source_path.lower() for h in _POLICY_NAME_HINTS)
        and c.source_path.lower().endswith((".docx", ".pdf"))
    ]
    pool = preferred or [
        c for c in chunks if c.source_path.lower().endswith((".docx", ".pdf"))
    ]
    parts: list[str] = []
    total = 0
    for c in pool:
        block = f"--- {c.source_path} {c.locator} ---\n{c.text.strip()}\n"
        if total + len(block) > 12000:
            break
        parts.append(block)
        total += len(block)
    return "\n".join(parts)
