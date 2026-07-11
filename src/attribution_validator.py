"""
attribution_validator.py

Public-safe source-attribution validator for a zero-trust audit pipeline.

Purpose:
- Check whether each atomic claim's evidence quote can be traced to the
  declared source section.
- Calculate an attribution rate.
- Flag unmatched evidence, missing sections, and wrong-section matches.

This module does not decide clinical truth. It only checks traceability.

Gate logic:
- attribution_rate == 1.0 means all evidence quotes were traceable.
- attribution_rate < 1.0 should route to HUMAN_REVIEW in governance_gate.py.
"""

from __future__ import annotations

import re
import string
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# Text normalization
# =============================================================================

def normalize_text(text: Any) -> str:
    """
    Lowercase, remove punctuation, collapse whitespace.

    This makes matching more tolerant to spacing, punctuation, and casing.
    """
    text = str(text)

    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def exact_match(quote: str, source_text: str) -> bool:
    """
    Checks exact raw substring match.
    """
    return quote.strip() in source_text


def normalized_match(quote: str, source_text: str) -> bool:
    """
    Checks normalized substring match.
    """
    quote_norm = normalize_text(quote)
    source_norm = normalize_text(source_text)

    if not quote_norm:
        return False

    return quote_norm in source_norm


# =============================================================================
# Source section handling
# =============================================================================

def extract_prompt_sections(raw_prompt: str) -> Dict[str, str]:
    """
    Extracts bracketed prompt sections.

    Example supported format:

    [STRUCTURED_FIELDS]
    some text here

    [SOURCE_TEXT]
    more text here

    Returns:
        {
            "STRUCTURED_FIELDS": "some text here",
            "SOURCE_TEXT": "more text here"
        }
    """
    sections: Dict[str, str] = {}

    current_section: Optional[str] = None
    current_lines: List[str] = []

    for line in str(raw_prompt).splitlines():
        stripped = line.strip()

        section_match = re.match(r"^\[([A-Z0-9_ /-]+)\]$", stripped)

        if section_match:
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).strip()

            current_section = section_match.group(1).strip()
            current_lines = []

        else:
            if current_section is not None:
                current_lines.append(line)

    if current_section is not None:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


def flatten_value(value: Any) -> str:
    """
    Converts dict/list/scalar source content into searchable text.
    """
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        return "\n".join(f"{key}: {flatten_value(val)}" for key, val in value.items())

    if isinstance(value, list):
        return "\n".join(flatten_value(item) for item in value)

    return str(value)


def source_record_to_sections(source_record: Dict[str, Any]) -> Dict[str, str]:
    """
    Converts a source_record dictionary into section text.

    Example:
        {
            "STRUCTURED_FIELDS": {...},
            "SOURCE_TEXT": "...",
            "MISSINGNESS_NOTES": [...]
        }
    """
    return {
        str(key): flatten_value(value)
        for key, value in source_record.items()
    }


def get_declared_source_text(
    source_sections: Dict[str, str],
    source_field: str,
) -> Tuple[Optional[str], str]:
    """
    Returns the declared section name and text.

    Uses exact section match first. Then tries a normalized fallback.
    """
    if source_field in source_sections:
        return source_field, source_sections[source_field]

    source_field_norm = normalize_text(source_field)

    for section_name, section_text in source_sections.items():
        if normalize_text(section_name) == source_field_norm:
            return section_name, section_text

    return None, ""


def find_match_anywhere(
    quote: str,
    source_sections: Dict[str, str],
) -> Optional[str]:
    """
    Returns the first section name where quote can be found.
    """
    for section_name, section_text in source_sections.items():
        if exact_match(quote, section_text) or normalized_match(quote, section_text):
            return section_name

    return None


# =============================================================================
# Claim-level attribution validation
# =============================================================================

