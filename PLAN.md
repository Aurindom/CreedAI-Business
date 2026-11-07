# Product plan

Working name: Main Street AI (placeholder). Updated 2026-11-07.

For setup, contracts and who owns what, read [`TEAMMATES handoff.md`](TEAMMATES%20handoff.md). If this file and the handoff disagree, the handoff wins.

The full target design, including the agent runtime and security, is in [`docs/architecture.md`](docs/architecture.md).

## Goal

A marketplace that helps small business owners who aren't technical find, compare and adopt AI tools. It's organized by task, like missed calls, scheduling or bookkeeping. Any kind of business can use it. Business type is an optional filter, and the business types in the catalog are examples, not a gate.

The app may honestly answer "you don't need a new tool". It never invents facts, prices or scores.

**Submission:** Sunday 2026-11-08, 11:59pm. A 10-minute video plus a prototype link judges can test.
**Finalists notified:** 2026-11-16, 12pm.
**In-person finals:** 2026-11-17, 5-8pm.

## Owner journey

| Step | What the owner gets |
|---|---|
| Describe the business | Optional business type, budget and the software they already pay for |
| Pick a problem | Plain-language problem cards grouped into category tabs |
| See eligible tools | Tools that do the job, labeled "made for your business", "works for any business" or "check first" |
| Compare | Four sourced facts per tool (entry price, setup effort, privacy, support), each with a link and the date it was checked |
| Build a stack | Only complementary tools. A second tool is added only when it fills a real gap, works with the first, and the total cost makes sense. Duplicates are flagged |
| Adopt | Setup steps for the chosen tool |

Browsing works without any AI. An agent chat is a second way in: it turns a plain-language need into the same search and comparison, cites sources, and asks a clarifying question when it isn't sure.

## Decisions in force

- **No single tool score this release.** Cards show a list of sourced facts instead. Reviews, star ratings and sentiment are future work after the app is stable, and only from sources we're allowed to use.
- **A fact counts only with a source and a date.** Otherwise the card says it's unknown.
- **Plan aware.** A feature counts as already paid for only when a sourced plan covers it. Otherwise the answer is "check your plan" or "upgrade".
- **`pending_review`** means our team hasn't rechecked a tool's facts yet. It has nothing to do with customer reviews.
- **AI calls go through OpenRouter only**, with the key kept on the server and one shared spending cap.

## Build order

1. Intake, catalog match, sourced comparison. Done.
2. Non-duplicate stack check. Done in the API.
3. Plan picker, pending-review labels, correct higher-plan pricing. In progress.
4. Agent chat with a mock adapter first, then the real endpoint.
5. Adoption plan.
6. One bounded live discovery scan: a time limit, saved results to fall back on, a run limit, and a review step so web content never goes straight into the catalog.

After the core path: the custom assistant and the results tracker.

## Stack

- Backend: FastAPI and Pydantic, SQLite seeded from `backend/data/catalog.json`.
- Frontend: React 19, Vite 7, Tailwind 4.
- AI: OpenRouter only.
- Hosting: an Azure VM with Docker and Caddy. Nothing is provisioned yet, and Aurindom approves each step.

## Team

- Aurindom leads and makes the final call.
- Teammate A owns the owner-facing UI.
- Teammate B owns the agent chat in the website.
- Claude builds the backend and the API client. Codex reviews and tests.

## Future work

- Custom assistant: the owner answers a few questions and gets a shareable text assistant, like a barista trainer.
- Results tracker: a private plan link and an estimate-versus-actual log.
- Customer reviews and ratings from permitted sources.
- User accounts, payments, real integrations with tools like Square, and automated check-in reminders. These go in the 16-week continuation plan.

If time runs short, cut in this order: live discovery falls back to saved results, then the adoption plan detail, then chat polish. Browsing and comparison stay.
