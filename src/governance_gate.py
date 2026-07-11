"""
governance_gate.py

Public-safe rule-based governance gate for a zero-trust audit pipeline.

This module converts audit signals into one final routing decision:

- HALT:
    Block before downstream exposure.

- HUMAN_REVIEW:
    Send to human review before any use.

- ALLOW_SUMMARY_ONLY:
    Retain only as limited summary support.
    This never authorizes autonomous clinical action.

This is a synthetic public demo. It is not a clinical validation system.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# =============================================================================
# Small helpers
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


def get_list(payload: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    """
    Safely gets a list of dictionaries from a payload.
    """
    value = payload.get(key, [])

    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]

    return []


def has_high_risk_factor(summary_artifact: Dict[str, Any]) -> bool:
    """
    Returns True if the generated summary includes a high-severity risk factor.
    """
    risk_factors = get_list(summary_artifact, "critical_risk_factors")

    return any(
        factor.get("severity") == "HIGH"
        for factor in risk_factors
    )


def has_high_severity_contradiction(judge_output: Optional[Dict[str, Any]]) -> bool:
    """
    Returns True if the judge found a high-severity contradicted claim.
    """
    if not judge_output:
        return False

    claim_audits = get_list(judge_output, "claim_audits")

    return any(
        claim.get("support_status") == "CONTRADICTED"
        and claim.get("severity_if_wrong") == "HIGH"
        for claim in claim_audits
    )


def has_review_level_claim_issue(judge_output: Optional[Dict[str, Any]]) -> bool:
    """
    Returns True if the judge found claims that should be reviewed.
    """
    if not judge_output:
        return False

    review_statuses = {
        "PARTIALLY_SUPPORTED",
        "UNSUPPORTED",
        "CONTRADICTED",
        "INSUFFICIENT_EVIDENCE",
    }

    claim_audits = get_list(judge_output, "claim_audits")

    return any(
        claim.get("support_status") in review_statuses
        for claim in claim_audits
    )


def has_critical_omissions(judge_output: Optional[Dict[str, Any]]) -> bool:
    """
    Returns True if the judge identified any critical omissions.
    """
    if not judge_output:
        return False

    return len(get_list(judge_output, "critical_omissions")) > 0


# =============================================================================
# Main gate
# =============================================================================

def compute_gate_decision(
    summary_artifact: Dict[str, Any],
    *,
    schema_valid: bool = True,
    privacy_leakage_flag: bool = False,
    attribution_rate: float = 1.0,
    semantic_result: Optional[Dict[str, Any]] = None,
    judge_output: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Computes the final zero-trust gate decision.

    Inputs:
        summary_artifact:
            Parsed generated summary artifact.

        schema_valid:
            True if the artifact passed schema validation.

        privacy_leakage_flag:
            True if privacy/identifier leakage was detected.

        attribution_rate:
            Fraction of atomic claims whose evidence was traceable.
            Use 1.0 when every evidence quote is traceable.

        semantic_result:
            Optional output from semantic_risk_labels.label_semantic_risk().

        judge_output:
            Optional raw judge output.

    Returns:
        Dictionary with:
        - final_decision
        - halt_reasons
        - review_reasons
        - notes
    """

    halt_reasons: List[str] = []
    review_reasons: List[str] = []
    notes: List[str] = []

    semantic_result = semantic_result or {}

    # -------------------------------------------------------------------------
    # 1. Hard stop conditions
    # -------------------------------------------------------------------------

    if not schema_valid:
        halt_reasons.append("schema_validation_failed")

    if privacy_leakage_flag:
        halt_reasons.append("privacy_or_identifier_leakage")

    if judge_output and judge_output.get("judge_verdict") == "HALT":
        halt_reasons.append("judge_verdict_halt")

    if has_high_severity_contradiction(judge_output):
        halt_reasons.append("high_severity_contradicted_claim")

    if semantic_result.get("semantic_risk_level") == "HALT_LEVEL_RISK":
        halt_reasons.extend(
            semantic_result.get("halt_reasons", ["semantic_halt_level_risk"])
        )

    # -------------------------------------------------------------------------
    # 2. Human-review conditions
    # -------------------------------------------------------------------------

    if attribution_rate < 1.0:
        review_reasons.append("incomplete_source_attribution")

    if to_bool(summary_artifact.get("unsupported_comparison_made")):
        review_reasons.append("unsupported_comparison_made")

    if to_bool(summary_artifact.get("missingness_acknowledged")):
        review_reasons.append("missingness_requires_review")

    if has_high_risk_factor(summary_artifact):
        review_reasons.append("high_severity_risk_factor_present")

    if judge_output:
        if has_review_level_claim_issue(judge_output):
            review_reasons.append("claim_support_issue")

        if has_critical_omissions(judge_output):
            review_reasons.append("critical_omission")

        if to_bool(judge_output.get("unsupported_comparison_made")):
            review_reasons.append("judge_flag_unsupported_comparison")

        if to_bool(judge_output.get("automation_overreach")):
            review_reasons.append("automation_overreach")

        if to_bool(judge_output.get("checklist_overreliance")):
            review_reasons.append("checklist_overreliance")

        if judge_output.get("judge_verdict") in {
            "PARTIALLY_GROUNDED",
            "REQUIRES_HUMAN_REVIEW",
        }:
            review_reasons.append("judge_verdict_requires_review")

    if semantic_result.get("semantic_risk_level") == "REVIEW_LEVEL_RISK":
        review_reasons.extend(
            semantic_result.get("review_reasons", ["semantic_review_level_risk"])
        )

    # -------------------------------------------------------------------------
    # 3. Final decision
    # -------------------------------------------------------------------------

    halt_reasons = list(dict.fromkeys(halt_reasons))
    review_reasons = list(dict.fromkeys(review_reasons))

    if halt_reasons:
        final_decision = "HALT"

    elif review_reasons:
        final_decision = "HUMAN_REVIEW"

    else:
        final_decision = "ALLOW_SUMMARY_ONLY"

    # -------------------------------------------------------------------------
    # 4. Notes
    # -------------------------------------------------------------------------

    if final_decision == "ALLOW_SUMMARY_ONLY":
        notes.append(
            "Artifact may be retained only as limited summary support. "
            "This does not authorize autonomous clinical action."
        )

    if final_decision == "HUMAN_REVIEW":
        notes.append(
            "Artifact requires human review before downstream workflow exposure."
        )

    if final_decision == "HALT":
        notes.append(
            "Artifact should be blocked before downstream exposure."
        )

    return {
        "final_decision": final_decision,
        "halt_reasons": halt_reasons,
        "review_reasons": review_reasons,
        "notes": notes,
    }


