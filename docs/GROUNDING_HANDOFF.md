# Grounding checkpoint for teammate integration

2026-11-07. This checkpoint adds backend grounding modules and quality tests,
not a public chat endpoint or login implementation. Coordinate shared-file changes
with the backend integrator; preserve each teammate's branch work.

## Entry points

- app.agent.evidence.build_request_evidence: resolve owner text; matched task uses
  existing recommendation rules, ambiguous input asks for clarification, unfamiliar
  input offers outcome/browse/custom-workflow next steps without an invented match.
- app.agent.evidence.build_evidence: server-side validated owner profile/task IDs
  to approved claims and source metadata; optional compare delegates to existing
  complementary-stack/addon deduplication logic.
- app.agent.prompts.SYSTEM_PROMPT: versioned claim-selection prompt.
- app.agent.grounding.validate_answer: plain JSON or one outer JSON fence, strict
  schema/reference/winner/context validation, backend rendering and grouped source
  URLs. Model prose cannot introduce factual claims alongside valid citations.
- app.agent.grounded_runtime.grounded_runtime: one buffered generation callback
  to existing W09 events. Use the SAME LeakGuard instance with run_turn. No raw
  model JSON, tool preview, credential or internal run ID belongs in browser output.

Never accept owner_id from model output as authorization. Incoming owner context
must come from validated login/session state. Teammate Redis login and Google
A2UI/chat work will be inspected after merge; this checkpoint does not assume
their final contracts. Test isolation/ownership before linking private saved plans.

## Evidence obtained

- Complete backend regression: 478 passed, one warning at this source checkpoint.
  See backend/evals/README.md for execution with outputs under sandbox.
- Dataset: 30 versioned policy scenarios plus adversarial output, invariance,
  citation, fence, business-context and exact-fragment guard checks.
- Bounded paid tests with Haiku4.5 exercised format/grounding, safe search failure,
  general-purpose fit, missing business context and graceful unfamiliar requests.
  Known local sample spend USD0.021701, not a provider/team-wide balance.
- Separate LOCAL actual Hermes v0.23.0 + MCP experiment, mock model: catalog
  success, structured failure, injected fake-secret interception and cancellation
  passed. Experiment code/state is intentionally not promoted in this commit.

Pinned-runtime integration findings: tool.completed is not proof of business
success; it has limited preview/error metadata. Use a trusted backend action
result. MCP filter syntax is mcp_servers.<server>.tools.include, not include_tools;
resources/prompts require explicit settings. Verify actual advertised tools.
The sandbox used mcp-marketplace as toolset and disabled deferred tool_search
for a one-tool direct-schema test, not as a general product discovery policy.

## Remaining work and boundaries

- Merge teammate changes, resolve conflicts, then inspect Redis login and A2UI/
  chat contracts. Test server-validated owner/conversation/run/call metadata after
  login is understood; no second owner identity system should be built in parallel.
- Production Hermes adapter needs authenticated MCP access and owner/session/run/
  call-bound action-result records with expiry. Do not copy mock shared-file
  receipts into public authorization. No public Hermes or host-tool exposure.
- Real web-search/fetch discovery is not proved by existing-catalog model tests.
  Connect the retained discovery pipeline, preserving pending-review provenance.
- Free-plan prices still need source-backed usage-limit qualification. Grounding
  guarantees fidelity to supplied catalog records, not their factual completeness.
- Langfuse is deferred until AFTER Hermes, Azure and teammate UI/chat integration.
  No cloud provisioning/deployment or new paid test authorized by this handoff.
- Prompt-injection teammate assignment: docs/PROMPT_INJECTION_CHECK.md. Offline
  tests first; do not overwrite shared backend modules in parallel.

Local runtime transcripts, credentials, SQLite data and failure logs are excluded
from this checkpoint. Ask the integrator for sanitized evidence where needed;
do not add generated sandbox artifacts to Git.
