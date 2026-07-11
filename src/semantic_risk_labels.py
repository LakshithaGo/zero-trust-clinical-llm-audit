"""
semantic_risk_labels.py

Public-safe semantic risk labeling for a zero-trust audit pipeline.

This module converts judge/audit outputs into simple governance risk labels.
It does not make clinical decisions. These labels are governance signals only.

Expected input:
- A judge_output dictionary matching the public AuditJudgeSchema from schemas.py.

Main output:
- A compact dictionary of semantic risk labels and review/halt reasons.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List


# =============================================================================
# Basic helpers
# =============================================================================

def to_bool(value: Any) -> bool:
    """
    Converts common bool-like values into True/False.
    """
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}

    return False


def get_claim_audits(judge_output: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Safely returns claim_audits as a list.
    """
    claim_audits = judge_output.get("claim_audits", [])

    if isinstance(claim_audits, list):
        return claim_audits

    return []


def get_critical_omissions(judge_output: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Safely returns critical_omissions as a list.
    """
    omissions = judge_output.get("critical_omissions", [])

    if isinstance(omissions, list):
        return omissions

    return []


# =============================================================================
# Core semantic risk labeling
# =============================================================================

def label_claim_risk(claim_audit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assigns a simple semantic risk label to one claim audit.
    """
    claim_id = claim_audit.get("claim_id", "UNKNOWN_CLAIM")
    support_status = claim_audit.get("support_status", "INSUFFICIENT_EVIDENCE")
    severity = claim_audit.get("severity_if_wrong", "MODERATE")
    source_quote_found = to_bool(claim_audit.get("source_quote_found"))

    if support_status == "SUPPORTED" and source_quote_found:
        label = "SUPPORTED"
        review_required = False
        halt_recommended = False

    elif support_status == "PARTIALLY_SUPPORTED":
        label = "PARTIAL_SUPPORT"
        review_required = True
        halt_recommended = False

    elif support_status == "UNSUPPORTED":
        label = "UNSUPPORTED_CLAIM"
        review_required = True
        halt_recommended = False

    elif support_status == "INSUFFICIENT_EVIDENCE":
        label = "INSUFFICIENT_EVIDENCE"
        review_required = True
        halt_recommended = False

    elif support_status == "CONTRADICTED":
        label = "CONTRADICTED_CLAIM"
        review_required = True
        halt_recommended = severity == "HIGH"

    else:
        label = "UNKNOWN_SUPPORT_STATUS"
        review_required = True
        halt_recommended = False

    return {
        "claim_id": claim_id,
        "semantic_label": label,
        "support_status": support_status,
        "severity_if_wrong": severity,
        "source_quote_found": source_quote_found,
        "review_required": review_required,
        "halt_recommended": halt_recommended,
    }


def label_semantic_risk(judge_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converts a judge output into semantic risk labels.

    This function is intentionally simple:
    - high-severity contradicted claims can trigger HALT
    - unsupported/partial/insufficient claims trigger HUMAN_REVIEW
    - unsupported comparisons trigger HUMAN_REVIEW
    - critical omissions trigger HUMAN_REVIEW
    - automation overreach triggers HUMAN_REVIEW
    - checklist overreliance triggers HUMAN_REVIEW
    - judge_verdict == HALT triggers HALT
    """
    claim_audits = get_claim_audits(judge_output)
    critical_omissions = get_critical_omissions(judge_output)

    claim_labels = [label_claim_risk(claim) for claim in claim_audits]

    support_counts = Counter(
        claim.get("support_status", "UNKNOWN")
        for claim in claim_audits
    )

    review_reasons: List[str] = []
    halt_reasons: List[str] = []

    # -------------------------------------------------------------------------
    # Claim-level signals
    # -------------------------------------------------------------------------
    for label in claim_labels:
        claim_id = label["claim_id"]
        semantic_label = label["semantic_label"]

        if label["halt_recommended"]:
            halt_reasons.append(f"high_severity_{semantic_label.lower()}:{claim_id}")

        elif label["review_required"]:
            review_reasons.append(f"{semantic_label.lower()}:{claim_id}")

    # -------------------------------------------------------------------------
    # Omission signals
    # -------------------------------------------------------------------------
    for omission in critical_omissions:
        severity = omission.get("omission_severity", "MODERATE")

        if severity == "HIGH":
            review_reasons.append("high_severity_critical_omission")
        else:
            review_reasons.append("critical_omission")

    # -------------------------------------------------------------------------
    # Judge-level governance signals
    # -------------------------------------------------------------------------
    judge_verdict = judge_output.get("judge_verdict")

    if judge_verdict == "HALT":
        halt_reasons.append("judge_verdict_halt")

    if judge_verdict in {"PARTIALLY_GROUNDED", "REQUIRES_HUMAN_REVIEW"}:
        review_reasons.append(f"judge_verdict_{str(judge_verdict).lower()}")

    if to_bool(judge_output.get("unsupported_comparison_made")):
        review_reasons.append("unsupported_comparison_made")

    if not to_bool(judge_output.get("missingness_recognition_correct")):
        review_reasons.append("missingness_not_correctly_acknowledged")

    if to_bool(judge_output.get("automation_overreach")):
        review_reasons.append("automation_overreach")

    if to_bool(judge_output.get("checklist_overreliance")):
        review_reasons.append("checklist_overreliance")

    if not to_bool(judge_output.get("human_review_alignment")):
        review_reasons.append("human_review_alignment_failure")

    # Remove duplicate reasons while preserving order.
    review_reasons = list(dict.fromkeys(review_reasons))
    halt_reasons = list(dict.fromkeys(halt_reasons))

    if halt_reasons:
        semantic_risk_level = "HALT_LEVEL_RISK"
    elif review_reasons:
        semantic_risk_level = "REVIEW_LEVEL_RISK"
    else:
        semantic_risk_level = "NO_MAJOR_SEMANTIC_RISK"

    return {
        "semantic_risk_level": semantic_risk_level,
        "claim_labels": claim_labels,
        "support_counts": dict(support_counts),
        "critical_omission_count": len(critical_omissions),
        "review_reasons": review_reasons,
        "halt_reasons": halt_reasons,
    }


# =============================================================================
# Optional lightweight text check for unsupported comparisons
# =============================================================================

COMPARISON_TERMS = [
    "median",
    "baseline",
    "cohort",
    "population",
    "compared with",
    "compared to",
    "above average",
    "below average",
    "higher than",
    "lower than",
    "relative risk",
]


def contains_comparison_language(text: str) -> bool:
    """
    Returns True if text contains simple comparison language.
    """
    text = str(text).lower()
    return any(term in text for term in COMPARISON_TERMS)


def flag_unsupported_comparison(summary_text: str, source_text: str) -> bool:
    """
    Lightweight rule:
    If the summary uses comparison language but the source does not,
    flag unsupported comparative reasoning.

    This is only a backup heuristic. The main signal should come from judge_output.
    """
    return (
        contains_comparison_language(summary_text)
        and not contains_comparison_language(source_text)
    )


# =============================================================================
# Local sanity check
# =============================================================================

if __name__ == "__main__":
    sample_judge_output = {
        "synthetic_record_id": "SYNTH_0001",
        "prompt_condition": "AUDIT_AWARE",
        "claim_audits": [
            {
                "claim_id": "C1",
                "claim_text": "Comparator data are not available.",
                "support_status": "SUPPORTED",
                "severity_if_wrong": "MODERATE",
                "source_quote_found": True,
                "semantic_support_explanation": "The source states comparator data are unavailable.",
            },
            {
                "claim_id": "C2",
                "claim_text": "The case is above the cohort median.",
                "support_status": "UNSUPPORTED",
                "severity_if_wrong": "MODERATE",
                "source_quote_found": False,
                "semantic_support_explanation": "No cohort median is present in the source.",
            },
        ],
        "critical_omissions": [],
        "missingness_recognition_correct": True,
        "unsupported_comparison_made": True,
        "automation_overreach": False,
        "checklist_overreliance": False,
        "human_review_alignment": True,
        "judge_verdict": "REQUIRES_HUMAN_REVIEW",
        "judge_summary": "Unsupported comparative framing requires review.",
    }

    result = label_semantic_risk(sample_judge_output)

    assert result["semantic_risk_level"] == "REVIEW_LEVEL_RISK"
    assert "unsupported_claim:C2" in result["review_reasons"]
    assert "unsupported_comparison_made" in result["review_reasons"]
    assert result["halt_reasons"] == []

    print("semantic_risk_labels.py sanity checks passed.")
