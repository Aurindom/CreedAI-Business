# Grounding evaluation

`grounding_cases.json` is a versioned set of 30 product-neutral scenarios that test
how Arkadio picks and cites tools. The expected outcomes exercise the real matching
policy, not a separate ranking rule written for the tests. More adversarial cases
live in `tests/test_grounding_quality.py`.

## Running it

From `backend/`, with the dev requirements installed:

```
python -m pytest tests/test_grounding_quality.py tests/test_agent_turn.py -q
```

No model is called. The model's side of the turn is faked, so the run is free and
deterministic.

## What the 30 scenarios cover

- Five task families: calls, bookkeeping, appointments, marketing and staff scheduling.
- Existing, unknown, upgrade and add-on plans.
- Restricted versus general applicability, and unfamiliar business types.
- Estimates, missing prices, budget boundaries, missing channel evidence and no-match requests.

The tools and tasks in the dataset are synthetic test data, not catalog entries.
The set is chosen boundary coverage, not every possible combination. Separate
invariant checks rename products, reverse catalog order and insert an irrelevant
zero-cost tool, and the policy decisions must not change.

Unrecognized requests get an invitation to browse tasks or outline a custom
workflow, with no product winner. Ambiguous requests get task choices instead of a
forced pick. No-match requests keep the honest uncertainty and offer next steps.

| Dimension | Evidence |
|---|---|
| Recommendation and ownership | Outcomes for three business types, an unfamiliar business, existing plan, unknown plan, upgrade, pending and no match |
| Grounding and citations | Unknown or incorrect claims, mismatched source IDs and request-package mismatches are rejected |
| Pricing fidelity | Source-backed rendering, explicit estimate wording, unchanged comparison and add-on dedup |
| Relevance | The model has no free-prose field. Unsupported advice, support and feature fields are rejected |
| Failure behavior | An unavailable package yields no products or winners, only a safe browse or retry reply |
| Prompt injection | Raw summaries and notes never become answer statements. The model cannot add instructions as prose |
| Output boundary | The raw response is buffered. Invalid model output never reaches the streamed text |
| Leak coverage | A fake split canary is injected into the runtime stream and the rendered output. A refusal alone does not count as interception |

## How the boundary works

The server builds an evidence package from the validated owner profile and task
IDs. The model gets the system prompt plus that package and returns JSON. The
runtime buffers it, validates it and renders only approved claims. The model can
pick statements and one allowed follow-up. It cannot write its own factual prose.
The same leak guard checks both the stream and the final output.

## Limitations

- Passing these checks does not prove the catalog's facts are true, that the ranking is optimal, or that answers are useful to a person.
- Exact-match leak protection does not catch encoded or spaced-out secrets, so credentials are never given to the model.
- Real vendor-source accuracy, live discovery yield and natural-language quality need their own evaluations. The 30 synthetic scenarios do not measure them.
- For the deployed app, `scripts/api_canary.py` runs live checks against a real URL. It calls the model and costs money, so run it with a budget in mind.
