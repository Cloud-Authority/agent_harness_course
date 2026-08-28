---
name: supplier-risk-scoring
description: Combine validated evidence, sanctions status, supplier tier, and remediation state into an explainable deterministic risk score and route.
tools: [calculate_supplier_risk]
---

# Supplier risk scoring

## When to use

Use this procedure after freshness and sanctions results are available.

## Steps

1. Pass only sandbox-verified freshness and sanctions outputs to `calculate_supplier_risk`.
2. Add risk for each blocking and material finding using the published calculation in the tool contract.
3. Keep the component scores and reason codes in the output.
4. Route a blocking result to remediation and a named owner; never let a numeric score bypass a blocking rule.
5. Give the drafting model the score as evidence, not as editable prose.

## Output

An overall score, risk band, route, blocking controls, and explainable score components.
