# TEAMMATES handoff

Written 2026-11-07 for the two teammates joining the build. Everything you need is in this file. You don't need any notes outside this repository.

Hackathon deadline: **Sunday 2026-11-08, 11:59pm** (10-minute video plus a prototype link judges can test).

## 1. What the app is

Main Street AI is a marketplace of AI tools for small business owners who aren't technical. An owner picks a business type (optional) and a problem, like "the books are behind". The app shows tools that solve it, with sourced facts (price, setup effort, privacy, support), and it can honestly say "you don't need a new tool". It also checks whether a set of tools overlaps.

The rules the whole team follows:
- **No invented facts.** Every price or claim shown to an owner comes from the backend, with a source link and the date it was checked. The UI never makes up or computes a score, a rating or a price.
- **Browsing works without AI.** The chat agent is a second way in. If the agent is down, the normal browse and compare screens still work.
- **No recommendation logic in the frontend.** The backend picks and ranks. The UI only shows what it gets.

## 2. What works today, and what doesn't

Works (backend and frontend talk to each other):
- Business type picker, 7 category tabs, 12 problem cards, a tool directory of 24 tools.
- `POST /api/recommend` returns a route per tool (already have it, check your plan, add-on, new tool, and so on), the fit, the added monthly cost and four sourced facts.
- `POST /api/compare` compares up to 3 tools for the chosen tasks, on the same prices as the cards (W05).
- `POST /api/stack/check` finds overlapping tools and adds up the known entry prices (older, see below).
- Private saved plans (W06): an owner starts a private session with no account, saves an adoption plan from a comparison, and reopens it later. See "Saved plans (W06)" below.
- 220 backend tests, last run passing on 2026-11-07.

Not built yet:
- **No chat UI and no live agent.** The chat contract in section 6 is a proposal.
- No live discovery, no MCP integration, no custom assistant or setup wizard.
- No plan picker in the UI yet. The backend and `api.js` are ready for it (see "Plan picker" below).
- No results tracker. No plan screens in the UI yet (the backend and `api.js` are ready).

