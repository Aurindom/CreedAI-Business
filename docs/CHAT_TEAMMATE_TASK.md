# Chat teammate: backend connection and useful follow-up choices

Assigned by Aurindom on 2026-11-07. Build on your own machine and existing personal branch. This extends your chat UI task; the Codex sandbox worker has been stopped so there is no competing implementation. Claude continues the main backend queue and a separate discovery/MCP worker. Codex verifies; Aurindom judges.

Read `../TEAMMATES handoff.md` for setup and the proposed chat/SSE contract. This document is self-contained within the Git repo; you do not need Aurindom's private parent-folder memory files. These instructions define work to do, not a claim that live chat/backend endpoints already exist.

## 1. Start from the shared baseline

Fetch and merge the latest `origin/aurin-test` into your existing branch, preserving your work. The last baseline inspected for this assignment was `cc92a61`; do not assume that remains the newest contract. Record the commit you actually use. Do not switch branches on Aurindom/Claude's shared checkout, reset other work, or force-push.

Use the documented sibling `sandbox/` layout. Put experiments, virtualenv/cache/temp files, tests' generated output, logs and sample transcripts under your own `sandbox/teammate-chat/`. Do not commit these artifacts or use real owner data/keys. Browsing and mock chat need no paid API.

## 2. Work ownership

- You own `frontend/src/chat/`: chat panel, message state, event renderer and replaceable mock/HTTP adapters. Teammate A owns `App.jsx`/shared styles and adds the agreed panel mount point.
- You may build a small isolated Python chat-orchestration module under your local `sandbox/teammate-chat/`. Inject resolver/recommender adapters so it can be checked without modifying shared backend code. This does not duplicate catalog matching or price calculation.
- Propose finalized source as an isolated new module, e.g. `backend/app/chat_bridge/`, in a focused PR after agreeing the contract with Claude. That namespace is proposed until ownership is recorded; avoid competing implementations.
- Claude owns shared `schemas.py`, `matching.py`, catalog, persistence, `main.py`, `frontend/src/api.js`, real `/api/chat` registration, model/provider/Hermes and discovery integration. Request changes there rather than editing them in parallel.
- No direct model/Hermes/MCP calls from the browser. No credentials in frontend state, prompts or commits. Do not start Azure resources, paid calls or the other workers' services.

## 3. Preserve the existing contract

The proposed browser request is `POST /api/chat` with `conversation_id`, `message` and `profile`. It is not yet an implemented endpoint. The adapter receives events through `onEvent` and resolves when finished.

Existing event types:

| type | Required purpose/fields |
|---|---|
| `status` | Progress `text` |
| `message_delta` | Assistant `text` |
| `clarify` | `question` and `choices` |
| `recommendation` | `problem_id` and `profile`; cards use the ordinary recommendation API |
| `sources` | `items` with title, URL, checked date |
| `error` | Safe `code`, `message`, `retryable` |
| `done` | End the turn and restore input availability |

Create example fixtures labeled MOCK. Document any proposed structured choice IDs, action intent, alternative references or custom-draft payload as ADDITIVE and agree the shape with Claude before connecting consumers. Do not silently change event names or teach the frontend to compute prices/eligibility. A conversation ID is a correlation handle, not proof of identity or authority over saved data.

Current ordinary APIs: `/api/tasks/resolve` accepts bounded task text; `/api/recommend` accepts `profile` and `problem_id`; `/api/tools/{id}/facts` returns checked/unknown display facts. Profile supports `owned: [{tool_id, plan}]`. Check the source/current API for exact shapes. Start with injected fixture adapters in the Python bridge; integration adapters later call/reuse these application operations through Claude's chosen boundary. A working deterministic bridge is a separate milestone from a live model conversation.

## 4. Conversation behavior to implement

