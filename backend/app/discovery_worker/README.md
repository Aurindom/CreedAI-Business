# Discovery worker provenance

Promoted from the existing `sandbox/discovery-mcp/discovery_mcp` worker on
2026-11-08; this is the same fetch/extract/store pipeline, not a replacement finder.
`app.live_discovery` supplies the current Catalog vocabulary as Snapshot, a live
search adapter, and the existing app discovery validator/storage boundary.
The old frozen-contract/fixture loader remains unused by the live adapter.

Search results are leads only. Vendor pages are independently fetched with
public-IP validation/pinning, bounded redirects/bytes/pages/time and conservative
source extraction. Unknown pricing and unsupported entitlements remain unknown.
New application tools are pending_review, never automatically verified winners.