Known data and logic gaps (Claude is fixing these on the backend, so don't work around them in the UI):
- 16 of the 24 tools are `pending_review` (8 are `verified`). Their facts haven't been rechecked yet. Since 2026-11-07 the backend never makes a pending tool the winner, and every option carries `status`. The card doesn't show it yet (teammate A).
- Several prices are unknown (Podium, Square, Toast, 7shifts, and the billing period for Slang AI).
- `PLAN.md` is the product plan. `TEAM_HANDOFF.md` only points here. Where anything disagrees with this file, this file wins.

This is a working prototype, not a finished product.

## 3. Setup

### Folder layout

Clone the repo next to a folder called `sandbox`. The frontend config writes its build and cache output to `../../sandbox` relative to `frontend/`, which is that sibling folder.

```
my-workspace/
  hackathon-app/      <- this repo
  sandbox/            <- test DBs, logs, build output, caches. Never committed.
```

### Prerequisites

- Python 3.11 or newer (tested on 3.14).
- Node 20.19 or newer, enforced by `engines` in `package.json` (tested on Node 24, npm 11).
- Git.
- **No API key is needed** to run browse mode.

### Backend (port 8000)

Bash:
```
cd hackathon-app/backend
python -m venv ../../sandbox/venv
source ../../sandbox/venv/bin/activate        # Windows Git Bash: source ../../sandbox/venv/Scripts/activate
pip install -r requirements-dev.txt
APP_DB_PATH=../../sandbox/dev.db python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

PowerShell:
```
cd hackathon-app\backend
python -m venv ..\..\sandbox\venv
..\..\sandbox\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
$env:APP_DB_PATH = "..\..\sandbox\dev.db"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Check it: open http://127.0.0.1:8000/api/health. You should see `{"status":"ok"}`. API docs are at http://127.0.0.1:8000/docs.

`requirements.txt` holds only what the server needs at runtime, all pinned. `requirements-dev.txt` adds the test tools (pytest, httpx). Install the dev file locally; a deploy installs only `requirements.txt`.

On every start the backend loads `backend/data/catalog.json` into a SQLite file. Always set `APP_DB_PATH` into the sandbox. Without it the DB lands in `backend/data/app.db` (it's git-ignored, but keep it out of the repo anyway).

Environment variables (names only, there are no secrets here):
- `APP_DB_PATH`: where the SQLite file goes.
- `CATALOG_PATH`: optional, a different catalog file to load.

### Frontend (port 5173)

```
cd hackathon-app/frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Vite sends every `/api/...` request to the backend on port 8000, so start the backend first. `npm run build` writes to `../../sandbox/frontend-build`.

### Stopping

Press Ctrl+C in each terminal. To start fresh, delete `sandbox/dev.db`. It's rebuilt from the catalog on the next start.

### Backend tests

From `hackathon-app/backend`, with the venv active:
```
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider --basetemp=../../sandbox/test-run
```

## 4. Who owns what

| Who | Owns | Doesn't touch |
|---|---|---|
| **Teammate A, UI** | Owner screens: business profile, problem picker, option cards, compare view, the plan picker, showing pending review status. Integrates `frontend/src/App.jsx` and `frontend/src/styles.css`. | `backend/`, `frontend/src/chat/` |
| **Teammate B, chat agent UI** | A visible chat panel for agentic chats: conversation state, messages, loading and progress, errors, a retry button, and a **mock chat adapter**. Everything goes under `frontend/src/chat/`. | `backend/`, `App.jsx` (except the one mount point A adds for you), `api.js` |
| **Claude** | Backend: matching, pricing, catalog, schemas, API contracts, and later the real `/api/chat` endpoint, discovery, MCP and the agent. Also `frontend/src/api.js`, which mirrors the backend contracts. | Teammate components, unless asked |
| **Codex** | Reviews and tests. | Doesn't make parallel app edits |
| **Aurindom** | Final call on everything, plus all commits to `aurin-test`, merges and deploys. | |

Rules that keep us from colliding:
- Only one person edits a shared file. `App.jsx` and `styles.css` belong to A. `api.js`, the schemas, the catalog and matching belong to Claude.
- Teammate B builds the chat as a self-contained component, for example `<ChatPanel />` in `frontend/src/chat/ChatPanel.jsx`. A adds the single line that mounts it in `App.jsx`, and you agree on where it sits.
- If you need a new field or endpoint, ask Claude (through Aurindom). Don't add it on your side and don't compute it in the UI.
- The tool's custom assistant and setup wizard aren't assigned yet. They come after the core path.

## 5. Current API (checked against the source on 2026-11-07)

All endpoints are JSON. Errors come back as `{"detail": "..."}`, for example `404 {"detail": "unknown problem: nope"}`.

| Method and path | What it returns |
|---|---|
| `GET /api/health` | `{"status": "ok"}` |
| `GET /api/trades` | Business types: `[{"id": "auto", "name": "Auto shop"}, ...]` (19 of them, examples only, not a gate) |
| `GET /api/categories` | `[{"id": "calls_messages", "name": "Calls and messages", "capabilities": ["phone_answering", "lead_response"], "labels": {"phone_answering": "answering phone calls", ...}}, ...]` (7). Use `labels` wherever an owner would otherwise see a capability id. |
| `GET /api/problems?trade=&category=` | Problem cards: `{"id": "bookkeeping", "title": "The books are behind", "plain_words": "...", "capability": "bookkeeping", "trades": ["all"]}` |
| `GET /api/tools?trade=&capability=&category=` | Full tool records (see below). Business type only changes the order. |
| `GET /api/tools/{tool_id}` | One tool record |
| `GET /api/tools/{tool_id}/facts` | The same four display facts a recommendation card shows (see "Display facts"). Use this for the comparison table so cards and comparison read the same. |
| `POST /api/recommend` | A recommendation (see below) |
| `POST /api/compare` | Task-aware comparison and stack cost (W05, see below) |
| `POST /api/stack/check` | Older overlap and entry-price check (see below) |
| `POST /api/sessions`, `DELETE /api/sessions/current` | Start or close a private session (W06) |
| `GET /api/plans`, `POST /api/plans`, `GET /api/plans/{id}`, `POST /api/plans/{id}/refresh` | Private saved plans (W06, see below) |

### Fact shape

Every fact on a tool looks like this. If `status` is `unknown`, show "unknown", never a guess.
```json
{"status": "present", "value": 38, "source_url": "https://quickbooks.intuit.com/pricing/",
 "source_type": "vendor", "checked": "2026-11-06", "note": "..."}
```

A tool record has `id, name, url, trades, applicability, applicability_source, status, summary, entry_monthly_usd, entry_plan, entry_billing, plan_tiers, plan_prices, offering, setup_effort, privacy, support_stability, connects_to, capabilities`. `status` is `verified`, `pending_review` or `rejected`. Here `pending_review` means our team hasn't rechecked the facts yet. It has nothing to do with customer reviews.

Plan facts, all optional and all sourced like any other fact:
- `plan_tiers`: plan names from cheapest to dearest. `plan_prices`: a map from those names to monthly prices, on the same billing basis as `entry_billing`.
- `offering`: `single` when the vendor sells one thing with no plans (Google Business Profile). Then no plan warning is shown. A free price alone doesn't count.
- Each capability can carry `included_from` (the lowest plan that includes it) or, for add-ons, `addon_from` (the lowest plan that can add it).

A new buyer is priced at the plan the feature needs, never the cheapest plan by default. If that plan or its price isn't sourced, `added_monthly_usd` is `null` and `cost_note` says what to check with the vendor.

### POST /api/recommend

Request:
```json
{
  "profile": {
    "trade": "hvac",
    "owned": [{"tool_id": "jobber", "plan": "Core"}],
    "budget_monthly_usd": 100
  },
  "problem_id": "bookkeeping"
}
```
Every field in `profile` is optional. `owned[].plan` is how the plan picker sends the owner's plan. The old `owned_tool_ids: ["jobber"]` still works.

Response (real output, cut down):
```json
{
  "problem_id": "bookkeeping",
  "outcome": "new_tool",
  "winner_tool_id": "quickbooks_online",
  "message": "QuickBooks Online covers this but overlaps what you have. Weigh the move first.",
  "tailored": false,
  "tailoring_note": "Nothing we've checked is built just for your kind of business, so these are offered to many kinds of business.",
  "options": [{
    "tool_id": "quickbooks_online",
    "tool_name": "QuickBooks Online",
    "status": "verified",
    "route": "switch",
    "fit": "any_business",
    "fit_note": "The vendor offers this to many kinds of business",
    "added_monthly_usd": 38.0,
    "cost_note": "Simple Start plan, before processing or hardware fees",
    "facts": [{"label": "Entry price", "known": true, "state": "known", "value": "$38/mo, Simple Start plan",
               "note": "...", "source_url": "https://quickbooks.intuit.com/pricing/",
               "source_type": "vendor", "checked": "2026-11-06"}]
  }],
  "check_first": [],
  "set_aside": [{"tool_id": "...", "tool_name": "...", "status": "verified", "reason": "..."}]
}
```
- `outcome`: `no_new_tool`, `add_on`, `new_tool`, `verify_with_vendor` or `no_match`.
- `route`: `already_have`, `check_plan`, `native_add_on`, `plan_upgrade`, `compatible_tool`, `separate_tool` or `switch`.
- `fit`: `you_use_it`, `made_for`, `any_business` or `unconfirmed`.
- `status`: `verified` or `pending_review`. Show a visible "not yet rechecked" badge on every pending card, in options, check_first and set_aside. A pending option is never the winner, so `winner_tool_id` is `null` when the top option is pending. Don't show a green or "recommended" style on a pending card. For `any_business`, say "offered to many kinds of business", not "works for any business".
- `added_monthly_usd` can be `null`, which means the cost is unknown. Show "unknown", not $0.
- `within_budget`: `true`, `false` or `null`. It compares `added_monthly_usd` (what the option adds to the bill, not the total bill) with `budget_monthly_usd`. `null` means no budget was given or the cost is unknown. Show `null` as "cost unknown", never as fitting. When a budget is given, show `budget_note` once near the results so the owner knows what is compared. If the winner goes over budget, `message` already says so.
- `check_first` holds options we can't confirm yet. Show them apart from the confident options.

### Display facts

Each item in `options[].facts` and in `GET /api/tools/{id}/facts` is `{label, known, state, value, note, source_url, source_type, checked}`. `state` is one of:
- `known`: sourced. Show the value, a link to `source_url` and the `checked` date.
- `not_checked`: nobody has looked yet. Show "Not checked yet".
- `unresolved`: someone looked and couldn't confirm it. Show "Unknown" plus `note` (the reason), and the link and date if present.

Don't merge `not_checked` and `unresolved` into one "unknown" style. Today the comparison builds its own text from the raw tool record and shows "Not checked yet" for both, which is the gap to close.

### Plan picker (W03, for the owner screen)

The backend and `frontend/src/api.js` are ready. The picker itself goes in `App.jsx`.
- Beside each owned tool, add an optional plan select. Options are `planChoices(tool)` (the sourced `plan_tiers`, cheapest first) plus "I do not know" as the default, value `PLAN_UNKNOWN`.
- If `isSingleOffering(tool)` is true (Google Business Profile), show no plan input at all. The vendor has no plans, so there's nothing to ask.
- If `planChoices` is empty for any other tool, don't show a select. A short optional text box for an old or custom plan name is fine, capped at `PLAN_LABEL_MAX` (100) characters. Label it "Not checked by us" and never show a typed name as a checked plan.
- Keep plans in state keyed by tool id, for example `{jobber: "Core"}`, so changing the trade, tab or problem doesn't wipe them.
- Build the request with `ownedProfile(trade, ownedIds, plans)`. It sends `owned: [{tool_id, plan}]`, turns blanks into "I do not know", and drops plans for tools that are no longer owned.
- Re-run the recommendation when a plan changes. The answer depends on it: a Lite owner can get `plan_upgrade` while a Max owner gets `already_have` for the same feature.
- A missing, unknown or unmatched plan always gives `check_plan` with `added_monthly_usd: null`, even for a feature on the vendor's cheapest plan, because an old plan may predate it. Never show that as $0 or "included".
- Don't add scores or stars.

### Problem splits (facets, W04)

Some problems split by the kind of work, for example lead replies by channel (phone or website chat) and scheduling by work type (jobs at the customer's place or booked appointments). This is all catalog data, never code:
- `GET /api/problems` cards may carry `requires`, for example `{"work_type": "appointments"}`, and `phrases` (used by the task search). Nothing to show for either.
- A tool only counts for a card with `requires` when a sourced fact confirms it handles that value. Otherwise it lands in `check_first` with a `fit_note` like "Not confirmed it handles website chat. Check with the vendor", and it can't win. Show `fit_note` as is.
- Any new split, card or tool goes through the same rule. Don't special-case a problem or a tool in the UI.

### POST /api/tasks/resolve (W04)

Turns an owner's own words into a problem card, for the search box and the chat. No model call: it only matches the catalog's `phrases`. Use `api.resolveTask(text)`.

Request `{"text": "I need to book appointments online"}` (1 to 300 characters, not blank, otherwise 422). Response:
```json
{"status": "matched", "problem_id": "appointment_booking",
 "choices": [{"id": "appointment_booking", "title": "Booking appointments takes too long", "...": "full problem card"}],
 "message": "Sounds like: Booking appointments takes too long."}
```
- `matched`: one card. Go straight to its recommendation.
- `ambiguous`: `problem_id` is `null`. Ask the owner to pick from `choices`, best guess first. Never act on it without the owner's click. It happens when:
  - a bare word fits several cards ("schedule"),
  - the sentence names two needs ("my books are a mess and I miss calls", "I answer calls fine but invoices are late"),
  - the need sits in a negated part ("I don't need help answering calls; I need bookkeeping"). Negated cards come last.
  - With only ONE choice, the message says "Did you mean ...? Please confirm." Show it as a yes/no confirm, not a list.
- `unsupported`: `choices` is empty. Show `message` and the normal problem list. Never guess. Typos ("invocies") and single vague words ("phone") land here today.

### Problem icons

`App.jsx` has a `problemIcons` map keyed by problem id, with a generic fallback. New cards (`appointment_booking`, `website_chat_leads`) get the fallback. To keep the UI free of per-problem code, it's better to key icons by category id (7 fixed tabs) or ask Claude for an `icon` field on the card. Teammate A's call.

### POST /api/stack/check

Request `{"tool_ids": ["quickbooks_online", "jobber"]}`, response:
```json
{"duplicates": ["QuickBooks Online and Jobber both cover sending invoices and getting paid"],
 "known_monthly_usd": 87.0, "total_monthly_usd": 87.0, "unknown_cost_tools": []}
```
`total_monthly_usd` is `null` if any tool's price is unknown. This adds **entry** prices with no task context, so it can disagree with the cards. For the comparison screen and plan preview use `/api/compare` below. Duplicates now use plain labels ("both cover sending invoices and getting paid").

### POST /api/compare (W05)

Request, with the same `profile` you send to `/api/recommend`:
```json
{"profile": {"trade": "hvac", "owned": [{"tool_id": "quickbooks_online", "plan": "Simple Start"}], "budget_monthly_usd": 150},
 "problem_ids": ["job_scheduling", "bookkeeping"],
 "tool_ids": ["jobber", "housecall_pro"],
 "assignments": {"job_scheduling": "jobber"}}
```
Limits: 1 to 5 `problem_ids`, 1 to 3 `tool_ids`, no repeats (422). Unknown ids give 404.

`assignments` is optional (`api.compare(profile, problemIds, toolIds, assignments)`). It maps a chosen task to the chosen tool the owner picked for it. Use it when two tools fit the same task and the owner picks one. A task or tool outside the selection, or a tool that isn't a usable fit for that task, gives `422`.

Readiness, one rule everywhere (W05 fix):
- `confirmed`: the tool lists the task, the fit applies, and our team has rechecked the tool.
- `possible`: it might fit, but something still needs checking (pending review or unconfirmed fit). Never show it as checked or ready.
- `excluded`: set aside. Don't offer it for that task.
- An unknown price is never 0 and never "within budget".

Response:
- `tools[]`: one per chosen tool, in the order sent.
  - `role`: `fills_gap` (holds a task, confirmed), `might_fill_gap` (holds a task that still needs checking), `alternative` (fits the same task as another chosen tool and nothing is assigned yet), `not_needed` (fits, but the task went to another tool, so it isn't counted) or `no_fit`. Show `role_note`.
  - `tasks[]`: one per chosen task the tool lists. `standing` is `eligible`, `check_first` (say why with `reason`) or `set_aside`. `coverage` is `confirmed`, `possible` or `excluded`. `route`, `added_monthly_usd` and `cost_note` are exactly what that tool's recommendation card shows.
  - `facts`: the same four display facts as the cards.
- `tasks[]`: one per chosen task. `kind` is `covered`, `possible`, `alternatives` or `gap`. Show `note`.
  - `candidate_ids`: every chosen tool that could take the task. Use these for a "pick one" control.
  - `assigned_to`: the tool that holds it, or `null` for alternatives and gaps.
  - `suggested`: `true` when we picked it because that tool is already needed for another task (lowest added cost, then the order sent). Show it as a suggestion the owner can change, not a decision.
- `overlaps[]`: plain sentences. Shared features are possible overlap, never proof two tools do the same job.
- `connections[]`: one per pair of chosen tools, plus chosen-to-owned pairs. `state` is `listed` (a vendor's sourced list names the other tool, see `listed_by` and `sources`) or `unverified`. Don't show `unverified` as compatible. Even `listed` doesn't say what data moves or which way, and `note` says so.
- `stack`: `null` when any task is still `alternatives`, because alternatives are not a bundle. Show `stack_note` instead ("Pick one per task first") and let the owner pick from `candidate_ids`, then call compare again with `assignments`. Otherwise it is built only from the assigned tasks, so each task is paid for once:
  - `lines[]`: one per tool, `monthly_usd` for all its tasks together. A plan shared by two tasks is charged once. Add-ons are charged once per recorded vendor offer. If we haven't recorded whether two add-ons are one purchase or separate, `monthly_usd` is `null` and `note` says so. `confirmed` is `false` if any of its tasks is only `possible`.
  - `known_monthly_usd`, `total_monthly_usd` (`null` if anything is unknown, never treated as 0), `unknown_cost_tools`.
  - `ready`: `true` only when every price is known, every line is confirmed and every chosen task is covered. `unconfirmed[]` names the tools still to check. `uncovered[]` names the chosen tasks no chosen tool covers. Then the total is only a subtotal for the covered part, and `assumptions` says so. Don't call a stack "checked" or "ready" unless `ready` is true.
  - `within_budget`: only set when `ready` is true and a budget was given, otherwise `null`. When not ready, `assumptions` says what the priced parts come to, as a conditional number.
  - `assumptions[]`: show these under the total (fees not included, annual billing, tools still to check).
- `stack_note`: always present. Says each task goes to one tool, mentions suggestions, tools still to check and tasks nothing chosen covers.
- `all_in_one[]`: up to 3 catalog tools that list every chosen task, for comparison only (`tool_id`, `tool_name`, `status`, `coverage`, `monthly_usd`, `note`). They are never swapped into the owner's choice and we never claim they save money. Show `all_in_one_note` with them. When nothing in the catalog lists all the tasks, the list is empty and the note says a wider search isn't available yet. Only filled when 2 or more tasks are chosen.

The adoption plan (W06) takes this structured `stack`, not the prose.

### Saved plans (W06)

No accounts. `api.js` has `startSession`, `endSession`, `plans`, `savePlan`, `plan`, `refreshPlan` and `newRequestId`. Each private helper takes the token as its first argument.

1. `POST /api/sessions` gives `201 {"token": "...", "expires_at": "..."}` (30 days). The token is shown only once and the server keeps only a hash of it. Send it as `Authorization: Bearer <token>`. Keep it on the device (for example `localStorage`) and tell the owner that clearing the browser loses access. Never put it in a URL, a log or a chat prompt.
2. `POST /api/plans` with the same body as `/api/compare` (including `assignments`, last argument of `savePlan`) plus `request_id` (8 to 100 letters, digits, `-` or `_`). Make one with `newRequestId()` when the owner presses Confirm and reuse it for retries, so a double click returns the same plan (`200`) instead of a second one (`201` the first time).
3. The response is the saved plan:
   - `steps[]`: one per tool being bought. `tasks`, `reasons`, `monthly_usd` (`null` = unknown) with `cost_note`, `setup` (the sourced setup fact), `facts`, `to_confirm[]` (open questions the owner should ask the vendor) and `to_try[]` (what to test before paying). We have no recorded setup steps, so none are invented.
   - `gaps[]`: chosen tasks nothing in the plan covers. `connections`, `stack` and `note` ("This plan is guidance. Nothing is bought, connected or set up for you."). Show `note`.
   - `status`: `checked` (nothing left open), `draft` (see `open_items[]`: gaps, suggested assignments, tools to check, unconfirmed prices) or `legacy` (saved before this change). Show a draft as a draft with its open items, never as a checked plan. Each step has `coverage` (`confirmed` or `possible`).
   - A legacy plan still loads. `GET` reports it as `changed`, and Refresh rebuilds it with a real status.
4. `GET /api/plans/{id}` returns `{"plan": ..., "changed": bool, "change_note": "...", "current_total_monthly_usd": ...}`. The saved estimate never changes on its own. If `changed` is true, show `change_note` and a Refresh button that calls `POST /api/plans/{id}/refresh`. `GET /api/plans` lists summaries for the session.
5. Errors: `422` a bad body, including an assignment outside the selection or to a tool that doesn't fit. `401` missing, ended or closed session (start a new one). `404` a plan that isn't in this session, including someone else's. `409` alternatives not yet narrowed to one per task, a `request_id` reused for a different selection, the 20-plan cap, or a refresh that today's catalog can't rebuild. `503` private plans are switched off on this server (`PRIVATE_PLANS=off`).

## 6. PROPOSED chat contract (not built, use the mock)

**New assignment, 2026-11-07:** Teammate B should read [CHAT_TEAMMATE_TASK.md](docs/CHAT_TEAMMATE_TASK.md). Aurindom assigned the isolated chat bridge/connection work to the teammate on their own machine; the Codex worker has been stopped. The guide gives file boundaries, current/proposed contracts, owner-plan/alternative/custom-draft behavior and acceptance checks. Claude retains shared backend/route and provider integration ownership. This extends the existing chat work without changing the event contract below.

Nothing in this section exists on the backend yet. Claude builds the real endpoint later. Teammate B builds against a mock with exactly this shape, so switching to the real one only means changing the adapter.

### The adapter

`frontend/src/chat/chatAdapter.js` exposes one function:
```js
sendMessage({ conversationId, message, profile }, onEvent) // returns a Promise that resolves when done
```
- `createMockAdapter()` gives scripted replies with small delays, plus one error case you can trigger (for example, the message "fail").
- `createHttpAdapter()` will later call `POST /api/chat`. It isn't wired until the backend exists.
- Choose between them with `import.meta.env.VITE_CHAT_MODE` (`mock` by default). When mock mode is on, show a clear "Demo mode" label in the panel.
- The chat never holds a provider key and never talks to a model or the agent runtime directly. Everything goes through our FastAPI backend.

### Request (proposed)

`POST /api/chat`
```json
{"conversation_id": "c_123", "message": "I keep missing calls while I'm on a job", "profile": {"trade": "hvac", "owned": []}}
```

### Streamed events (proposed, one JSON object per server-sent event)

| `type` | Fields | What the UI does |
|---|---|---|
| `status` | `text` | Shows progress, e.g. "Searching the catalog" |
| `message_delta` | `text` | Adds text to the assistant's reply |
| `clarify` | `question`, `choices[]` | Shows quick-reply buttons |
| `recommendation` | `problem_id`, `profile` | Renders option cards by calling the existing `api.recommend(profile, problem_id)`. The chat never builds its own cards or prices. |
| `sources` | `items[]` with `title`, `url`, `checked` | Shows the citations |
| `error` | `code`, `message`, `retryable` | Shows a friendly error, plus a retry button if `retryable` |
| `done` | | Turns the input back on |

The panel must handle: a slow reply (keep a loading state), an error in the middle of a stream, a double send (block it while one is running), an empty message, and an "agent unavailable" state that points the owner back to browsing.

If you want a fixture file, put it at `frontend/src/chat/fixtures/mockConversation.json` and label it as mock data.

## 7. Branches and pull requests

1. Wait until Aurindom tells you the snapshot commit on `aurin-test` has been pushed. He'll post the commit SHA.
2. `git fetch origin`
3. On **your existing personal branch**, bring in the snapshot without losing your own work:
   ```
   git checkout <your-branch>
   git merge origin/aurin-test
   ```
   Fix any conflicts by hand. If you're not sure, ask before you resolve them.
4. Keep pull requests small, and open them **into `aurin-test`**. Say what changed and how you checked it.
5. If you change a shared shape, tell the others before the code that depends on it changes.

Don't do any of these: force-push, reset a shared branch, merge into `main`, deploy, or share secrets or `.env` files. Never commit `sandbox/`, `node_modules/`, virtualenvs, `*.db`, logs, screenshots or `.env`.

## 8. Acceptance checks before you open a PR

- Backend `/api/health` returns ok, and one browse, recommend and compare path works in the browser.
- `npm run build` succeeds (output goes to the sandbox).
- Backend tests still pass if you touched anything they cover.
- Mock or demo modes are clearly labeled on screen.
- Pending review tools still show their status, and unknown prices show as unknown.
- No generated files (DBs, builds, logs, caches) in your diff.
- In the PR, list the checks you actually ran. Don't say a check passed if you didn't run it.

## 9. Money and keys

Browse mode and the chat mock cost nothing. Live model calls will go through one shared OpenRouter key with a **$25 total budget for the whole team**. Don't make any paid calls without Aurindom's okay. Customer reviews, star ratings and sentiment bars are deliberately left out of this release.

## 10. W07: reliability helpers and same-origin serving

Backend and `api.js` are done. `App.jsx` has not been changed, so nothing below is used by the UI yet.

### 10.1 Cancel and "latest request wins" (`frontend/src/api.js`)

Every `api.*` method now takes an optional `AbortSignal` as its **last** argument. Old calls work unchanged. Examples: `api.compare(profile, problemIds, toolIds, assignments, signal)`, `api.tools(trade, category, signal)`, `api.trades(signal)`.

`latestOnly()` makes a runner. Make one runner per thing that can change quickly (task search, business type, selection). A new call cancels the previous one, and an old answer can never overwrite a newer one.

```js
const runCompare = useRef(latestOnly()).current

async function refresh() {
  setLoading(true)
  try {
    const result = await runCompare((signal) => api.compare(profile, problemIds, toolIds, assignments, signal))
    if (result.stale) return          // a newer request exists, ignore this one
    setComparison(result.value)
  } catch (error) {
    showError(error)                  // see 10.2
  } finally {
    setLoading(false)                 // only safe if you don't need to keep the spinner for the newer call
  }
}
```

Note on the spinner: when a result is stale, a newer request is still running. Don't clear loading in that case. Return before `finally` clears it, or keep a counter.

Also pass your own `AbortController().signal` in a `useEffect` cleanup if you only need cancel on unmount. `isAbort(error)` tells you an error is just a cancel and should be ignored.

### 10.2 Errors the UI can show

All thrown errors are normal `Error` objects whose `message` is safe to show.

| Case | message | Extra fields |
| --- | --- | --- |
| Backend down or no network | "We can't reach the server right now. Check your connection and try again." | `offline: true`, `cause` |
| 5xx | "Something went wrong on our side. Please try again in a moment." | `serverError: true`, `status`, `detail` |
| 4xx | `"<status>: <detail>"` as before | `status`, `detail` |
| Cancelled | browser `AbortError` | use `isAbort(error)` |

Suggested use: if `error.offline`, show the message with a Retry button. For 5xx, show the message and keep `error.detail` out of the screen (it is for console or support). Nothing retries automatically. A POST that timed out may have been saved, so the retry must be a user click, and plan saves reuse the same `request_id` so a repeat is safe.

### 10.3 Build and serve same-origin

```
cd hackathon-app/frontend
npx vite build --outDir ../../sandbox/frontend-build/w07 --emptyOutDir
```

Then point the backend at that folder and start it:

```
FRONTEND_DIST="<absolute path to the build folder>" python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`. No Vite proxy is needed. If `FRONTEND_DIST` is not set, the backend looks for `frontend/dist` (the default `npm run build` output). The folder must contain `index.html`, otherwise the API runs alone as before.

Rules the server follows:
- Real files in the build folder are served as is. Anything outside the folder cannot be reached.
- Any other GET path without a file extension returns `index.html` (so refreshing a client-side route works).
- A missing file with an extension, for example `/assets/old.js`, is a plain 404, not the page.
- `/api` is never replaced by the page. An unknown `/api/...` path returns JSON `{"detail": "Not Found"}`.
- The folder is checked on each request, so a new build shows up without restarting.

### 10.4 Server errors

Any unhandled backend error returns `500` with `{"detail": "Something went wrong on our side. Please try again in a moment."}`. The stack trace goes to the server log only (logger `app.web`).

### 10.5 What is and is not connected

Connected and tested (backend tests, 13 new in `backend/tests/test_w07_serving.py`):
- Same-origin serving of a built frontend, SPA fallback, `/api` JSON 404, path traversal blocked, no-dist behaviour, generic 500.
- `api.js` signal support, `latestOnly`, offline and 5xx errors. The Vite build passes. These helpers have not been run in a browser and have no frontend unit tests (the project has no frontend test runner).

Not connected yet:
- `App.jsx` does not use signals, `latestOnly`, or `error.offline`. Rapid input changes can still let an old response win until teammates wire it in.
- Loading, empty, retry and unavailable screens are UI work and are not built.
- Keyboard and phone checks are not done.
- No Docker, Azure, HTTPS or deployment files. Cloud work is gated.
- No mock data is involved in any of this.

## 11. Estimated prices (added 2026-11-07)

Some vendor pricing pages don't say plainly which number is the monthly price, so we had to read it with some guessing. Those prices are now marked and never treated as confirmed. Today that's Jobber ($49 Core) and Housecall Pro ($79 Basic).

### 11.1 New fields
- Any fact can carry `"inferred": true`. It is always `present` and its `note` says what was guessed. Older facts without the field mean `false`.
- `/api/tools/{id}/facts`: each fact has `inferred`. An estimated price's `value` ends with "(estimate)", like "$49/mo, Core plan (estimate)".
- `/api/recommend` options and `/api/compare` task fits have `price_estimated`. The price is still shown, `cost_note` ends with "check the vendor's pricing page", and `within_budget` stays `null`.
- If the top option's price is an estimate, the outcome is `verify_with_vendor` with no winner, and the message names the tool and says to check its pricing page.
- `/api/compare` stack: each line has `price_estimated`, and `stack.estimated[]` names the tools with estimated prices. The total is still added up, but `ready` is `false`, `within_budget` is `null`, `assumptions` has a line about it and `stack_note` ends with "Prices to check on the vendor's page".
- `all_in_one[]` entries have `price_estimated`.
- `/api/stack/check` has `estimated_cost_tools[]`.
- Saved plans: a plan with an estimated price is a `draft`, with an open item like "Part of Jobber's price is our estimate. Check the vendor's pricing page".

### 11.2 What the UI should do
- Show an estimated price with a small "estimate" label and a link to the fact's `source_url`, never as a confirmed price or within budget.
- Never call a stack "ready" or a plan "checked" while `stack.estimated` has anything in it. The backend already enforces this.
