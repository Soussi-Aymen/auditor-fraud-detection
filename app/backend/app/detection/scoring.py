"""
Confidence scoring.

score = clamp(0..100, base + statistical_strength + stage2_delta + multi_category_boost)
band  = skip | needs_human_verification | high  (thresholds from detectors.yaml)
"""

from __future__ import annotations

from typing import Any

from app.schemas import ConfidenceBand, Finding


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def band_for_confidence(confidence: float, cfg: dict[str, Any]) -> ConfidenceBand:
    conf = cfg.get("confidence") or {}
    skip_below = float(conf.get("skip_below", 35))
    high_above = float(conf.get("high_above", 65))
    if confidence < skip_below:
        return ConfidenceBand.skip
    if confidence <= high_above:
        return ConfidenceBand.needs_human_verification
    return ConfidenceBand.high


def compute_confidence(
    *,
    base: float,
    statistical_strength: float,
    stage2_delta: float,
    multi_category_boost: float,
) -> float:
    return round(
        clamp(base + statistical_strength + stage2_delta + multi_category_boost),
        1,
    )


def filter_skip_band(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.band != ConfidenceBand.skip]