def validate_claim_attribution(
    claim: Dict[str, Any],
    source_sections: Dict[str, str],
) -> Dict[str, Any]:
    """
    Validates attribution for one atomic claim.

    Expected claim fields:
    - claim_id
    - claim_text
    - source_field
    - evidence_quote

    Also supports evidence_snippet as a fallback name.
    """
    claim_id = claim.get("claim_id", "UNKNOWN_CLAIM")
    claim_text = claim.get("claim_text", claim.get("claim", ""))
    source_field = claim.get("source_field", "")
    evidence_quote = claim.get("evidence_quote", claim.get("evidence_snippet", ""))

    evidence_quote = str(evidence_quote).strip()

    declared_section_name, declared_section_text = get_declared_source_text(
        source_sections,
        str(source_field),
    )

    exact_declared_match = False
    normalized_declared_match = False
    matched_elsewhere_section = None

    if not evidence_quote:
        trace_status = "EMPTY_EVIDENCE"

    elif declared_section_name is None:
        matched_elsewhere_section = find_match_anywhere(evidence_quote, source_sections)

        if matched_elsewhere_section:
            trace_status = "INVALID_SOURCE_FIELD_BUT_QUOTE_FOUND_ELSEWHERE"
        else:
            trace_status = "MISSING_DECLARED_SECTION"

    else:
        exact_declared_match = exact_match(evidence_quote, declared_section_text)
        normalized_declared_match = normalized_match(evidence_quote, declared_section_text)

        if exact_declared_match:
            trace_status = "EXACT_DECLARED_MATCH"

        elif normalized_declared_match:
            trace_status = "NORMALIZED_DECLARED_MATCH"

        else:
            matched_elsewhere_section = find_match_anywhere(evidence_quote, source_sections)

            if matched_elsewhere_section:
                trace_status = "WRONG_SECTION_MATCH"
            else:
                trace_status = "UNMATCHED_EVIDENCE"

    attributed = trace_status in {
        "EXACT_DECLARED_MATCH",
        "NORMALIZED_DECLARED_MATCH",
    }

    return {
        "claim_id": claim_id,
        "claim_text": claim_text,
        "source_field": source_field,
        "declared_section_found": declared_section_name is not None,
        "matched_elsewhere_section": matched_elsewhere_section,
        "exact_declared_match": exact_declared_match,
        "normalized_declared_match": normalized_declared_match,
        "trace_status": trace_status,
        "attributed": attributed,
    }


