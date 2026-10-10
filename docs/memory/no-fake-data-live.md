---
name: no-fake-data-live
description: Never push fake/test records into the live app's in-memory lists (auctionList etc.) — background code auto-saves them to the server
metadata:
  type: feedback
---
2026-10-05: to preview the merged 💼 내 자산 layout I pushed two fake '매도완료' objects into `auctionList` in the live site's browser tab. One (with a real-looking address) was auto-saved to the server by background code (likely geocode/coord update → save), and it briefly fed 2,325만 of fake income into tax calcs. I deleted it via deleteAuctionAPI('test_x1') and verified it was gone.

**Why:** the live app persists objects in its lists from many background paths; the user's real tax/bid numbers depend on that data.
**How to apply:** for UI previews, render with a local copy (e.g. a scratch HTML or monkeypatched render function that takes data as an argument) or a local dev server — never mutate live global lists. If it happens, tell the user and clean up immediately.
