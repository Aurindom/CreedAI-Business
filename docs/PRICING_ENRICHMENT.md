# Pricing enrichment and official-site fallback

Decision/discussion recorded 2026-11-07. Aurindom wants scalable pricing research for discovered products and an actionable owner experience: a missing price must never become a bare 'Unknown' price on a product card. Use a clickable product icon/name and an explicit official-pricing or contact-sales action instead. This is a display requirement, not permission to invent a numeric price or treat missing costs as zero.

## Worker and integration boundary

Use a dedicated pricing-enrichment adapter/job within discovery. The retained discovery/MCP worker owns changes and primary tests; main Claude continues the app queue. If pricing research is delegated to an additional helper, coordinate disjoint files and let the retained discovery worker integrate/test it. Do not launch a conflicting crawler, modify shared app schemas concurrently or add paid model calls without the existing gate. A coding subagent used during development is separate from a production pricing job; the deployed app cannot assume access to our coding-agent session.

An optional model can extract ambiguous page text into a strict schema; source fetching, validation, cache, arithmetic and publication rules remain code-owned. The requested gpt-5.6-sol name is not a selectable model in Codex's current subagent tool; do not silently substitute another model or assume a production API/model ID or price exists. Choose a supported model only at the appropriate explicit model/spending decision. No model is required for the initial deterministic extraction/fixtures.

## Bounded enrichment flow

1. For each newly discovered/changed product, enqueue a deduplicated job with verified official product/pricing URLs and relevant plan/region/currency/user/usage context. Do not send private owner profiles or access tokens to a general pricing job.
2. Reuse fresh cached facts first. Try an official API/feed when available, accessible public HTML/structured offer data next, browser rendering for script-built pages where allowed, then a bounded optional model extraction if justified and approved. Never assume every vendor publishes an API or machine-readable complete terms.
3. Capture plan name, billing period, currency, regular versus promotional price, commitment, seats/locations, usage allowances and overages, required add-ons and source/date/supporting context. Validate field relationships and exact offer identity. A cheap model's answer or search snippet alone is not checked pricing evidence.
4. Apply limited pages/time/retries per product and global spending/admission caps. Blocked or quote-only pages end gracefully; do not repeatedly pay to retry. Preserve ambiguous/conflicting facts for research and do not silently replace an established price with a guessed one.
5. Persist evidence with freshness and exact units. Price retrieval is not feature entitlement verification or proof the product solves the owner's problem. Run asynchronous refresh so browsing does not wait for a page/model on every visit.
6. Keep a public official-site/pricing link useful even when extraction fails. An unpublished quote cannot be recovered by a better scraper. Private owner-entered quotes stay owner-reported and must not become global public list prices.

## Owner-facing price states

| Internal evidence state | Display/action |
|---|---|
| Checked fixed price | Price with correct plan, unit, billing terms, source/date and 'View official pricing' |
| Published starting/usage price | 'From ...' or stated rate plus limits; estimate only with explicit usage assumptions |
| Quote-only | 'Request a quote' linking to the official sales/pricing page |
| Blocked, unconfirmed or conflicting extraction | 'Check official pricing' linking to the confirmed official page |
| Prior checked price now stale | 'Last checked ...' with its date and 'Check current pricing'; never imply refreshed |
| No confirmed pricing URL | 'Visit official website'; do not invent a /pricing URL |

Make the product icon/name a real accessible external link with an accompanying visible text action. Use an existing approved logo or monogram fallback, not a new scraping/logo service. A link must point to a validated official domain; no model-invented destination. Do not show $0 for a missing price. Other non-price facts may still use explicit unknown/not-checked states.

Internally keep missing numeric values null and preserve reason/freshness. Comparisons can show known facts beside official-pricing links. For incomplete cost totals, show 'Known costs: $X, plus pricing to confirm for [products]' with links; no cheapest, complete-total, savings or budget-fitting claim for the whole solution. Clicking out is a useful fallback, while the marketplace retains its side-by-side comparison.

## Files and focused checks when implemented

- Retained worker's source/extraction/store/contract modules in `sandbox/discovery-mcp/`: pricing adapter, evidence states, caching and fixtures; do not change its directory ownership.
- Main integration: schema/fact/API pricing-state mapping coordinated with Claude, using the same units/offer identities as matching/comparison/adoption. Backwards-compatible display actions can be added without changing existing null arithmetic.
- Teammate A: product card/comparison price text and icon/link states; teammate B renders the backend-provided actions. Neither computes missing prices or implements a separate scraper.
- Test fixed, annual, per-user/usage, promotional, quote-only, blocked, ambiguous currency, conflicting facts, stale cache and missing pricing-link cases. Assert every price-empty card has an official-site action, source/dates survive and incomplete totals never become zero/complete. Repeat jobs reuse cache, same-offer billing is deduplicated correctly, and no arbitrary/private URL can be fetched.

This plan does not authorize a new worker/model call, paid scraper, live scan, Azure deployment or Hermes change. Real discovery still needs the reviewed source adapter and bounded test plan. Customer review/sentiment work remains deferred.
