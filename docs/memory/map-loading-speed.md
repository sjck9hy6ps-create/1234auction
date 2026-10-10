---
name: map-loading-speed
description: Map badge loading-speed work (2026-10-03): causes found, fixes, measured before/after, measurement method
metadata:
  type: project
---

On 2026-10-03 the user asked for much faster badge loading. Causes found:
- get-house payloads for big regions are 9–13MB. They never fit the Redis cache, so every visit re-queried Supabase (3–18s).
- The Redis TTL was 10h and no workflow ran warmup-house-cache.
- placeAuctionMarker computed getAuctionWonEstimates (findSimilarComps) even for suppressed badges, freezing the page for about 4.9s.
- calcPriceGrades called calcPppForGrade twice per building.

Fixes (commits 20c15da, fb3ea9c and the next one):
- Redis values are gzip+base64 with a 'gz:' prefix; TTL is 8 days.
- data-health.yml now warms all 257 LAWD codes after the Tuesday check.
- IndexedDB per-region cache (6h, 12 regions) via fetchHouseDataCached.
- awEst is computed only for badges that are actually drawn.
- The idle debounce went from 1200ms to 600ms.

Measured results:
- 부천 get-house: 6–7s → 0.4s.
- First visit to a big region (서초): first badges 3.6s, all badges 6.9s. Previously 부천 took about 26s.
- In-session revisit: about 2s.

How to measure: wrap the global functions in the live page and poll `Object.keys(markers).length` over time. Don't delete `dataCache` entries during a test; that froze the tab.
