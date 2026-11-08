# Penny, Hermes, MCP and Discovery: fixes and end-to-end evidence

Validation date: **2026-11-08**. Application release: **468cdf5**, pushed to
`origin/aurin-test` and deployed on Azure as `penny-app:468cdf5`.

Live application:
https://mainstreet-penny-aurin.belgiumcentral.cloudapp.azure.com

## Were real OpenRouter end-to-end tests run?

**Yes, in both the sandbox and Azure deployment.** These were application API
requests using the production Docker image, actual Hermes, actual MCP executor,
actual gateway and real OpenRouter responses and reported usage. Separate offline
and fake-provider tests are identified below.

The two live execution paths are:

```text
Penny /api/chat -> Hermes -> public MCP get_tool_details -> persisted receipt
                -> model gateway -> OpenRouter -> backend validation -> UI/SSE

Discovery /api/research -> OpenRouter web search -> independent official-page fetch
                       -> automatic evidence verification -> catalog/audit storage
```

Hermes uses the gateway for model calls and MCP for public catalog reads during
the run. The backend verifies the stored reads before delivering an answer.
Discovery is a separate API workflow with its own provider ledger; it does not
need to pass through Hermes or MCP. Both paths were exercised live.

The tested model was `anthropic/claude-haiku-4.5` through OpenRouter.

## Fixes and their descriptions

| Issue | Cause and change | Main files |
|---|---|---|
| Review-replies starter fell back | The resolver treated “never get around to” as a refusal and confused getting reviews with replying. The earlier idiom fix is retained; every exact catalog example now maps to its own task, with valid owner excerpts passed into routing. | `backend/app/tasks.py`, `penny_grounding.py`, `chat.py` |
| Seven other built-in examples misrouted or lacked evidence | The catalog descriptions, phrase matcher and grounding excerpt rules did not agree. Exact normalized catalog sentences now have an explicit deterministic contract. Added appointment/customer-list phrases and corrected “getting” stemming. | `backend/data/catalog.json`, `tasks.py`, `tests/test_catalog_contract.py` |
| Login absent from the production frontend | Vite builds had no public Supabase settings even though the backend had them. BuildKit supplies the auth settings from a secret mount; the builder exports only the public URL and publishable/anon key. Service-role/secret keys are rejected. | `deploy/Dockerfile`, `compose.prod.yml`, `frontend/scripts/build-deploy.mjs` |
| Linux containers could not read source files | A restrictive checkout umask produced mode0600 files. Docker preserved those modes, but the app runs as a non-root user. Normalize public source/static permissions and test non-root imports and file reads during image build. | `deploy/Dockerfile` |
| Hermes lost MCP tools after dependency updates | Replacing MCP/gateway containers left the existing Hermes process with stale tool registration. A paid request reached OpenRouter with an empty tools array; the backend rejected it as `tool_missing`. Dependency restart propagation and an explicit post-update Hermes refresh now restore registration. | `deploy/compose.prod.yml`, `scripts/deploy_vm.sh` |
| Health checks looked good while chat failed | Process health alone did not prove a usable tool-attached model request. Deployment acceptance now requires actual canary answers, persisted MCP outcomes and gateway accounting in addition to readiness. | `scripts/api_canary.py`, `docs/RELEASE_GATE.md` |
| Validation diagnostics were missing | Application INFO events were not visible under the production logging setup. JSON logging now exposes fixed validation/routing codes through an explicit extra-field allowlist. | `backend/app/logging_config.py`, `deploy/logging.json` |
| Scanner probes returned HTTP200 | Extensionless paths such as `/.git/HEAD` fell through to the React shell. Proxy and backend reject sensitive/probe paths with404, preserving legitimate pages and assets. These responses had not exposed host SSH/Git files. | `deploy/Caddyfile`, `backend/app/web.py` |
| Future updates could repeat integration failures | Added a reusable offline gate, catalog/starter route contracts, production-image build checks, a bounded live canary and a SHA-checked VM deployment script. | `scripts/release_gate.py`, `scripts/api_canary.py`, `scripts/deploy_vm.sh` |

Exact canonical examples do not override arbitrary user refusals. Additional
negation/wrappers do not inherit a catalog sentence's meaning. General wording
still goes through phrase matching and bounded semantic routing. The grounding
checks remain enforced.

## How actual tool completion is verified

The backend registers required reads before dispatch. A response is accepted only
when the MCP executor stored success for the expected run, tool and arguments,
the result hash matches the expected/current catalog data, and execution finished
within its deadline. A model saying “done,” a `success` boolean in untrusted text,
or Hermes emitting `run.completed` does not establish that an action happened.

Forged MCP receipt tests returned `tool_missing` and produced no validated answer.
The next legitimate request succeeded. One historical pending read from an earlier
rejected hosted run remains in the audit database and is not counted as success.

## Test results

