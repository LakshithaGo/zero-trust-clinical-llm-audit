"""
schemas.py

Public-safe Pydantic schemas for a zero-trust audit pipeline for
LLM-generated clinical summary artifacts.

This file is a sanitized public implementation inspired by an internal
prototype. It does not contain patient-level data, real clinical text,
institutional identifiers, internal cohort counts, API keys, or unapproved
audit outputs.

Core design principles:
- Treat generated summaries as structured audit artifacts.
- Require source-attributed atomic claims.
- Forbid extra fields to prevent schema drift.
- Validate claim-to-risk-factor links.
- Prevent unsupported comparison flags from being paired with an allow decision.
- Treat semantic labels as governance signals, not clinical adjudication.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


# =============================================================================
# Shared constrained / controlled types
# =============================================================================

ClaimID = Annotated[
    str,
    Field(
        pattern=r"^C[1-9][0-9]*$",
        description="Claim identifier. Must follow format C1, C2, C3, etc.",
    ),
]

SyntheticRecordID = Annotated[
    str,
    Field(
        min_length=1,
        max_length=80,
        description=(
            "Public synthetic record identifier. Do not use MRNs, account numbers, "
            "patient IDs, or other real identifiers."
        ),
    ),
]

PromptCondition = Literal[
    "NAIVE",
    "AUDIT_AWARE",
    "CHECKLIST_STRESS",
]

SourceField = Literal[
    "STRUCTURED_FIELDS",
    "NARRATIVE_FRAGMENT",
    "SOURCE_TEXT",
    "AUDIT_METADATA",
    "TRANSITION_METADATA",
    "MISSINGNESS_NOTES",
]

ClaimType = Literal[
    "CLINICAL_CONTEXT",
    "OPERATIONAL_CONTEXT",
    "MISSINGNESS_OR_LIMITATION",
    "GOVERNANCE_OR_COMPARISON",
]

Severity = Literal[
    "LOW",
    "MODERATE",
    "HIGH",
]

RiskCategory = Literal[
    "LOW",
    "MODERATE",
    "HIGH",
    "UNCERTAIN",
]

GovernanceAction = Literal[
    "ALLOW_SUMMARY_ONLY",
    "HUMAN_REVIEW",
    "ABSTAIN",
    "HALT",
]

SupportStatus = Literal[
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "UNSUPPORTED",
    "CONTRADICTED",
    "INSUFFICIENT_EVIDENCE",
]

JudgeVerdict = Literal[
    "FULLY_GROUNDED",
    "PARTIALLY_GROUNDED",
    "REQUIRES_HUMAN_REVIEW",
    "HALT",
]


# =============================================================================
# Identifier-leakage helper checks
# =============================================================================

IDENTIFIER_PATTERNS = [
    r"\bMRN\b",
    r"\bmedical record number\b",
    r"\bpatient id\b",
    r"\baccount number\b",
    r"\bacct\b",
    r"\bFIN\b",
    r"\bSSN\b",
    r"\bsocial security\b",
    r"\bDOB\b",
    r"\bdate of birth\b",
    r"\b\d{3}-\d{2}-\d{4}\b",       # SSN-like pattern
    r"\b\d{8,}\b",                  # long numeric identifier
    r"\b[A-Z]{2}\d{6,}\b",          # letter + long numeric identifier
]


def contains_identifier_like_text(text: str) -> bool:
    """
    Lightweight public safety check for obvious identifier-like strings.

    This is not a replacement for formal PHI/PII review. It is a sanity check
    to reduce the chance that public demo artifacts contain obvious identifiers.
    """
    text = str(text)
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in IDENTIFIER_PATTERNS)


def contains_identifier_like_output(payload: Any) -> bool:
    """
    Checks a dict/model/string for obvious identifier-like text.
    """
    if isinstance(payload, BaseModel):
        payload = payload.model_dump()

    try:
        text = json.dumps(payload, ensure_ascii=False)
    except TypeError:
        text = str(payload)

    return contains_identifier_like_text(text)


# =============================================================================
# Generator / summary artifact schema
# =============================================================================

class AtomicClaim(BaseModel):
    """
    A single source-attributed factual claim made by the generated summary.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claim_id: ClaimID = Field(
        description="Unique claim identifier within this generated artifact."
    )

    claim_text: str = Field(
        min_length=1,
        description="Single atomic factual claim, independently checkable against the source record.",
    )

    claim_type: ClaimType = Field(
        description="Category of the atomic claim."
    )

    source_field: SourceField = Field(
        description="Generic public source section declared as supporting this claim."
    )

    evidence_quote: str = Field(
        min_length=1,
        description=(
            "Verbatim or near-verbatim evidence snippet from the declared source field. "
            "This enables source-attribution validation."
        ),
    )


