# Owner toolkit UI

The storefront showcase leads into three functional entry points: explore a task, compare a subscription, or open account favourites. Category shortcuts come from the live catalog. The optional business form keeps existing subscriptions and plan selectors behind an expandable control, with selected counts preserved.

The directory search filters the loaded catalog by name, summary and capability text. It does not call a model, classify owner intent or change recommendation ranking. It preserves the active category and offers a clear way to reset search and category filters when there are no matches. Recommendation cards keep plan details and sources expandable.

A floating comparison tray shows the current selection, supports removal/clearing, and jumps to the comparison workspace. The existing three-tool limit still applies. On small screens the tray occupies the space beside Penny, with shorter controls and no duplicated name chips. Reduced-motion navigation avoids smooth scrolling and hover movement.

The responsive start cards use SVG illustrations and static gradients; no extra image, font service or animation runtime was added. Price, fit, verification and account rules remain server controlled. No paid model requests are needed for these flows.

## Verification

Run the frontend test suite and production build normally. With the app running locally and Playwright available, run `node frontend/e2e/usability.cjs` from the repository root. `QA_FRONTEND_URL` can select another local frontend. `PLAYWRIGHT_MODULE` and `QA_BROWSER_PATH` support an existing test environment, as described in `FAVOURITES_AND_RETENTION.md`.

The browser journey checks the three starting paths, category selection, directory search, empty-result recovery, selection limits, comparison navigation/clearing and expandable evidence at 1440px, 820px, 390px and 320px widths. It checks horizontal overflow, tray/Penny overlap and page errors. Screenshots and results are saved under ignored `sandbox/`.

The existing two-account favourites journey and summary-print checks also passed after the UI changes. Those favourites checks use a synthetic identity provider with real local API/SQLite/Redis; they do not establish live Supabase email delivery. The tested default summary PDF remained one page.
