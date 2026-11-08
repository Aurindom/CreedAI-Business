# Claude resume: continue Wxx on the integrated Penny/Supabase baseline

2026-11-07. Read the latest `aurin-test` commit containing this document. Record
the exact SHA before starting. Penny and Supabase are implemented in source;
do not reapply the old sandbox patch or restart the initial app/W09 build.

## Current checkpoint

697 backend tests /23 frontend tests /build passed. Real first-account login,
plan persistence, immediate app logout rejection, five-minute history recovery
and actual expiry passed. Integrated signed-in/guest Penny passed real provider
checks. Read AUTH_PENNY_INTEGRATION_REVIEW.md for scope/costs/limitations.

Auth production hardening belongs to the human teammate under
PRODUCTION_AUTH_TEAMMATE_HANDOFF.md: second real account still signupHTTP429,
SMTP/redirect configuration, auth verification performance and release evidence.
No production deployment occurred. Do not treat this as an account isolation,
live discovery, Hermes private-receipt or deployed capacity guarantee.

## Next Wxx work and division

1. **W10 identity-bound Hermes/MCP integration:** inspect existing auth.Principal,
   access.account_owner and chat integration. Plan server-owned user/business/
   conversation/run/tool-call bindings and expiring action receipts. Private
   authority must never come from a model field or frontend ID. The current
   read-only public catalog path must continue for guests.
2. **W08/W10 real discovery:** inspect the existing finder/storage/MCP contract
   and retained discovery-worker context. Continue the same implementation;
   do not build a competing finder. Complete independent fixtures/contracts,
   then present the bounded live-source/provider scan for direction.
3. **W12 evidence and submission:** update source-to-architecture mapping, two
   business journeys, unfamiliar/no-match and failure cases, what was manual vs
   platform-discovered, and the 16-week continuation plan. Prepare the video/judge
   walkthrough in parallel with independent source work.
4. **W11 assistant/tracker:** retain scope but only proceed after core discovery,
   agent integration and private authorization are stable. No duplicate chat
   runtime or ungrounded assistant. Discuss schedule conflicts before displacing
   the required core prototype/video work.

W01-W09 have substantial implementation; verify a concrete defect before
rebuilding one from historical queue descriptions. Earlier parent memory/queue
baselines such as65 tests or untracked app files are superseded by this checkpoint.

## Existing runtime evidence and limits

Pinned Hermes v0.23.0 was previously exercised locally with an injected mock model
and HTTP MCP: success, structured failure, fake-secret blocking and cancellation
passed. That experimental registry/auth scaffolding was not promoted. It does
not prove paid-model reasoning, web discovery, user isolation or production load.
`tool.completed` previews are not trusted action receipts. Preserve explicit
business success/failure even when the model turn reports completion.

Use current approved claims/grounding/selection logic for all factual output;
no raw model prose or arbitrary tool previews. Current Penny uses direct
OpenRouter tool calls, not a secretly connected Hermes adapter. New runtime work
must preserve the already-tested account/guest and failure behavior.

## Coordination and gates

Work on your own branch from this pushed baseline. Own isolated agent/MCP adapter
files, discovery contract work and tests. Coordinate `main.py`, `db.py`, `schemas.py`,
`chat.py` and frontend/API event changes with the auth teammate and one integrator.
Do not edit their auth/history/plan files concurrently or create another login.

Local read-only inspection, reversible code and offline/mock tests may continue.
Before a new actual Hermes start/configuration, live discovery source/provider
call, paid-model batch or Azure execution, give Aurindom the concrete path,
unanswered question, exact files, acceptance checks and resource/cost bounds.
Reuse an existing exact authorization when it clearly applies; do not assume old
completed paid batches automatically repeat. No blanket reset/ours/theirs or
force-push. Share progress in concise dated evidence reports.

Azure account/VM selection and deployment remain separate gates. Langfuse remains
after Hermes/Azure/teammate integration. Private services must not become public
to make the demo work. No unrelated tools, new paid accounts or broad load sweep.

Aurindom is final judge. Codex verifies delivered checkpoints. This file is a
resume instruction, not a claim that Claude has been remotely started or that
messages have been sent to a teammate.