| Environment and test | Result and scope |
|---|---|
| Offline backend/frontend/build | **1,091 backend tests, 36 frontend tests, production frontend build passed.** These tests alone do not establish live provider behavior. |
| Real sandbox API matrix | **22/22 journeys passed**, including all12 catalog examples, greeting/context, confirmation, business correction, multiple needs, explicit negation, resumption, unknown QuickBooks plan and Mailchimp exclusion. |
| Final sandbox image | Four live canaries passed after the final application changes. The image used the production Compose topology with isolated native volumes. |
| Azure real API canaries | Reviews, appointment booking, explicit negation and greeting all passed with validated answers after the final deployment workflow. |
| Real browser | The reviews starter returned Google Business Profile; one click produced one chat POST. Sources/caveats and PDF worked; zero page errors. Azure browser sign-in/sign-out with the real Supabase QA account passed. |
| Real authenticated Penny | Account A identity, live model response, private Redis history, guest denial, logout/revoked-token denial and recovery passed in sandbox and Azure. |
| Live discovery | Both environments ran two real scans: catalog24->27->28, all IDs unique, five automatic-verification audit rows. Repeat scans updated existing entries and found an additional new vendor. |
| Automatic verification | Official-page evidence was checked and unresolved plan/pricing notes retained. **No newly discovered live candidate passed full automatic promotion.** Positive promotion is covered by offline fixtures. |
| Sandbox concurrency | Real app/Hermes/MCP with a fake provider: five requests produced three validated replies and two fast busy refusals; all21 browse probes returned200. No provider spend. |
| Azure real concurrency | Five real requests produced three validated replies (~12.7-12.9s) and two busy refusals (~0.4s); all31 browse probes returned200. |
| Actual outages in both environments | MCP, Hermes and gateway were stopped/restored individually. Readiness503, browsing200, safe chat refusal, zero model forwards and recovery all passed. Errors inside HTTP200 SSE streams were inspected explicitly. |
| Persistence | Azure synthetic saved plan, Redis history and discovered catalog survived app/Redis restart. The sandbox catalog also persisted across restarts. |
| Post-outage Azure canary | The exact reviews sentence validated again in6.63s, confirming actual model/tool recovery rather than just a green health endpoint. |
| Secret isolation | Compiled JS contains the public Supabase settings and no internal/OpenRouter credentials. Secret/runtime files were excluded from Git and Docker context. |

## Cost, limits and cleanup

| Scope | Settled provider calls | Recorded cost |
|---|---:|---:|
| Sandbox gateway |66|USD0.370003|
| Sandbox discovery/verification |7|USD0.046737|
| Azure gateway |39|USD0.193202|
| Azure discovery/verification |7|USD0.046747|
| **Combined checkpoint** |**119**|**USD0.656689**|

Azure totals include the earlier four failed-host calls costing USD0.017578.
Additional work beyond that starting balance was115 calls/USD0.639111. Fake-provider
charges are excluded. No live charges were held and no final gateway trip remained.
These are local test ledgers, not the team-wide OpenRouter account balance.

Azure's approved combined lifetime ceiling is split into **USD4 for chat/gateway
and USD1 for discovery**. The app reservation ledger is finite, one worker admits
three simultaneous chat turns, and discovery has a12-provider-request cap plus
public research rate/concurrency limits. Ledgers were preserved, not reset.

Sandbox test containers were stopped; their native volumes and evidence remain.
The Azure application remains running. The original Caddy hotfix is preserved in
Git stash and settings/database/ledger snapshots were retained before updating.

## Remaining boundaries

- Real Account B still cannot sign in. Two-real-account isolation requires the
  teammate to create/confirm it and run the committed two-account checker.
- Production SMTP and confirmation/password-reset redirect journeys still need
  their own verification. Existing-account password login has passed.
- Provider-key rotation remains with its owner. Azure managed backups, monitoring
  alerts and Key Vault setup are separate infrastructure work.
- New discovery candidates with incomplete evidence remain pending. Scheduled
  discovery and rendered-page/pricing-table verification remain deferred as W14.
- These passing tests cover the recorded cases and failure scenarios; they do not
  guarantee every future phrasing, third-party outage or teammate merge.

## Future teammate merge procedure

Start from the tested integration line, review one branch diff at a time, run
`python scripts/release_gate.py`, build the production image and test its actual
service contracts. Deploy only an approved SHA with
`bash scripts/deploy_vm.sh APPROVED_SHA`. Run the free API checks, then the bounded
`scripts/api_canary.py --live` batch, and inspect MCP receipts and provider usage
before accepting the update. Keep the previous image and persistent data available
for rollback; never roll a ledger back to manufacture budget.

## Evidence locations

The coordinating workspace retains sanitized reports under
`sandbox/release-gate/`: `accounting.json`, `live-result-*.json`, discovery/auth/
browser/concurrency/outage results, and the corresponding `azure-*` reports and
deployment logs. Full offline logs/JUnit are under this checkout's ignored
`sandbox/release-gate/20261108-184336/`. These private workspace artifacts are not
part of the Git release.

Related committed documents: `RELEASE_VALIDATION_2026-11-08.md`, `RELEASE_GATE.md`,
`PRODUCTION_DEPLOY.md`, and `PRODUCTION_BUDGET.md` in this directory.
