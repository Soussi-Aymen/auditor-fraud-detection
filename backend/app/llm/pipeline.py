"""Wire LLM assist into the analysis pipeline (policy → detectors → narrate/quotes)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.config import load_detector_config
from app.llm.assist import extract_policy_overrides, narrate_finding, trim_citation_quotes
from app.parsing.documents import DocumentChunk
from app.schemas import Finding


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def policy_config_overrides(
    document_chunks: list[DocumentChunk],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return detector config with optional LLM policy overlays applied."""
    base = cfg if cfg is not None else load_detector_config()
    overlay = extract_policy_overrides(document_chunks)
    if not overlay:
        return base
    return _deep_merge(base, overlay)


def enrich_findings(findings: list[Finding], *, max_quote_chars: int = 160) -> list[Finding]:
    """
    Trim citation quotes (fast model) then narrate title/summary (primary).

    Does not change confidence, band, categories, or invent findings.
    """
    enriched: list[Finding] = []
    for finding in findings:
        citations = trim_citation_quotes(finding.citations, max_chars=max_quote_chars)
        updated = finding.model_copy(update={"citations": citations})
        enriched.append(narrate_finding(updated))
    return enriched
