"""Wire LLM assist into the analysis pipeline (policy → detectors → narrate/quotes)."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from typing import Any

from app.config import load_detector_config
from app.llm.assist import (
    _fallback_narrate,
    extract_policy_overrides,
    hard_trim_citations,
    narrate_finding,
    trim_citation_quotes,
)
from app.llm.client import openai_enabled
from app.parsing.documents import DocumentChunk
from app.schemas import Finding


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


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
    if not _env_bool("LLM_POLICY_EXTRACT", True):
        return base
    overlay = extract_policy_overrides(document_chunks)
    if not overlay:
        return base
    return _deep_merge(base, overlay)


def enrich_findings(findings: list[Finding], *, max_quote_chars: int = 160) -> list[Finding]:
    """
    Hard-trim quotes for all findings; optionally LLM-narrate the top-N by confidence.

    Speed knobs (env):
      LLM_NARRATE_MAX=8       — max findings to send to primary model (0 = template only)
      LLM_NARRATE_WORKERS=4   — parallel narrate workers
      LLM_TRIM_QUOTES=0       — if 1, also call fast model per finding for quote trim
    """
    if not findings:
        return []

    use_llm_trim = _env_bool("LLM_TRIM_QUOTES", False) and openai_enabled()
    prepared: list[Finding] = []
    for finding in findings:
        if use_llm_trim:
            citations = trim_citation_quotes(finding.citations, max_chars=max_quote_chars)
        else:
            citations = hard_trim_citations(finding.citations, max_chars=max_quote_chars)
        prepared.append(finding.model_copy(update={"citations": citations}))

    if not openai_enabled():
        return [_fallback_narrate(f) for f in prepared]

    narrate_max = max(0, _env_int("LLM_NARRATE_MAX", 8))
    if narrate_max == 0:
        return [_fallback_narrate(f) for f in prepared]

    # Narrate only the highest-confidence findings (auditor-first); rest stay template.
    ranked_idx = sorted(range(len(prepared)), key=lambda i: prepared[i].confidence, reverse=True)
    to_narrate = set(ranked_idx[:narrate_max])
    workers = max(1, min(_env_int("LLM_NARRATE_WORKERS", 4), len(to_narrate)))

    out: list[Finding] = [_fallback_narrate(f) for f in prepared]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(narrate_finding, prepared[i]): i for i in to_narrate}
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                out[i] = fut.result()
            except Exception:  # noqa: BLE001
                out[i] = _fallback_narrate(prepared[i])

    out.sort(key=lambda f: f.confidence, reverse=True)
    return out
