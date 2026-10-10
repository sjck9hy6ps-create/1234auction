---
name: ui-redesign-asil
description: 2026-10-04 UI redesign modeled on asil.kr (layout only), and how it is wired
metadata:
  type: project
---

The user asked for a UI like 아실 (asil.kr). Only the layout and readability were adopted, not branding.

How it is built (index.html):
- New frame: #topbar (blue, with search and main menus plus 더보기), #chipbar (type buttons plus proxy chips), #sidebar (left list of complexes in the viewport, sortable 인기/거래량/평단가/입주년도/이름; a bottom sheet on mobile), #right-tools (geo tools plus 범례/경계).
- relocateUiV2() moves the existing elements into the new frame, so ids and handlers are unchanged. Chips use data-proxy to click the original buttons.
- badgeMode in localStorage: 'simple' is the default. createMarker calls applySimpleBadge (2 lines: name + 평형·latest price). Auction and bid-case badges use applySimpleAuctionBadge (3 lines). The 배지 chip toggles back to the old detailed badges.
- #map is offset by margin-top 96px and margin-left 320px (when the sidebar is open), and calls map.relayout on toggle.

Also fixed:
- updateCurrentDongArea retries after an in-flight calculation. Before, the dong filter stuck to the first location and hid all badges.
- Auction 예상매도가 is not computed when the subject's 시군구 isn't loaded yet (it gave a wrong low value).