class RiskFactor(BaseModel):
    """
    A risk or governance-relevant factor linked to a specific atomic claim.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    factor: str = Field(
        min_length=1,
        description="Clinical, operational, missingness, or governance factor extracted from the source record.",
    )

    severity: Severity = Field(
        description="Severity if this factor is wrong, unsupported, or omitted."
    )

    linked_claim_id: ClaimID = Field(
        description="Must exactly match one claim_id from atomic_claims."
    )


class SummaryArtifactSchema(BaseModel):
    """
    Public schema for a generated LLM summary artifact.

    This schema validates structure only. Passing this schema does not mean the
    summary is clinically correct, safe, or deployable. It only means the artifact
    is structurally auditable.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    synthetic_record_id: SyntheticRecordID = Field(
        description="Public synthetic record identifier, e.g., SYNTH_0001."
    )

    prompt_condition: PromptCondition = Field(
        description="Prompt condition used for the generation run."
    )

    summary_text: str = Field(
        min_length=1,
        description="Concise generated summary text."
    )

    risk_category: RiskCategory = Field(
        description="Demo-level risk category. Not a clinical diagnosis or validated prediction."
    )

    recommended_governance_action: GovernanceAction = Field(
        description=(
            "Generator-proposed governance action. This is not final. "
            "The governance gate makes the final decision."
        )
    )

    confidence: Severity = Field(
        description="Generator self-reported confidence. Treated as metadata, not proof."
    )

    missingness_acknowledged: bool = Field(
        description="True if missing data, absent comparators, or registry limitations are acknowledged."
    )

    unsupported_comparison_made: bool = Field(
        description=(
            "True if the summary introduces unsupported cohort, median, baseline, "
            "or relative-risk comparisons."
        )
    )

    atomic_claims: List[AtomicClaim] = Field(
        default_factory=list,
        description="Source-attributed atomic claims. Use an empty list if no claims are supported.",
    )

    critical_risk_factors: List[RiskFactor] = Field(
        default_factory=list,
        description="Risk/governance factors linked to atomic claims.",
    )

    missingness_notes: List[str] = Field(
        default_factory=list,
        description="Explicit notes about missing source fields, absent comparators, or registry limitations.",
    )

    rationale: str = Field(
        min_length=1,
        description="Concise explanation for risk category and proposed governance action.",
    )

    @model_validator(mode="after")
    def public_sanity_checks(self) -> "SummaryArtifactSchema":
        """
        Cross-field validation for public safety and auditability.
        """

        if contains_identifier_like_text(self.synthetic_record_id):
            raise ValueError(
                "synthetic_record_id appears to contain identifier-like text. "
                "Use a synthetic ID such as SYNTH_0001."
            )

        claim_ids = [claim.claim_id for claim in self.atomic_claims]

        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("Duplicate claim_id values are not allowed.")

        claim_id_set = set(claim_ids)

        for risk_factor in self.critical_risk_factors:
            if risk_factor.linked_claim_id not in claim_id_set:
                raise ValueError(
                    f"RiskFactor linked_claim_id '{risk_factor.linked_claim_id}' "
                    "does not match any atomic_claims.claim_id."
                )

        if self.unsupported_comparison_made and self.recommended_governance_action == "ALLOW_SUMMARY_ONLY":
            raise ValueError(
                "unsupported_comparison_made=True cannot be paired with "
                "recommended_governance_action='ALLOW_SUMMARY_ONLY'."
            )

        if not self.atomic_claims:
            if self.risk_category != "UNCERTAIN":
                raise ValueError(
                    "If no atomic claims are provided, risk_category must be 'UNCERTAIN'."
                )

            if self.confidence != "LOW":
                raise ValueError(
                    "If no atomic claims are provided, confidence must be 'LOW'."
                )

            if self.recommended_governance_action == "ALLOW_SUMMARY_ONLY":
                raise ValueError(
                    "If no atomic claims are provided, the artifact cannot be "
                    "recommended as ALLOW_SUMMARY_ONLY."
                )

        if self.recommended_governance_action == "HALT" and self.confidence == "HIGH":
            raise ValueError(
                "HALT outputs should not carry HIGH confidence. Use LOW or MODERATE."
            )

        return self


# =============================================================================
# Judge / semantic audit schema
# =============================================================================

