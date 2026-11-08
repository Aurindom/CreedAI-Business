# Grounding quality evaluation, dataset version 2

Final integrated-release note (2026-11-08): the 30 scenarios below passed as part
of the 1,261-test backend gate. Current Penny/Hermes/MCP wiring and real Azure API
evaluation evidence are in `docs/FINAL_MAIN_VALIDATION.md` and its sanitized JSON
artifact. Historical statements below about unwired runtime/UI adapters describe
the original patch, not the final main application. For the deployed application,
use `python scripts/api_canary.py --base-url <HTTPS_URL> --live --edges` from the
repository root with an explicitly approved finite budget. The older direct
runtime evaluation CLI is not evidence for native Hermes/MCP execution.

Run from the workspace parent using the installed sandbox interpreter. Set
`PYTHONDONTWRITEBYTECODE=1` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. All runtime
output must remain in sandbox:

```powershell
& sandbox/dep-check-venv/Scripts/python.exe -m pytest hackathon-app/backend/tests/test_grounding_quality.py hackathon-app/backend/tests/test_agent_turn.py -q -p no:cacheprovider --basetemp=sandbox/codex-grounding/pytest-review --junitxml=sandbox/codex-grounding/review.xml *> sandbox/codex-grounding/review.log
```

`grounding_cases.json` is a versioned product-neutral scenario dataset. Expected
outcomes exercise the real matching policy, rather than a new chat ranking rule.
Additional adversarial cases live in test_grounding_quality.py. The JUnit result
retains individual cases; do not equate the total pass count with real-model or
live-site quality.

The dataset now contains 30 scenarios: five task families (calls, bookkeeping,
appointments, marketing and staff scheduling), existing/unknown/upgrade/add-on
plans, restricted versus general applicability, unknown businesses, estimates,
missing prices, budget boundaries, missing channel evidence and no-match cases.
Its synthetic tools/tasks are test data, not new production catalog capabilities.
This is deliberately selected boundary coverage, not all possible combinations.
Separate invariant checks rename products, reverse catalog order and insert an
irrelevant zero-cost tool. Their expected policy decisions must remain unchanged.

build_request_evidence uses the existing task resolver. Unrecognized requests
get an outcome-oriented invitation to browse available tasks or outline a custom
workflow, with no product winner. Ambiguous requests get task choices rather than
a forced recommendation. Choices are navigation/clarification, not a claim that
they solve the original request. No-match requests retain the honest uncertainty
while offering next steps. This backend adapter still needs teammate chat wiring;
the existing public task-resolver endpoint/UI has not been changed in this patch.

Future expansion should add observed failures, withheld review examples and
complementary-task/source/pricing coverage, rather than simply more industry names.
Actual vendor-source accuracy, live discovery yield and natural-language quality
are separate evaluations. The 30 synthetic scenarios do not establish those.

Review dimensions separately:

| Dimension | Evidence |
|---|---|
| Recommendation/ownership | scenario outcomes for three business types, unfamiliar business, existing plan, unknown plan, upgrade, pending and no match |
| Grounding/citations | unknown/incorrect claims, mismatched real source IDs, request-package mismatch rejected |
| Pricing fidelity | source-backed rendering, explicit estimate wording, unchanged policy comparison/addon dedup; broader unit handling remains in W08 pricing tests |
| Relevance | model has no free-prose field; unsupported advice/support/feature fields rejected |
| Failure behavior | unavailable package has no products/winners and only a safe browse/retry response |
| Prompt injection | raw summaries/notes excluded from answer statements; model cannot add instructions as prose |
| Output boundary | raw response buffered; invalid model prose never enters W09 text frames |
| Leak coverage | fake split-canary injected into runtime stream and rendered output; refusal alone does not count as interception |

Usage: build an EvidencePackage server-side with build_evidence using the validated
owner profile and task IDs. Send SYSTEM_PROMPT plus this package to the model.
grounded_runtime buffers the returned JSON, validates it and renders approved
claims through existing run_turn events. Supply the same LeakGuard instance to
both boundaries. default_answer is an offline baseline, not a substitute for
measuring real model compliance. Do not stream raw model JSON to a browser.

This patch adds a reusable backend boundary; it does not wire the teammate UI,
introduce a public chat route, configure Hermes or fetch official websites.
Eligibility, routes and comparison totals remain the existing backend's decisions.
Source metadata comes from stored catalog facts, not fresh independent verification.
Applicability sources without check dates are labeled accordingly. The model can
select statements and one allowed followup, not write arbitrary factual prose.
Output is text; frontend integration must render it as text, not untrusted HTML.

Limitations: deterministic fidelity does not prove the catalog's factual truth,
optimal ranking, arbitrary natural-language entailment, or human usefulness.
Exact-match leak protection does not catch encoded/spaced-out secrets; credentials
must never be supplied to the model. Broader free-text chat/custom-tool generation
and actual live discovery require their own integration/evaluation scope.

For Claude verification: inspect evidence selection and source provenance, verify
that a model cannot attach a valid citation to changed text, test allowed outputs
as well as rejection paths, and check the explicit uncertainty of estimates.
Use the latest shared memory for paid-test state before any provider call.
