---
name: redis-limit-incident
description: 2026-10-03 incident — Upstash Redis hit the plan limit and all reads/writes were blocked (auctions/bidCases/siteNotes looked empty)
metadata:
  type: project
---

On 2026-10-03, after the loading-speed work, Upstash returned this for every command:

> 403 "ERR This database has reached current Fixed plan limits"

The app showed 0 auctions, bid cases and site notes. The data was not deleted, only blocked.

Likely cause: my gzip house_* caches for all 257 regions, kept for 8 days by the data-health warmup, filled the plan.

Mitigation pushed (49bf2c2):
- House cache back to 10h, capped at 600KB per region; the warmup step was removed.
- api/auction returns 503 on store errors, and POST/DELETE refuse to write. Before this, a read error looked like an empty list and a save could overwrite real data.
- The app shows a red "불러올 수 없음 - 저장하지 마세요" banner.
- api/auction?diag=1 is a read-only status check.

The user must resolve the limit in the Upstash console (upgrade/auto-upgrade, delete house_* keys, or wait for expiry). I cannot purchase.

**Why:** critical user data shares a DB with bulky caches.
**How to apply:** never put large or bulk caches in the Upstash DB that holds auctions/bidCases/siteNotes. Consider moving that user data to Supabase.

Confirmed in the console: the limit hit was **monthly bandwidth** (12GB / 10GB), not storage (102MB / 256MB). Upstash says "Database is suspended". The console Data Browser and CLI are unavailable too. HOUSE_REDIS_CACHE_ENABLED is now false in get-house.js, so the house cache no longer goes through Upstash. Unblocking requires an upgrade or waiting for the monthly reset (Nov 1).

Resolved 2026-10-03. The user upgraded to pay-as-you-go but wants to return to free.
- Backups: ../backups/2026-10-03/{auctions,bidCases,siteNotes}.json (1517/2447/8 items).
- house_* keys cleared.
- api/auction.js was redesigned (61a07dc) to a per-item hash `h:<kind>` plus a version key `v:<kind>`. The legacy arrays were renamed to `<kind>:legacy_backup`.
- The client keeps {ver, list} in IndexedDB 'auction-list-cache' and fetches with ?withVer=1&since=ver. A repeat load now transfers about 0KB, and a save sends one item.
- Migration verified identical to the backup.