def validate_claims_for_artifact(
    summary_artifact: Dict[str, Any],
    source_sections: Dict[str, str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Validates all atomic claims in a generated summary artifact.

    Returns:
        claim_rows:
            One row per claim.

        summary:
            Aggregate attribution metrics.
    """
    claim_rows: List[Dict[str, Any]] = []

    atomic_claims = summary_artifact.get("atomic_claims", [])

    if not isinstance(atomic_claims, list):
        atomic_claims = []

    for claim in atomic_claims:
        if isinstance(claim, dict):
            claim_rows.append(
                validate_claim_attribution(claim, source_sections)
            )

    total_claims = len(claim_rows)
    attributed_claims = sum(row["attributed"] for row in claim_rows)

    exact_declared_matches = sum(row["exact_declared_match"] for row in claim_rows)
    normalized_declared_matches = sum(row["normalized_declared_match"] for row in claim_rows)

    unmatched_claim_ids = [
        row["claim_id"]
        for row in claim_rows
        if row["trace_status"] in {"UNMATCHED_EVIDENCE", "EMPTY_EVIDENCE"}
    ]

    wrong_section_claim_ids = [
        row["claim_id"]
        for row in claim_rows
        if row["trace_status"] == "WRONG_SECTION_MATCH"
    ]

    missing_declared_section_claim_ids = [
        row["claim_id"]
        for row in claim_rows
        if row["trace_status"] == "MISSING_DECLARED_SECTION"
    ]

    invalid_source_field_claim_ids = [
        row["claim_id"]
        for row in claim_rows
        if row["trace_status"] == "INVALID_SOURCE_FIELD_BUT_QUOTE_FOUND_ELSEWHERE"
    ]

    if total_claims == 0:
        attribution_rate = 0.0
    else:
        attribution_rate = attributed_claims / total_claims

    summary = {
        "total_claims": total_claims,
        "attributed_claims": attributed_claims,
        "atomic_claim_attribution_rate": attribution_rate,
        "exact_declared_match_count": exact_declared_matches,
        "normalized_declared_match_count": normalized_declared_matches,
        "unmatched_claim_ids": unmatched_claim_ids,
        "wrong_section_claim_ids": wrong_section_claim_ids,
        "missing_declared_section_claim_ids": missing_declared_section_claim_ids,
        "invalid_source_field_claim_ids": invalid_source_field_claim_ids,
    }

    return claim_rows, summary


# =============================================================================
# Public wrapper
# =============================================================================

def validate_source_attribution(
    summary_artifact: Dict[str, Any],
    *,
    source_record: Optional[Dict[str, Any]] = None,
    raw_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Public wrapper for attribution validation.

    Use either:
    - source_record: dictionary with source sections
    - raw_prompt: prompt text containing bracketed source sections

    Returns:
        {
            "claim_rows": [...],
            "summary": {...},
            "attribution_rate": float,
            "requires_review": bool
        }
    """
    if source_record is None and raw_prompt is None:
        raise ValueError("Provide either source_record or raw_prompt.")

    if source_record is not None:
        source_sections = source_record_to_sections(source_record)
    else:
        source_sections = extract_prompt_sections(raw_prompt or "")

    claim_rows, summary = validate_claims_for_artifact(
        summary_artifact,
        source_sections,
    )

    attribution_rate = summary["atomic_claim_attribution_rate"]

    requires_review = attribution_rate < 1.0

    return {
        "claim_rows": claim_rows,
        "summary": summary,
        "attribution_rate": attribution_rate,
        "requires_review": requires_review,
    }


# =============================================================================
# Local sanity checks
# =============================================================================

if __name__ == "__main__":
    source_record = {
        "STRUCTURED_FIELDS": {
            "length_of_stay": "3.0 days",
            "transition_support_documented": "YES",
        },
        "SOURCE_TEXT": (
            "The source record states that transition support was documented. "
            "The record does not provide cohort median, baseline, or comparator data."
        ),
        "MISSINGNESS_NOTES": [
            "Comparator data are not available.",
            "Some registry fields are incomplete.",
        ],
    }

    clean_artifact = {
        "synthetic_record_id": "SYNTH_0001",
        "atomic_claims": [
            {
                "claim_id": "C1",
                "claim_text": "Comparator data are not available.",
                "source_field": "MISSINGNESS_NOTES",
                "evidence_quote": "Comparator data are not available.",
            },
            {
                "claim_id": "C2",
                "claim_text": "Transition support was documented.",
                "source_field": "SOURCE_TEXT",
                "evidence_quote": "transition support was documented",
            },
        ],
    }

    bad_artifact = {
        "synthetic_record_id": "SYNTH_0002",
        "atomic_claims": [
            {
                "claim_id": "C1",
                "claim_text": "The case is above the cohort median.",
                "source_field": "SOURCE_TEXT",
                "evidence_quote": "above the cohort median",
            }
        ],
    }

    clean_result = validate_source_attribution(
        clean_artifact,
        source_record=source_record,
    )

    assert clean_result["attribution_rate"] == 1.0
    assert clean_result["requires_review"] is False

    bad_result = validate_source_attribution(
        bad_artifact,
        source_record=source_record,
    )

    assert bad_result["attribution_rate"] == 0.0
    assert bad_result["requires_review"] is True
    assert "C1" in bad_result["summary"]["unmatched_claim_ids"]

    prompt_text = """
[STRUCTURED_FIELDS]
length_of_stay: 3.0 days

[SOURCE_TEXT]
The source record states that transition support was documented.

[MISSINGNESS_NOTES]
Comparator data are not available.
""".strip()

    prompt_result = validate_source_attribution(
        clean_artifact,
        raw_prompt=prompt_text,
    )

    assert prompt_result["attribution_rate"] == 1.0

    print("attribution_validator.py sanity checks passed.")