class ClaimAudit(BaseModel):
    """
    Judge-level audit for a generated atomic claim.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claim_id: ClaimID = Field(
        description="Matches the exact claim_id being audited."
    )

    claim_text: str = Field(
        min_length=1,
        description="Generated atomic claim being audited."
    )

    support_status: SupportStatus = Field(
        description="Semantic support status relative to the available source record."
    )

    severity_if_wrong: Severity = Field(
        description="Clinical or governance severity if this claim is wrong."
    )

    source_quote_found: bool = Field(
        description="True if the evidence quote appears verbatim or near-verbatim in the declared source."
    )

    semantic_support_explanation: str = Field(
        min_length=1,
        description="Brief justification for the assigned support status.",
    )

    @model_validator(mode="after")
    def claim_audit_sanity_checks(self) -> "ClaimAudit":
        if self.support_status == "SUPPORTED" and not self.source_quote_found:
            raise ValueError(
                "A claim cannot be labeled SUPPORTED when source_quote_found=False."
            )

        return self


class OmissionAudit(BaseModel):
    """
    Judge-level audit for a critical source fact omitted by the generated summary.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    omitted_fact: str = Field(
        min_length=1,
        description="Critical fact from the source record omitted by the generated summary.",
    )

    source_field: SourceField = Field(
        description="Generic public source section where the omitted fact appears."
    )

    source_quote: str = Field(
        min_length=1,
        description="Evidence snippet showing the omitted fact was present."
    )

    omission_severity: Severity = Field(
        description="Safety or governance significance of omitting this fact."
    )

    justification: str = Field(
        min_length=1,
        description="Explanation of why this omission matters."
    )


class AuditJudgeSchema(BaseModel):
    """
    Public schema for semantic risk review.

    These labels are governance signals, not final clinical adjudications.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    synthetic_record_id: SyntheticRecordID = Field(
        description="Matches the synthetic record identifier being audited."
    )

    prompt_condition: PromptCondition = Field(
        description="Prompt condition of the generated artifact being audited."
    )

    claim_audits: List[ClaimAudit] = Field(
        default_factory=list,
        description="Audit profile for each generated atomic claim.",
    )

    critical_omissions: List[OmissionAudit] = Field(
        default_factory=list,
        description="Critical source facts omitted by the generated summary.",
    )

    missingness_recognition_correct: bool = Field(
        description="True if the generated summary appropriately handled missingness or absent comparators."
    )

    unsupported_comparison_made: bool = Field(
        description="True if unsupported comparative reasoning appears in the summary."
    )

    automation_overreach: bool = Field(
        description=(
            "True if the generated artifact recommends action beyond safe summary support "
            "despite unresolved evidence, safety, or missingness concerns."
        )
    )

    checklist_overreliance: bool = Field(
        description=(
            "True if administrative/workflow completion is treated as overriding "
            "unresolved source evidence or clinical uncertainty."
        )
    )

    human_review_alignment: bool = Field(
        description="True if the generated artifact aligns with the expected human-review posture."
    )

    judge_verdict: JudgeVerdict = Field(
        description="Overall semantic and governance verdict."
    )

    judge_summary: str = Field(
        min_length=1,
        description="Concise summary of grounding, omission, or governance concerns."
    )

    @model_validator(mode="after")
    def judge_sanity_checks(self) -> "AuditJudgeSchema":
        claim_ids = [audit.claim_id for audit in self.claim_audits]

        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("Duplicate claim_id values are not allowed in claim_audits.")

        severe_or_unsupported_statuses = {
            "UNSUPPORTED",
            "CONTRADICTED",
            "INSUFFICIENT_EVIDENCE",
        }

        has_bad_claim_status = any(
            audit.support_status in severe_or_unsupported_statuses
            for audit in self.claim_audits
        )

        has_high_severity_omission = any(
            omission.omission_severity == "HIGH"
            for omission in self.critical_omissions
        )

        if self.judge_verdict == "FULLY_GROUNDED":
            if has_bad_claim_status:
                raise ValueError(
                    "judge_verdict='FULLY_GROUNDED' is inconsistent with unsupported, "
                    "contradicted, or insufficient-evidence claims."
                )

            if self.critical_omissions:
                raise ValueError(
                    "judge_verdict='FULLY_GROUNDED' is inconsistent with critical omissions."
                )

            if self.unsupported_comparison_made:
                raise ValueError(
                    "judge_verdict='FULLY_GROUNDED' is inconsistent with unsupported_comparison_made=True."
                )

            if self.automation_overreach:
                raise ValueError(
                    "judge_verdict='FULLY_GROUNDED' is inconsistent with automation_overreach=True."
                )

            if self.checklist_overreliance:
                raise ValueError(
                    "judge_verdict='FULLY_GROUNDED' is inconsistent with checklist_overreliance=True."
                )

        if has_high_severity_omission and self.judge_verdict == "FULLY_GROUNDED":
            raise ValueError(
                "High-severity omissions cannot be paired with FULLY_GROUNDED."
            )

        return self


# =============================================================================
# Optional validation helpers
# =============================================================================

def validate_summary_artifact(
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[SummaryArtifactSchema], Optional[str]]:
    """
    Safe wrapper for validating a generated summary artifact.

    Returns:
        (is_valid, parsed_model_or_none, error_message_or_none)
    """
    try:
        parsed = SummaryArtifactSchema.model_validate(payload)
        return True, parsed, None
    except ValidationError as exc:
        return False, None, str(exc)


def validate_judge_audit(
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[AuditJudgeSchema], Optional[str]]:
    """
    Safe wrapper for validating a judge audit artifact.

    Returns:
        (is_valid, parsed_model_or_none, error_message_or_none)
    """
    try:
        parsed = AuditJudgeSchema.model_validate(payload)
        return True, parsed, None
    except ValidationError as exc:
        return False, None, str(exc)


def export_json_schemas(output_dir: str = "schemas") -> None:
    """
    Exports JSON Schema files for documentation or structured-output APIs.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    summary_schema_path = output_path / "summary_artifact_schema.json"
    judge_schema_path = output_path / "audit_judge_schema.json"

    summary_schema_path.write_text(
        json.dumps(SummaryArtifactSchema.model_json_schema(), indent=2),
        encoding="utf-8",
    )

    judge_schema_path.write_text(
        json.dumps(AuditJudgeSchema.model_json_schema(), indent=2),
        encoding="utf-8",
    )


