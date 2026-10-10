---
name: one-price-visit-screening
description: 2026-10-09 simplification — one recommended bid + 임장/패스 verdict per apartment; how it's computed; margin-benchmark correction
metadata:
  type: project
---
User (2026-10-09): too many options; goal = from hundreds of weekly auctions, quickly find ones worth 임장; same calculation for all, field-checked values go through the same calc, and only ONE recommended bid. Target 매도가 stays "slightly below market" (current est is ~1.9% below real resales — keep, don't raise quantiles).

Implementation (public/index.html): `computePick`/`applyPickToRow` at the end of finalizeBidBoardRow.
- Recommended bid = argmax(낙찰 가능성 × 세후 순이익) over bids with net ≥ 1,000만 (MIN_MARGIN_MANWON). P comes from the 🎲 winbid model; net from solveAuctionBidFromRecord at margins 0/1000/2000/3500, interpolated (bidPlanFor(row, fast)).
- row.recBid / margin are overwritten with the pick (old value kept as recBidOld); recAggr removed.
- 임장 = pick exists, P ≥ VISIT_MIN_P (0.20), not 🚩 강한 의심, not 🏢 bulk; otherwise 패스 with a one-line reason. Apartments only (villa logic deferred).
- Board is `renderBidBoardLite` (state.lite = true): tabs 임장/패스/전체 + 지역 + 정렬; past bids hidden; the old chips/filters are hidden via CSS but code remains. Drawer: pick card on top, "자세히" folded, 직접 확인한 금액 inputs always visible.
- First week: 324 upcoming apts → 28 임장, 296 패스 (197 can't reach 1천만 even at 최저가, 36 low P, 29 too few same-complex trades).

**Correction recorded:** bidCases' estMargin excludes 수리비·대출이자 → not comparable to the app's margin. Like-for-like (최소 수리비 + 이자 포함, 세전) realized margin of flips is median ~1.7% (loss 38%); band table fixed in marginBandStats. So winners accept thin margins vs the app's 7–14% target.
Related: [[winbid-model]], [[resale-detection-limits]], [[first-deal-risk-priority]].
