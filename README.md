# Zero-Trust Audit Pipeline for Clinical LLM Summaries 

This repository contains a public synthetic methodological case study and prototype code for auditing LLM-generated clinical summary artifacts. The pipeline routes generated summaries through schema validation, source-attribution validation, semantic risk labeling, and rule-based governance gating.

This public version uses synthetic and abstracted registry-style examples. It does not include patient-level data, real clinical text, institutional identifiers, or unapproved internal results.

## Table of contents 
- [Summary](#summary)
- [Case setting and deployment risk](#Case-setting-and-deployment-risk)
- [Zero-trust audit pipeline](#Zero-trust-audit-pipeline)
    - [Methodology](#Methodology)
- [Synthetic demonstration and failure-mode taxonomy](#Synthetic-demonstration-and-failure-mode-taxonomy)
    - [Table 1](#Table-1)
    - [Abstracted review example](#Abstracted-review-example)
- [Governance implications and limitations ](#Governance-implications-and-limitations )

## Summary

Clinical large language models (LLMs) are increasingly proposed for summarization, chart review, and documentation support, but fluent and schema-valid outputs may still contain verification failures that pose deployment-relevant risks. This synthetic methodological case study presents the design and demonstration of a zero-trust audit gate for LLM-generated clinical summaries using registry-style clinical records. The pipeline routes each generated summary through four control layers: (1) structured schema validation, (2) normalized source-attribution validation, (3) semantic risk review, and (4) final governance routing. The case study focuses on two auditability failure modes: quote stitching, where a model constructs unverifiable evidence snippets from true facts, and unsupported comparative reasoning, where a summary presents baseline or cohort-level comparisons not present in the record. This report shows how generated clinical summaries can be treated as auditable artifacts and routed to summary-only use, human review, or halt decisions before downstream exposure. The case illustrates how clinical LLM governance can move beyond benchmark accuracy toward traceable, source-grounded, and workflow-aware deployment controls.

## Case setting and deployment risk 

Clinical environments are typified by fragmented documentation, where essential patient data is usually dispersed across patient health databases, administrative metadata, and unstructured clinical narratives (Alu & Oluwadare, 2026) (Wang et al., 2026). Large Language Models (LLMs) provide a method for combining these fragments into unified clinical summaries, but linguistic coherence can shroud critical deployment risks (Dave Van Veen et al., 2023). A generated summary may seem clinically plausible but can simultaneously introduce unsupported claims, unverifiable source attributions, or reasoning that goes beyond the underlying patient record (Bedi et al., 2026) (Alu & Oluwadare, 2026).
This synthetic methodological case study examines a registry-style maternal health setting. Clinical registries often contain asymmetric missingness, where variables like length-of-stay, interpreter utilization, care-transition status, or historical baselines may be unavailable, inconsistently recorded, or not comparable across patient cohorts (D. Mahamadou et al., 2025) (Sayres et al., 2026). These structural gaps matter for deployment as an LLM may still generate continuous prose even when the source contains uncertainty or absence. In an unconstrained workflow, this can cause the model to smooth over missing data with confident but insufficiently verified assumptions about patient risk, care-transition status, or cohort-level context (Vasilev et al., 2025).
The deployment risk is therefore not limited to obvious hallucination. A summary can be factually plausible yet remain audit-unsafe if its evidence trail cannot be verified. This framework isolates two failure modes that may emerge under sparse registry conditions: 
•	Quote Stitching: where the model constructs citation-like evidence by joining non-contiguous source text, section labels, or list fragments (Wang et al., 2026);
•	Unsupported Comparative Reasoning: where the model introduces cohort-level judgments, median comparisons, baseline statements, or relative-risk framing that does not appear in the individual source record (Bedi et al., 2026) (Asgari et al., 2025).
In both cases, the issue is not only whether the summary “sounds correct,” but whether its claims and reasoning can be traced to the available evidence.
Rather than estimating population-level error rates or validating clinical performance, this study demonstrates a pre-deployment audit workflow for clinical LLM summaries. The proposed architecture serves as a zero-trust gate that routes generated outputs to summary-only use, human review, or halt decisions before downstream workflow exposure.

## Zero-trust audit pipeline

The audit architecture treats an LLM-generated clinical summary as a target artifact instead of a directly deployable clinical document. The pipeline is data-origin agnostic: it can be applied to real, de-identified, or synthetic registry-style records, as long as the source record, generated output, expected schema, and governance rules are available. The auditor does not need access to the Generator model's training data, internal weights, or proprietary configuration, exhibiting a practical deployment setting where outputs must be evaluated independently of the model provider.

The workflow converts a registry-style record into a structured summary artifact containing summary text, atomic claims, declared source fields, evidence snippets, missingness notes, and preliminary routing metadata. This design shifts evaluation away from paragraph-level fluency toward claim-level checks of traceability, evidence consistency, and deployment risk. 

![Figure 1](zero_trust_architecture.png.png)