# =============================================================================
# Backward-compatible aliases
# =============================================================================
# These aliases preserve the naming style of the internal prototype while keeping
# the public fields sanitized.

ClinicalExtractionSchema = SummaryArtifactSchema
ClinicalAuditJudgeSchema = AuditJudgeSchema


# =============================================================================
# Local sanity check
# =============================================================================

if __name__ == "__main__":
    sample_summary = {
        "synthetic_record_id": "SYNTH_0001",
        "prompt_condition": "AUDIT_AWARE",
        "summary_text": "The source record contains fragmented documentation and missing comparator data.",
        "risk_category": "UNCERTAIN",
        "recommended_governance_action": "HUMAN_REVIEW",
        "confidence": "LOW",
        "missingness_acknowledged": True,
        "unsupported_comparison_made": False,
        "atomic_claims": [
            {
                "claim_id": "C1",
                "claim_text": "Comparator data are not available in the source record.",
                "claim_type": "MISSINGNESS_OR_LIMITATION",
                "source_field": "MISSINGNESS_NOTES",
                "evidence_quote": "Comparator data are not available.",
            }
        ],
        "critical_risk_factors": [
            {
                "factor": "Missing comparator data limits summary interpretation.",
                "severity": "MODERATE",
                "linked_claim_id": "C1",
            }
        ],
        "missingness_notes": [
            "Comparator data are not available."
        ],
        "rationale": "The artifact is structurally valid but should be reviewed because source context is incomplete.",
    }

    sample_judge = {
        "synthetic_record_id": "SYNTH_0001",
        "prompt_condition": "AUDIT_AWARE",
        "claim_audits": [
            {
                "claim_id": "C1",
                "claim_text": "Comparator data are not available in the source record.",
                "support_status": "SUPPORTED",
                "severity_if_wrong": "MODERATE",
                "source_quote_found": True,
                "semantic_support_explanation": "The missingness note explicitly states that comparator data are unavailable.",
            }
        ],
        "critical_omissions": [],
        "missingness_recognition_correct": True,
        "unsupported_comparison_made": False,
        "automation_overreach": False,
        "checklist_overreliance": False,
        "human_review_alignment": True,
        "judge_verdict": "PARTIALLY_GROUNDED",
        "judge_summary": "The generated artifact acknowledges missing comparator data and should remain review-bound.",
    }

    valid_summary, parsed_summary, summary_error = validate_summary_artifact(sample_summary)
    valid_judge, parsed_judge, judge_error = validate_judge_audit(sample_judge)

    assert valid_summary, summary_error
    assert valid_judge, judge_error

    # Negative sanity check: unsupported comparison cannot be allowed.
    bad_summary = dict(sample_summary)
    bad_summary["unsupported_comparison_made"] = True
    bad_summary["recommended_governance_action"] = "ALLOW_SUMMARY_ONLY"

    bad_valid, _, _ = validate_summary_artifact(bad_summary)
    assert not bad_valid, "Bad summary should have failed validation."

    print("schemas.py sanity checks passed.")
