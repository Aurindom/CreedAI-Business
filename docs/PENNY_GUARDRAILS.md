# Penny guardrails and owner-phrase checks

These controls add defense in depth for OWASP LLM01 (prompt injection), LLM02 (sensitive information), LLM05 (output handling), LLM06 (agency), LLM07 (prompt leakage), LLM09 (misinformation), and LLM10 (consumption). This is not a certification or complete mitigation of the OWASP Top 10.

Reference: https://genai.owasp.org/llm-top-10/

## Boundaries and tests

| Requirement | Implementation | Regression coverage |
|---|---|---|
| Ignore/reveal-prompt attacks | Screen current message, history, and free-text profile fields before calling a model; repeat at the agent boundary | `test_chat_guards.py`: instruction override, prompt disclosure, role delimiters, hidden and zero-width text |
| Untrusted vendor/tool instructions | Inspect catalog brief, action arguments, action results and events; withhold suspicious results before model/UI use | `test_chat_guards.py`: HTML comments, hidden elements, Unicode formatting, poisoned tool name |
| Contact data | Block common email addresses and 10-15 digit phone formats in chat input/history/profile and model output; browser validates before appending messages to session history | Backend contact-data tests and UI interaction checks |
| Proxy-aware rate limiting | Trust X-Forwarded-For only from configured proxy CIDRs; walk right-to-left to the first untrusted hop; malformed chains fall back to the peer. Apply per-minute limits to validation and model chat routes, and retain the model route's daily cap | Proxy-chain, spoof-prefix, direct-client, Retry-After, expiry, and memory-cap tests |
| Content-free audit logs | Emit `penny_guard_block` with fixed `guard_reason` and `guard_source` fields only | Assert record contains neither submitted text nor contact details |
| Owner-facing note | Expandable "What Penny will not do" in the chat, with buying/connecting/payment/privacy boundaries | UI interaction check asserts the note exists |
| Typos and slang | Narrow reviewed aliases retain clause boundaries and negation; unknown words are not broadly fuzzy-matched | 48-case `owner_phrases.json` regression set, plus existing task tests |

## Hosting proxy setup

Run Uvicorn with `--no-proxy-headers` so the application can validate the actual immediate peer rather than a server-rewritten client address. The proxy must overwrite/append X-Forwarded-For using its observed client address. Restrict direct backend access to the proxy.

Set `CHAT_TRUST_PROXY=1` and `CHAT_TRUSTED_PROXY_CIDRS` to the actual immediate proxy network(s), comma-separated. Do not trust all IPv4/IPv6 addresses, arbitrary public traffic, or an entire hosting network without an ingress restriction. With no valid trusted CIDR, forwarded headers are ignored.

`CHAT_REQUESTS_PER_MINUTE` defaults to 30 requests per source address. Browser validation and live chat each count as requests. `CHAT_DAILY_MESSAGES` retains the daily model-message limit. Both in-memory limiters fail closed when their tracking table is full. Deploy one worker for these process-local limits; multiple workers/VMs need a shared limiter or an equivalent ingress limit before scaling. No hosting configuration was provisioned by this change.

Audit records use Python logging, so configure the host to retain the fixed event fields; do not enable request-body, header, or raw model-prompt capture in APM/proxy logs. This application does not control a hosting provider's logging settings.

## Limits and privacy

Pattern checks are deliberately bounded heuristics. They do not detect every injection, encoding, translated instruction, or category of personal data. Common obfuscated/local phone formats and spelled-out emails can require additional detection. Continue to enforce allowed actions, checked catalog facts, source/date checks, provider budgets and caps, and React's escaped text rendering. Unknown prices remain unknown.

Blocked new messages stay out of browser conversation history and model requests; the draft input remains visible so the owner can edit it. If old saved history contains contact data, start a new chat. Validation failures fail closed and do not silently fall back to a model or an alternative reply path. No private-plan token is included in chat context.

## Phrase benchmark and answer quality

`backend/tests/fixtures/owner_phrases.json` has 48 representative cases. Two phrases came from the task request. The rest are labeled synthetic examples of everyday owner wording; they are not fabricated claims of customer interviews. Replace/extend them with consented, anonymized owner feedback when available.

Cases cover all 12 task cards, typos/slang, negation, multiple needs, and unsupported work. A negated outcome is conservatively confirmed instead of assumed. The live instruction set asks for one relevant follow-up, reuses known plan/budget context, and distinguishes an added budget from the current bill. The live reply instructions have been proofread for plain wording. Scripted chat and its keyword fallback have been removed. No model retraining or paid generation is required for the checks below.

Run after every matcher/prompt change from `backend` with the isolated environment:

```
python -m pytest tests/test_owner_phrases.py tests/test_tasks.py tests/test_chat_prompts.py tests/test_chat_guards.py tests/test_chat.py -q -p no:cacheprovider --basetemp=../../sandbox/penny-checks
```

Run `npm test` from `frontend` for the owner-facing note, blocked-message history, and validation-outage checks. Then run the complete backend suite and frontend production build. Model calls in backend tests are mocked; prompt text checks do not guarantee the wording of every live-model response. Live answer quality needs a separate reviewed evaluation before claiming measured accuracy.


## Current provider and answer contract

Penny uses OpenRouter only, pinned to `anthropic/claude-haiku-4.5`. The retained
`anthropic_chat.py` adapter is legacy test code and is not selected by public chat.
The backend token/key remains server-side. `CHAT_SPEND_CAP_USD` defaults to 0.10;
its persistent reservation ledger is not an account-wide provider hard stop.
Missing/invalid usage retains the reservation and stops the turn. No paid repair
loop runs after invalid selection.

The model selects `claim_ids` and an optional supported `followup_id` through
`submit_answer`. Request-specific schemas enumerate approved IDs. The backend
adds required context and winner support, binds the current evidence package and
citations, then validates and renders the text. Model prose, prices, invented IDs,
extra policy fields and submissions mixed with actions are rejected. Validation
logs contain fixed status/reason codes, not raw owner/model content.

Signed-in requests carry a Supabase token in the HTTP header; the backend derives
account/session identity. Guests receive no account authority. Identity IDs and
credentials do not enter the model prompt. Logout is checked before model rounds
and outgoing frames. The UI aborts requests and resets private context on account
changes. See ACCOUNT_CHAT_A2UI.md for account/cache/plan behavior.

The check suite uses mocks; real provider evidence is documented separately in
AUTH_PENNY_INTEGRATION_REVIEW.md. Passing fixtures does not verify fresh vendor
truth, universal model compliance, deployment capacity or every attack encoding.
