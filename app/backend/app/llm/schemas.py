"""Pydantic schemas for OpenAI Structured Outputs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NarrationOut(BaseModel):
    title: str = Field(description="Short audit-style headline (one line).")
    summary: str = Field(
        description="2–4 sentence evidence story grounded only in provided facts."
    )


class QuoteTrimOut(BaseModel):
    quotes: list[str] = Field(
        description=(
            "One trimmed quote per input citation, same order. "
            "Each quote must be a contiguous substring of that citation's source text."
        )
    )


class PolicyExtractOut(BaseModel):
    thresholds_eur: list[float] = Field(
        default_factory=list,
        description=(
            "Materiality / approval / structuring thresholds in EUR found in the policy text. "
            "Empty if none found."
        ),
    )
    fiscal_year_end_month: int | None = Field(
        default=None,
        description="Fiscal year-end month 1–12 if stated; else null.",
    )
    fiscal_year_end_day: int | None = Field(
        default=None,
        description="Fiscal year-end day 1–31 if stated; else null.",
    )
