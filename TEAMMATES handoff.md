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
- Business type picker, 7 category tabs, 10 problem cards, a tool directory of 24 tools.
- `POST /api/recommend` returns a route per tool (already have it, check your plan, add-on, new tool, and so on), the fit, the added monthly cost and four sourced facts.
- `POST /api/stack/check` finds overlapping tools and adds up the known monthly cost.
- 65 backend tests, last run passing on Aurindom's machine.

Not built yet:
- **No chat UI and no live agent.** The chat contract in section 6 is a proposal.
- No live discovery, no MCP integration, no custom assistant or setup wizard.
- No plan picker in the UI yet. The backend and `api.js` are ready for it (see "Plan picker" below).
- No saved plans or results tracker.

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
| `GET /api/categories` | `[{"id": "calls_messages", "name": "Calls and messages", "capabilities": ["phone_answering", "lead_response"]}, ...]` (7) |
| `GET /api/problems?trade=&category=` | Problem cards: `{"id": "bookkeeping", "title": "The books are behind", "plain_words": "...", "capability": "bookkeeping", "trades": ["all"]}` |
| `GET /api/tools?trade=&capability=&category=` | Full tool records (see below). Business type only changes the order. |
| `GET /api/tools/{tool_id}` | One tool record |
| `GET /api/tools/{tool_id}/facts` | The same four display facts a recommendation card shows (see "Display facts"). Use this for the comparison table so cards and comparison read the same. |
| `POST /api/recommend` | A recommendation (see below) |
| `POST /api/stack/check` | Overlap and cost check (see below) |

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

### POST /api/stack/check

Request `{"tool_ids": ["quickbooks_online", "jobber"]}`, response:
```json
{"duplicates": ["QuickBooks Online and Jobber both cover invoicing"],
 "known_monthly_usd": 87.0, "total_monthly_usd": 87.0, "unknown_cost_tools": []}
```
`total_monthly_usd` is `null` if any tool's price is unknown.

## 6. PROPOSED chat contract (not built, use the mock)

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