# =============================================================================
# Local sanity checks
# =============================================================================

if __name__ == "__main__":
    clean_summary = {
        "synthetic_record_id": "SYNTH_0001",
        "unsupported_comparison_made": False,
        "missingness_acknowledged": False,
        "critical_risk_factors": [],
    }

    review_summary = {
        "synthetic_record_id": "SYNTH_0002",
        "unsupported_comparison_made": True,
        "missingness_acknowledged": True,
        "critical_risk_factors": [],
    }

    halt_judge = {
        "judge_verdict": "HALT",
        "claim_audits": [
            {
                "claim_id": "C1",
                "support_status": "CONTRADICTED",
                "severity_if_wrong": "HIGH",
            }
        ],
        "critical_omissions": [],
    }

    # Clean case: allow summary-only.
    result_clean = compute_gate_decision(
        clean_summary,
        schema_valid=True,
        privacy_leakage_flag=False,
        attribution_rate=1.0,
    )

    assert result_clean["final_decision"] == "ALLOW_SUMMARY_ONLY"

    # Review case: unsupported comparison + missingness.
    result_review = compute_gate_decision(
        review_summary,
        schema_valid=True,
        privacy_leakage_flag=False,
        attribution_rate=1.0,
    )

    assert result_review["final_decision"] == "HUMAN_REVIEW"
    assert "unsupported_comparison_made" in result_review["review_reasons"]

    # Halt case: judge-level halt and high-severity contradiction.
    result_halt = compute_gate_decision(
        clean_summary,
        schema_valid=True,
        privacy_leakage_flag=False,
        attribution_rate=1.0,
        judge_output=halt_judge,
    )

    assert result_halt["final_decision"] == "HALT"

    # Halt case: schema failure.
    result_schema_fail = compute_gate_decision(
        clean_summary,
        schema_valid=False,
        privacy_leakage_flag=False,
        attribution_rate=1.0,
    )

    assert result_schema_fail["final_decision"] == "HALT"

    print("governance_gate.py sanity checks passed.")