1. Understand/confirm the task. Render ambiguous or negated statements as clarification, rather than assume the first mentioned problem is the requested one. Store explicit owner choices; do not pretend scripted fixtures understand arbitrary language.
2. Collect missing plan information through structured choices. Use sourced tiers supplied by the backend, plus 'I do not know'. A typed legacy/custom label is unverified; the backend decides whether it establishes feature access. Do not ask a plan question for a source-backed single offering. Recompute when context changes.
3. If the task is covered by an existing subscription, retain the reuse recommendation but offer useful next choices: setup help, compare alternatives, discover more or design a custom aid. 'No new tool needed' must not end the conversation or hide the owner's unresolved workflow difficulty.
4. Show up to two checked same-task alternatives ONLY when the backend returns them. Preserve pending/unknown status, task/channel fit, relevant plan costs and overlap/switching caveats. Several owned tools must not falsely imply there are no independent alternatives; tell Claude if the backend contract cannot yet expose the required pool. No fabricated near-score percentages or new numeric product scores.
5. If there are no suitable alternatives, say so. Discovery can be mocked with a visible Demo label, or shown unavailable until integrated; never call it live or claim a search occurred when it did not.
6. On owner selection, offer a constrained custom-assistant draft: purpose, input fields/schema, expected output, approved knowledge, limits and a sample. Explain review, sample testing and setup steps. Draft instructions do not mean a tool was saved, connected or deployed. No arbitrary executable scripts, banking/account credentials or automatic third-party actions.
7. Keep private persistence outside this bridge until Claude's ownership/access boundary is ready. State can be explicit caller-supplied turn context for the isolated demo; do not claim persistent secure sessions.

Do not force another subscription or custom build when reuse works. The owner can still explore alternatives. Owning an accounting product does not prove a general statement like 'my books are behind' is solved; ask about the specific gap when necessary.

## 5. Reliability and acceptance checks

Use focused behavioral checks, with outputs in your sandbox:

- Clear task produces a recommendation reference; ambiguity requires an explicit selection before proceeding.
- A missing/legacy plan does not produce a frontend-invented included/$0 claim. Changing the plan changes the request and refreshes the result.
- An inclusion result still offers follow-up choices; available backend alternatives appear; absent alternatives are not invented.
- Pending products and unknown costs retain their labels. An alternative pair is not presented as a bundle the owner should buy together.
- Custom aid is produced only after the owner chooses it, with bounded validated draft data and honest draft status.
- Empty input, invalid/stale choice, double send, cancellation and backend unavailable are handled. An error halfway through the stream does not leave the panel stuck loading. Each completed turn emits `done` once; cancellation never claims a completed private action.
- The HTTP adapter handles event boundaries split across chunks and friendly error events. Drop/ignore stale turn responses so a prior answer cannot overwrite a newer one.
- Stream only allowed fields; do not forward raw tool previews, arbitrary backend objects, stack traces or private tokens. Report limits honestly; no promise of perfect generic secret detection.

No paid call is required for these checks. Label simulated delays, responses and discovery as mocks. Stop any service you start and report its port/status; do not stop teammates' services.

## 6. Integration and return report

First deliver a small agreed contract/examples PR or message to Aurindom/Claude; then build independently. Main Claude can continue W05 and discovery while you work. Bring changes back through a focused PR into `aurin-test`, following Aurindom's merge directions; do not merge/deploy automatically.

Your report should include source baseline, exact files, a short rationale, a before/after conversation example, commands/check results, what is mocked versus backend-connected, unresolved dependencies and the exact changes Claude must connect. Keep raw traces in sandbox. Do not claim live AI, discovery, saving or external deployment unless actually implemented and verified.

Claude/Codex review the adapter against the latest W05 response. Main Claude registers the backend route and connects real provider/discovery functions only at their approved gates. Teammate A/B connect the UI. If integration fails, browsing remains available and chat shows a clear temporary-unavailable state. Preserve the prior working path and document how to revert the new adapter.

Customer reviews, star ratings and sentiment bars remain future work after stability.
