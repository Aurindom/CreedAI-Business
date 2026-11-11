# Discovery worker

The fetch, extract and store pipeline behind live tool discovery.
`app.live_discovery` supplies the current catalog vocabulary as a snapshot, a live
search adapter, and the app's discovery validator and storage boundary.

Search results are leads only. Vendor pages are fetched independently with
public-IP validation and pinning, bounded redirects, bytes, pages and time, and
conservative source extraction. Unknown pricing and unsupported entitlements stay
unknown. New tools are saved as pending_review and are never treated as verified
recommendations until reviewed.
