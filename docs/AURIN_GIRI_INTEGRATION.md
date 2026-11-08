# Aurin integration into Giri: 2026-11-08

Merged `origin/aurin-test` at `1e77d78` into `giri-test`, starting from `93373a9`. This adds the incoming Hermes routing, model gateway, public operations, discovery and automatic evidence verification work while retaining account favourites, 30-day chat retention, history deletion and the updated Mailjet handoff. The source `aurin-test` branch was not modified.

Integration decisions:

- The directory-card conflict keeps both automatic-verification labels and favourite hearts.
- The development proxy defaults to the existing local backend at port 8000. `API_PROXY_TARGET` can select a V2 backend such as `http://127.0.0.1:8152`. Local Vite cache stays in the existing sandbox location.
- Action-status messages now round-trip through account chat history; unsupported statuses are rejected. This prevents the incoming action UI from making saved snapshots fail validation.
- The summary retains incoming source dates, evidence and vendor questions. The default compact print is one page; the owner can select detailed sources and questions for a longer printout. Source details remain available in the preview.

Verification on the integrated tree: 995 backend tests, 36 frontend tests and the Vite production build passed. The 11-check favourites browser journey passed using real local API/SQLite/Redis and a synthetic identity provider. Desktop/mobile Chrome printing passed; the sample default PDF was one page and the detailed version two pages. Native Safari printing and real Supabase two-account delivery were not re-tested by these checks.

Local configuration remains the existing OpenRouter runtime with a USD1 cap. No Hermes/MCP/discovery services were enabled or paid model checks run as part of this merge. Incoming V2 deployment and spending records describe that checkout's historical tests, not authorization to raise this workspace's limit.
