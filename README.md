# Main Street AI

This is the independent V2 integration checkout. Start with [V2 integration and acceptance](docs/V2_INTEGRATION_REPORT.md) for merge decisions, real API/browser results, cost accounting and Claude review instructions.

A task-first marketplace that helps small business owners who aren't technical find, compare and adopt AI tools. Every fact on a tool card has a source and the date it was checked.

Built for the UMD AI for Small Business Hack-a-thon, Fall 2026. This is a working prototype.

- **Teammates start here:** [`TEAMMATES handoff.md`](TEAMMATES%20handoff.md)
- **Product plan:** [`PLAN.md`](PLAN.md)
- **Architecture (target design):** [`docs/architecture.md`](docs/architecture.md)
- **Deferred work:** [`docs/FUTURE_WORK.md`](docs/FUTURE_WORK.md)

## Quick start

Clone this repo next to an empty `sandbox` folder. Test databases, build output and the virtualenv go there, never into the repo.

Requires Python 3.11+ and Node 20.19+. No API key is needed to browse.

```
cd hackathon-app/backend
python -m venv ../../sandbox/venv
source ../../sandbox/venv/bin/activate
pip install -r requirements-dev.txt
APP_DB_PATH=../../sandbox/dev.db python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```
cd hackathon-app/frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. PowerShell commands and the test command are in the handoff.
